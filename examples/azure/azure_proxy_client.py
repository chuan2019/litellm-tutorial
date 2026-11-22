"""Drive the Azure proxy with the OpenAI SDK, stage incidents on the fake Azure and read where requests went."""
import os
from collections import Counter

import httpx
from openai import OpenAI

FAKE = os.environ.get("FAKE_AZURE", "http://127.0.0.1:4018")
client = OpenAI(base_url="http://localhost:4000", api_key=os.environ["LITELLM_KEY"], max_retries=0)
MSGS = [{"role": "user", "content": "Weather in Paris?"}]


def seen(kind: str = "chat") -> list[dict]:
    """Return the fake's log: chat requests, or Entra ID token requests."""
    log = httpx.get(f"{FAKE}/_seen").json()
    return [r for r in log if ("token" in r["path"]) == (kind == "token")]


def ask(alias: str):
    return client.chat.completions.with_raw_response.create(model=alias, messages=MSGS)


httpx.get(f"{FAKE}/_reset")
costs = {ask("gpt").headers.get("x-litellm-response-cost") for _ in range(10)}
print("1. 10 calls to 'gpt', by resource:", dict(Counter(r["resource"] for r in seen())), "| cost header:", costs)

httpx.get(f"{FAKE}/_reset")
httpx.get(f"{FAKE}/_fail", params={"resource": "eastus", "error": "throttled"})
ok = sum(ask("gpt").http_response.status_code == 200 for _ in range(6))
print(f"2. eastus throttled; 6 calls succeeded: {ok} | attempts by resource:",
      dict(Counter(r["resource"] for r in seen())))

httpx.get(f"{FAKE}/_reset")
for resource in ("eastus", "swedencentral"):
    httpx.get(f"{FAKE}/_fail", params={"resource": resource, "error": "filtered"})
raw = ask("gpt")
print("3. content filter in both regions; served by:", raw.headers.get("x-litellm-model-group"),
      "| reply:", repr(raw.parse().choices[0].message.content), "| last path:", seen()[-1]["path"])

httpx.get(f"{FAKE}/_reset")
for _ in range(3):
    ask("gpt-entra")
print("4. gpt-entra x3: Entra ID token requests:", len(seen("token")),
      "| chat auth:", {r["auth"] for r in seen()})

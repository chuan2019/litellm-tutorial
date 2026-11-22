"""Drive the Vertex AI proxy with the OpenAI SDK, stage incidents on the fake Vertex and read where requests went."""
import os
from collections import Counter

import httpx
from openai import OpenAI

FAKE = os.environ.get("FAKE_VERTEX", "http://127.0.0.1:4019")
client = OpenAI(base_url="http://localhost:4000", api_key=os.environ["LITELLM_KEY"], max_retries=0)
MSGS = [{"role": "user", "content": "Weather in Paris?"}]


def seen(kind: str = "model") -> list[dict]:
    """Return the fake's log: model calls, or token requests."""
    return [r for r in httpx.get(f"{FAKE}/_seen").json() if ("model" in r) == (kind == "model")]


def ask(alias: str):
    return client.chat.completions.with_raw_response.create(model=alias, messages=MSGS)


httpx.get(f"{FAKE}/_reset")
for _ in range(10):
    ask("gemini")
print("1. 10 calls to 'gemini', by location:", dict(Counter(r["location"] for r in seen())))

httpx.get(f"{FAKE}/_reset")
httpx.get(f"{FAKE}/_fail", params={"location": "us-central1", "error": "exhausted"})
ok = sum(ask("gemini").http_response.status_code == 200 for _ in range(6))
print(f"2. us-central1 exhausted; 6 calls succeeded: {ok} | attempts by location:",
      dict(Counter(r["location"] for r in seen())))

httpx.get(f"{FAKE}/_reset")
for location in ("us-central1", "us-east4"):
    httpx.get(f"{FAKE}/_fail", params={"location": location, "error": "exhausted"})
raw = ask("gemini")
print("3. both regions exhausted; served by:", raw.headers.get("x-litellm-model-group"),
      "| reply:", repr(raw.parse().choices[0].message.content))

httpx.get(f"{FAKE}/_reset")
for _ in range(3):
    ask("claude")
print("4. claude x3: token exchanges:", [r["path"] for r in seen("token")],
      "| publisher:", {r["publisher"] for r in seen()}, "| auth:", {r["auth"] for r in seen()})

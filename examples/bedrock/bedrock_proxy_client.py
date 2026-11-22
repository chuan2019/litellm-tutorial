"""Drive the Bedrock proxy and read the fake Bedrock's log: which region, which identity, which body."""
import collections
import os

import httpx
from openai import OpenAI

PROXY = os.environ.get("PROXY_URL", "http://localhost:4000")
FAKE = os.environ.get("BEDROCK_ENDPOINT", "http://127.0.0.1:4015")
client = OpenAI(base_url=PROXY, api_key=os.environ["LITELLM_KEY"])


def ask(alias: str, n: int = 1) -> list:
    """Send n requests; return (served model group, attempted fallbacks) for each."""
    out = []
    for _ in range(n):
        raw = client.chat.completions.with_raw_response.create(
            model=alias, messages=[{"role": "user", "content": "hi"}], max_tokens=32)
        out.append((raw.headers.get("x-litellm-model-group"), raw.headers.get("x-litellm-attempted-fallbacks")))
    return out


def bedrock_calls() -> list:
    return [r for r in httpx.get(f"{FAKE}/_seen").json() if r["path"] != "/"]


httpx.get(f"{FAKE}/_reset")
ask("claude", 10)
print("1. 10 calls to 'claude', by region:", dict(collections.Counter(r["auth"]["region"] for r in bedrock_calls())))

httpx.get(f"{FAKE}/_reset")
httpx.get(f"{FAKE}/_fail", params={"region": "us-west-2", "error": "throttled"})
served = ask("claude", 6)
print("2. us-west-2 throttled; 6 calls succeeded:", len(served), "| attempts by region:",
      dict(collections.Counter(r["auth"]["region"] for r in bedrock_calls())))

httpx.get(f"{FAKE}/_fail", params={"region": "us-east-1", "error": "unavailable"})
print("3. both regions down; served by:", ask("claude", 1)[0],
      "| last Bedrock model:", bedrock_calls()[-1]["path"].split("/")[2])

httpx.get(f"{FAKE}/_reset")
ask("claude-team-b", 3)
seen = httpx.get(f"{FAKE}/_seen").json()
sts = [r for r in seen if r["path"] == "/"]
print("4. claude-team-b x3: STS AssumeRole calls:", len(sts), sts[0]["body"]["RoleArn"] if sts else "",
      "| Bedrock signed by:", {r["auth"]["access_key"] for r in seen if r["path"] != "/"})

httpx.get(f"{FAKE}/_reset")
ask("claude-guarded", 1)
print("5. claude-guarded body carries:", bedrock_calls()[0]["body"].get("guardrailConfig"))

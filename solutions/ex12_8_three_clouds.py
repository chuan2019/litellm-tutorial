"""One alias, three clouds: spread, a throttled cloud taken out, recovery, and what happens when all fail."""
import os
import time

import httpx
from openai import OpenAI, RateLimitError

BEDROCK = os.environ.get("FAKE_BEDROCK", "http://127.0.0.1:4015")
AZURE = os.environ.get("FAKE_AZURE", "http://127.0.0.1:4018")
VERTEX = os.environ.get("FAKE_VERTEX", "http://127.0.0.1:4019")
client = OpenAI(base_url=os.environ.get("PROXY_URL", "http://localhost:4000"),
                api_key=os.environ["LITELLM_MASTER_KEY"], max_retries=0)


def reset() -> None:
    for fake in (BEDROCK, AZURE, VERTEX):
        httpx.get(f"{fake}/_reset")


def counts() -> dict[str, int]:
    """Count model calls each fake received (token and STS requests excluded)."""
    return {"bedrock": sum("/model/" in r["path"] for r in httpx.get(f"{BEDROCK}/_seen").json()),
            "azure": sum("resource" in r for r in httpx.get(f"{AZURE}/_seen").json()),
            "vertex": sum("model" in r for r in httpx.get(f"{VERTEX}/_seen").json())}


def ask():
    return client.chat.completions.with_raw_response.create(
        model="claude", messages=[{"role": "user", "content": "hi"}])


reset()
costs = [float(ask().headers["x-litellm-response-cost"]) for _ in range(12)]
spread = counts()
assert all(spread.values()) and all(c > 0 for c in costs), (spread, costs)
print("1. 12 calls:", spread, "| every call priced:", all(c > 0 for c in costs))

reset()
httpx.get(f"{BEDROCK}/_fail", params={"region": "us-west-2", "error": "throttled"})
ok = sum(ask().http_response.status_code == 200 for _ in range(10))
seen = counts()
assert ok == 10 and seen["bedrock"] == 1, seen
print("2. Bedrock throttled: 10/10 succeeded, attempts:", seen)

time.sleep(8)  # a little longer than cooldown_time
reset()
for _ in range(12):
    ask()
assert counts()["bedrock"] > 0
print("3. after the cooldown, Bedrock serves again:", counts())

reset()
httpx.get(f"{BEDROCK}/_fail", params={"region": "us-west-2", "error": "throttled"})
httpx.get(f"{AZURE}/_fail", params={"resource": "myfoundry", "error": "throttled"})
httpx.get(f"{VERTEX}/_fail", params={"location": "global", "error": "exhausted"})
try:
    ask()
    raise AssertionError("every cloud is down; the call should fail")
except RateLimitError as e:
    print("4. all three clouds throttled: the client gets", e.status_code, "after attempts:", counts())
print("all checks passed")

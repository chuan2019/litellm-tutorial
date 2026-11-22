"""Azure OpenAI on the wire: deployment vs v1 URLs, pricing with base_model, Entra token reuse, mapped errors."""
import os

FAKE = os.environ.get("FAKE_AZURE", "http://127.0.0.1:4018")
os.environ.update(LITELLM_LOCAL_MODEL_COST_MAP="True", AZURE_AUTHORITY_HOST=FAKE, FED_TOKEN="eyJ.federated.sig")

import httpx
import litellm

litellm.suppress_debug_info = True
BASE = f"{FAKE}/westeurope"
MSGS = [{"role": "user", "content": "hi"}]


def chat(model: str, **kw: object):
    return litellm.completion(model=model, messages=MSGS, api_base=BASE, num_retries=0, **kw)


def log() -> list[dict]:
    return httpx.get(f"{FAKE}/_seen").json()


httpx.get(f"{FAKE}/_reset")
r = chat("azure/team-gpt", api_key="k1", api_version="2024-10-21")
req = log()[-1]
assert req["path"] == "/openai/deployments/team-gpt/chat/completions", req
assert req["query"] == "api-version=2024-10-21" and req["auth"] == "api-key k1"
assert r._hidden_params["response_cost"] is None
priced = chat("azure/team-gpt", api_key="k1", api_version="2024-10-21", base_model="azure/gpt-4o")
assert priced._hidden_params["response_cost"] > 0
print("deployment route:", req["path"], "| cost without/with base_model:", None, priced._hidden_params["response_cost"])

chat("azure/team-gpt", api_key="k1", api_version="v1")
req = log()[-1]
assert req["path"] == "/openai/v1/chat/completions" and req["query"] == "" and req["auth"] == "Bearer k1", req
print("v1 route:", req["path"], req["auth"])

httpx.get(f"{FAKE}/_reset")
for _ in range(3):
    chat("azure/team-gpt", api_version="2024-10-21", azure_ad_token="oidc/env/FED_TOKEN",
         tenant_id="tenant-ex", client_id="client-ex")
tokens = [x for x in log() if x["path"].endswith("/oauth2/v2.0/token")]
chats = [x for x in log() if "resource" in x]
assert len(tokens) == 1 and len(chats) == 3
assert len({c["auth"] for c in chats}) == 1 and chats[0]["auth"].startswith("Bearer entra-token-")
print("workload identity: 1 token request for 3 calls, auth:", chats[0]["auth"])

for dep, exc in (("team-gpt-filtered", litellm.ContentPolicyViolationError), ("team-gpt-throttled", litellm.RateLimitError)):
    try:
        chat(f"azure/{dep}", api_key="k1", api_version="2024-10-21")
        raise AssertionError(f"{dep} should fail")
    except exc as e:
        print(f"{dep}: {type(e).__name__} {e.status_code}")
print("all checks passed")

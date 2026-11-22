"""What LiteLLM sends to Azure: deployments, API versions, Foundry models, Entra ID tokens, errors."""
import json
import os

for var in ("AZURE_API_KEY", "AZURE_AD_TOKEN", "AZURE_CLIENT_SECRET", "AZURE_TENANT_ID", "AZURE_CLIENT_ID"):
    os.environ.pop(var, None)
FAKE = os.environ.get("FAKE_AZURE", "http://127.0.0.1:4018")
# Entra ID tokens are requested from {AZURE_AUTHORITY_HOST}/{tenant}/oauth2/v2.0/token; the fake plays Entra ID too.
os.environ.update(LITELLM_LOCAL_MODEL_COST_MAP="True", AZURE_AUTHORITY_HOST=FAKE,
                  FEDERATED_TOKEN="eyJ.fake-federated-jwt.sig")

import httpx
import litellm

litellm.suppress_debug_info = True
MSGS = [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Weather in Paris?"}]
EASTUS = f"{FAKE}/eastus"           # stands in for https://<resource>.openai.azure.com
FOUNDRY = f"{FAKE}/myfoundry"       # stands in for https://<resource>.services.ai.azure.com


def call(label: str, model: str, show_body: bool = False, repeat: int = 1, **kwargs: object) -> None:
    """Make `repeat` calls against the fake Azure and print the last reply and what reached the wire."""
    httpx.get(f"{FAKE}/_reset")
    try:
        for _ in range(repeat):
            r = litellm.completion(model=model, messages=MSGS, max_tokens=64, num_retries=0, **kwargs)
        cost = r._hidden_params.get("response_cost")
        result = f"cost ${cost:.8f}" if cost is not None else "cost None"
    except Exception as e:  # LiteLLM's mapped errors don't all share one base class
        result = f"{type(e).__name__} {getattr(e, 'status_code', '')}"
    print(f"{label:38} {result}")
    for req in httpx.get(f"{FAKE}/_seen").json():
        where = f"{req.get('resource', 'entra')}{req['path']}" + (f"?{req['query']}" if req.get("query") else "")
        print(f"    POST {where:72} {req['auth']}")
        if show_body:
            print("    body:", json.dumps(req["body"]))


print("== Azure OpenAI: deployments and API versions")
call("deployment, API key", "azure/gpt4o-prod", show_body=True,
     api_base=EASTUS, api_key="azure-key-1", api_version="2024-10-21")
call("same, with base_model for pricing", "azure/gpt4o-prod",
     api_base=EASTUS, api_key="azure-key-1", api_version="2024-10-21", base_model="azure/gpt-4o")
call("v1 API (api_version=v1)", "azure/gpt4o-prod",
     api_base=EASTUS, api_key="azure-key-1", api_version="v1", base_model="azure/gpt-4o")
print("== Microsoft Foundry models")
call("Claude in Foundry", "azure_ai/claude-haiku-5-5", show_body=True, api_base=FOUNDRY, api_key="foundry-key")
call("Llama in Foundry", "azure_ai/Llama-4-Maverick-17B-128E-Instruct-FP8",
     api_base=f"{FOUNDRY}/models", api_key="foundry-key")
print("== Entra ID instead of keys")
call("static Entra ID token", "azure/gpt4o-prod",
     api_base=EASTUS, api_version="2024-10-21", azure_ad_token="eyJ.entra-access-token.sig")
call("workload identity (OIDC), 3 calls", "azure/gpt4o-prod", repeat=3,
     api_base=EASTUS, api_version="2024-10-21", azure_ad_token="oidc/env/FEDERATED_TOKEN",
     tenant_id="tenant-1", client_id="client-1")
print("== errors")
for word in ("throttled", "filtered", "missing", "unavailable"):
    call(f"deployment answers '{word}'", f"azure/gpt4o-{word}",
         api_base=EASTUS, api_key="azure-key-1", api_version="2024-10-21")

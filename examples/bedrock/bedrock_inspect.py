"""What LiteLLM sends to Bedrock: model IDs, routes, request translation, signing, assumed roles, errors."""
import json
import os

for var in ("AWS_PROFILE", "AWS_SESSION_TOKEN", "AWS_BEARER_TOKEN_BEDROCK"):
    os.environ.pop(var, None)
# Fake static keys, only so the request can be signed for the fake endpoint; never do this with real keys.
os.environ.update(LITELLM_LOCAL_MODEL_COST_MAP="True", AWS_REGION="us-west-2",
                  AWS_ACCESS_KEY_ID="AKIAFAKEEXAMPLE0001", AWS_SECRET_ACCESS_KEY="fake-secret")

import httpx
import litellm

litellm.suppress_debug_info = True
FAKE = os.environ.get("FAKE_BEDROCK", "http://127.0.0.1:4015")
MSGS = [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Weather in Paris?"}]
TOOLS = [{"type": "function", "function": {"name": "get_weather", "description": "Weather for a city",
          "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}]


def call(label: str, model: str, show_body: bool = False, fail: str | None = None, **kwargs: object) -> None:
    """Make one call against the fake Bedrock and print the reply and what reached the wire."""
    httpx.get(f"{FAKE}/_reset")
    if fail:
        httpx.get(f"{FAKE}/_fail", params={"region": "us-west-2", "error": fail})
    try:
        r = litellm.completion(model=model, messages=kwargs.pop("messages", MSGS), max_tokens=64,
                               aws_bedrock_runtime_endpoint=FAKE, num_retries=0, **kwargs)
        result = f"cost ${r._hidden_params['response_cost']:.8f}"
    except litellm.exceptions.APIError as e:
        result = f"{type(e).__name__} {e.status_code}"
    except Exception as e:  # LiteLLM's mapped errors don't all share one base class
        result = f"{type(e).__name__} {getattr(e, 'status_code', '')}"
    print(f"{label:36} {result}")
    for req in httpx.get(f"{FAKE}/_seen").json():
        a = req["auth"]
        signer = f"{a['scheme']} {a.get('access_key', '')} {a.get('region', '')}/{a.get('service', '')}".rstrip("/ ")
        print(f"    POST {req['path']:58} {signer}{'  +session token' if req['session_token'] else ''}")
        if show_body:
            print("    body:", json.dumps(req["body"]))


print("== model IDs and routes")
call("regional inference profile", "bedrock/us.anthropic.claude-haiku-5-5", show_body=True)
call("same model, Invoke route", "bedrock/invoke/us.anthropic.claude-haiku-5-5", show_body=True)
call("global inference profile", "bedrock/global.anthropic.claude-haiku-5-5")
call("Amazon Nova (Converse)", "bedrock/us.amazon.nova-2-lite-v1:0")
call("application inference profile ARN", "bedrock/arn:aws:bedrock:us-west-2:123456789012:application-inference-profile/"
     "a1b2c3", base_model="anthropic.claude-haiku-5-5")

print("== request features")
call("tools", "bedrock/us.anthropic.claude-haiku-5-5", show_body=True, tools=TOOLS)
call("Bedrock Guardrails on the call", "bedrock/us.anthropic.claude-haiku-5-5", show_body=True,
     guardrailConfig={"guardrailIdentifier": "gr-abc123", "guardrailVersion": "1"})

print("== credentials and region")
call("aws_region_name=eu-west-1", "bedrock/eu.anthropic.claude-haiku-5-5", aws_region_name="eu-west-1")
call("assume a role first (STS)", "bedrock/us.anthropic.claude-haiku-5-5",
     aws_role_name="arn:aws:iam::123456789012:role/litellm-bedrock", aws_session_name="litellm-proxy",
     aws_sts_endpoint=FAKE)
call("Bedrock API key (bearer token)", "bedrock/us.anthropic.claude-haiku-5-5", api_key="bedrock-api-key-fake")

print("== errors")
for word in ("throttled", "denied", "invalid", "unavailable"):
    call(f"Bedrock answers '{word}'", "bedrock/us.anthropic.claude-haiku-5-5", fail=word)

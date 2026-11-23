"""Amazon Bedrock Mantle from the SDK: one provider, three request formats, two ways to authenticate."""
import os

from _mock import LIVE

if not LIVE:
    for var in ("AWS_PROFILE", "AWS_SESSION_TOKEN", "AWS_BEARER_TOKEN_BEDROCK", "BEDROCK_MANTLE_API_KEY"):
        os.environ.pop(var, None)
    # Fake static keys, only so the offline request can be signed; never put real keys in code.
    os.environ.update(AWS_ACCESS_KEY_ID="AKIAFAKEEXAMPLE0001", AWS_SECRET_ACCESS_KEY="fake-secret")
os.environ.setdefault("AWS_REGION", "us-west-2")

from _wire import auth, outcome, send  # first: it sets the env vars LiteLLM reads when imported
import boto3
import httpx
import litellm
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest


GPT_OSS = "bedrock_mantle/openai.gpt-oss-120b"
GEMMA = "bedrock_mantle/google.gemma-4-31b"
GPT5 = "bedrock_mantle/openai.gpt-5.4"
CLAUDE = "bedrock_mantle/anthropic.claude-haiku-4-5"
MSGS = [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Capital of France?"}]


def show(label, fn=litellm.completion, **kwargs):
    """Make one call; print the outcome, the URL, how it authenticated and the shape of the body."""
    if fn is litellm.completion:
        kwargs = {"messages": MSGS, "max_tokens": 64, **kwargs}
    resp, req = send(fn, **kwargs)
    if hasattr(resp, "output"):
        resp = f"{resp.output_text!r} tokens={resp.usage.input_tokens}/{resp.usage.output_tokens}"
    print(f"{label:52} {outcome(resp) if not isinstance(resp, str) else resp}")
    if req:
        body = req["body"]
        print(f"    POST {req['url']}  {auth(req['headers'])}\n"
              f"    body: model={body.get('model')!r}, fields={sorted(k for k in body if k != 'model')}")


def mantle_models(region):
    """List the model IDs Mantle serves in a region: GET /v1/models, signed like any Mantle request."""
    url = f"https://bedrock-mantle.{region}.api.aws/v1/models"
    request = AWSRequest(method="GET", url=url)
    SigV4Auth(boto3.Session().get_credentials().get_frozen_credentials(), "bedrock", region).add_auth(request)
    return sorted(m["id"] for m in httpx.get(url, headers=dict(request.headers)).json()["data"])


if LIVE:
    for region in ("us-west-2", "us-east-1"):
        ids = mantle_models(region)
        print(f"{region}: {len(ids)} models; Claude: {[i for i in ids if 'claude' in i]}; "
              f"gpt-5.5: {'openai.gpt-5.5' in ids}")

print("== one provider, three request formats")
for model in (GPT_OSS, GEMMA, GPT5, CLAUDE):
    show(model, model=model)

print("== region and credentials")
show("region in the model string", model="bedrock_mantle/us-east-2/openai.gpt-oss-120b")
show("aws_region_name='eu-west-1'", model=GPT_OSS, aws_region_name="eu-west-1")
show("api_key= (a made-up Bedrock API key)", model=GPT_OSS, api_key="made-up-bedrock-api-key")
show("api_base without the /v1", model=GPT_OSS, api_base="https://bedrock-mantle.us-west-2.api.aws")

print("== the Responses API")
show("responses(): gpt-oss", fn=litellm.responses, model=GPT_OSS, input="Capital of France?", max_output_tokens=256)
show("responses(): Claude", fn=litellm.responses, model=CLAUDE, input="Capital of France?", max_output_tokens=64)

print("== the same Claude model, three ways")
show("bedrock/mantle/anthropic.claude-haiku-4-5", model="bedrock/mantle/anthropic.claude-haiku-4-5")
show("bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0", model="bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0")
for key in (CLAUDE, "anthropic.claude-haiku-4-5-20251001-v1:0", "us.anthropic.claude-haiku-4-5-20251001-v1:0"):
    price = litellm.model_cost[key]
    print(f"price {key:52} ${price['input_cost_per_token'] * 1e6:.2f} / ${price['output_cost_per_token'] * 1e6:.2f} "
          "per million tokens in/out")

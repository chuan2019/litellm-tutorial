"""Exercise 1.6: what Bedrock Mantle serves in two regions, and one model called both ways in each."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "exercises"))
import _env  # noqa: E402

import boto3  # noqa: E402
import httpx  # noqa: E402
import litellm  # noqa: E402
from botocore.auth import SigV4Auth  # noqa: E402
from botocore.awsrequest import AWSRequest  # noqa: E402

REGIONS = ("us-west-2", "us-east-1")
MODEL = "openai.gpt-oss-120b"

if not _env.LIVE:
    sys.exit("this exercise lists Mantle's models and needs LIVE=1 and AWS credentials")


def mantle_models(region):
    url = f"https://bedrock-mantle.{region}.api.aws/v1/models"
    request = AWSRequest(method="GET", url=url)
    SigV4Auth(boto3.Session().get_credentials().get_frozen_credentials(), "bedrock", region).add_auth(request)
    response = httpx.get(url, headers=dict(request.headers))
    response.raise_for_status()
    return {m["id"] for m in response.json()["data"]}


catalogue = {region: mantle_models(region) for region in REGIONS}
for region in REGIONS:
    other = next(r for r in REGIONS if r != region)
    only = sorted(catalogue[region] - catalogue[other])
    print(f"{region}: {len(catalogue[region])} models, {len(only)} only here, {only}")
    print(f"    Claude Haiku 5.5 offered: {'anthropic.claude-haiku-5-5' in catalogue[region]}")

for region in REGIONS:
    assert MODEL in catalogue[region], (region, MODEL)
    chat = litellm.completion(model=f"bedrock_mantle/{MODEL}", aws_region_name=region, max_tokens=300,
                              messages=[{"role": "user", "content": "Capital of France? One word."}])
    resp = litellm.responses(model=f"bedrock_mantle/{MODEL}", aws_region_name=region,
                             input="Capital of France? One word.", max_output_tokens=300)
    print(f"{region}: completion -> {chat.choices[0].message.content!r} "
          f"cost=${chat._hidden_params['response_cost']:.6f} | responses -> {resp.output_text!r}")
    assert "paris" in chat.choices[0].message.content.lower() and "paris" in resp.output_text.lower()
print("all checks passed")

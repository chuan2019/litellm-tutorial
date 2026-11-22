"""Provider-native context features through LiteLLM: context editing, compaction, prompt caching, the memory tool."""
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "bedrock"))
for var in ("AWS_PROFILE", "AWS_SESSION_TOKEN", "AWS_BEARER_TOKEN_BEDROCK"):
    os.environ.pop(var, None)
# Fake static keys, only so the request can be signed for the fake endpoint; never do this with real keys.
os.environ.update(LITELLM_LOCAL_MODEL_COST_MAP="True", AWS_REGION="us-west-2",
                  AWS_ACCESS_KEY_ID="AKIAFAKEEXAMPLE0001", AWS_SECRET_ACCESS_KEY="fake-secret")

import httpx
import litellm

import _fake_upstream
import fake_bedrock


def start(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_port}"


ANTHROPIC, BEDROCK = start(_fake_upstream.Handler), start(fake_bedrock.Handler)
MSGS = [{"role": "system", "content": "Static rules: answer in one line."}, {"role": "user", "content": "Status?"}]
CLEAR_OLD_TOOL_RESULTS = {"edits": [{"type": "clear_tool_uses_20250919",
                                     "trigger": {"type": "input_tokens", "value": 30000},
                                     "keep": {"type": "tool_uses", "value": 3}, "exclude_tools": ["memory"]}]}
MEMORY_TOOL = [{"type": "memory_20250818", "name": "memory"}]


def anthropic(**kwargs):
    """Call the fake Anthropic API and return the body and anthropic-beta header it received."""
    litellm.completion(model="anthropic/claude-haiku-5-5", messages=MSGS, api_key="fake", api_base=ANTHROPIC, **kwargs)
    seen = httpx.get(f"{ANTHROPIC}/_seen").json()[-1]
    return json.loads(seen["body"]), seen["headers"].get("anthropic-beta")


def bedrock(model, **kwargs):
    """Call the fake Bedrock and return the route and the body fields beyond the messages."""
    litellm.completion(model=model, messages=MSGS, aws_bedrock_runtime_endpoint=BEDROCK, num_retries=0, **kwargs)
    seen = httpx.get(f"{BEDROCK}/_seen").json()[-1]
    extra = {k: v for k, v in seen["body"].items() if k not in ("messages", "inferenceConfig", "max_tokens", "anthropic_version")}
    return seen["path"].rsplit("/", 1)[-1], extra


print("== 1. context editing: let Anthropic clear old tool results")
body, beta = anthropic(context_management=CLEAR_OLD_TOOL_RESULTS)
print("beta   :", beta)
print("sent   :", body["context_management"]["edits"][0]["type"], "| keep", body["context_management"]["edits"][0]["keep"])

print("== 2. server-side compaction, OpenAI-style input")
body, beta = anthropic(context_management=[{"type": "compaction", "compact_threshold": 150000}])
print("beta   :", beta)
print("sent   :", body["context_management"])

print("== 3. prompt caching: mark the stable prefix")
body, _ = anthropic(cache_control_injection_points=[{"location": "message", "role": "system"}])
print("system :", body["system"])
_, extra = bedrock("bedrock/us.anthropic.claude-haiku-5-5",
                   cache_control_injection_points=[{"location": "message", "role": "system"}])
print("bedrock:", extra["system"])

print("== 4. Anthropic's memory tool is passed through")
body, beta = anthropic(tools=MEMORY_TOOL)
print("tools  :", body["tools"], "| beta:", beta)

print("== 5. on Bedrock it depends on the route")
for model in ("bedrock/us.anthropic.claude-haiku-5-5", "bedrock/invoke/us.anthropic.claude-haiku-5-5"):
    route, cm = bedrock(model, context_management=CLEAR_OLD_TOOL_RESULTS)
    _, tools = bedrock(model, tools=MEMORY_TOOL)
    print(f"{model:44} {route:8} context_management={'context_management' in cm}  memory tool={'tools' in tools}")

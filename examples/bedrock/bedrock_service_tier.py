"""Bedrock service tiers: what `service_tier` puts on the wire, what comes back, and what it costs."""
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
NOVA = "bedrock/us.amazon.nova-2-lite-v1:0"  # priced per tier in LiteLLM's table
MSGS = [{"role": "user", "content": "Capital of France?"}]


def call(label: str, model: str = NOVA, serve: str | None = None, fail: str | None = None, **kwargs: object) -> None:
    """One call against the fake Bedrock: the tier sent, the tier reported back, and the cost LiteLLM recorded."""
    httpx.get(f"{FAKE}/_reset")
    if serve:
        httpx.get(f"{FAKE}/_serve", params={"tier": serve})
    if fail:
        httpx.get(f"{FAKE}/_fail", params={"region": "us-west-2", "error": fail})
    try:
        r = litellm.completion(model=model, messages=MSGS, max_tokens=32,
                               aws_bedrock_runtime_endpoint=FAKE, num_retries=0, **kwargs)
        result = f"reply tier={str(getattr(r, 'service_tier', None)):9} cost ${r._hidden_params['response_cost']:.8f}"
    except Exception as e:  # LiteLLM's mapped errors don't all share one base class
        result = f"{type(e).__name__} {getattr(e, 'status_code', '')}"
    seen = httpx.get(f"{FAKE}/_seen").json()
    sent = [(req["body"] or {}).get("serviceTier") for req in seen]
    wire = f"wire serviceTier={sent[0]}" if seen else "nothing sent"
    print(f"{label:34} {wire:42} {result}")


info = litellm.get_model_info(NOVA)
print("Nova 2 Lite (us.) per 1M tokens, in/out:", *(
    f"{tier} ${info[f'input_cost_per_token{sfx}'] * 1e6:.4f}/${info[f'output_cost_per_token{sfx}'] * 1e6:.4f}"
    for tier, sfx in (("standard", ""), ("flex", "_flex"), ("priority", "_priority"))), sep="\n    ")

print("== the values LiteLLM forwards")
call("no service_tier")
call('service_tier="priority"', service_tier="priority")
call('service_tier="flex"', service_tier="flex")
call('service_tier="default"', service_tier="default")
call('service_tier="auto"', service_tier="auto")

print("== the values LiteLLM drops without a word")
call('service_tier="reserved"', service_tier="reserved")
call('service_tier="standard"', service_tier="standard")
call('service_tier="Priority"', service_tier="Priority")
call('service_tier="ultrafast"', service_tier="ultrafast")

print("== Bedrock decides")
call("asked priority, served default", service_tier="priority", serve="default")
call("Bedrock refuses the tier", service_tier="priority", fail="tier")

print("== other routes and models")
call("Claude Haiku, Converse", "bedrock/us.anthropic.claude-haiku-5-5", service_tier="priority")
call("Claude Haiku, Invoke", "bedrock/invoke/us.anthropic.claude-haiku-5-5", service_tier="priority")
call("Claude Haiku, Invoke, drop_params", "bedrock/invoke/us.anthropic.claude-haiku-5-5", service_tier="priority",
     drop_params=True)

print("== a default tier per deployment (the proxy's model_list works the same way)")
router = litellm.Router(model_list=[{"model_name": "nova-batchy", "litellm_params": {
    "model": NOVA, "aws_bedrock_runtime_endpoint": FAKE, "service_tier": "flex"}}])
for label, kwargs in (("deployment default", {}), ("caller overrides it", {"service_tier": "priority"})):
    httpx.get(f"{FAKE}/_reset")
    r = router.completion(model="nova-batchy", messages=MSGS, max_tokens=32, **kwargs)
    sent = httpx.get(f"{FAKE}/_seen").json()[0]["body"].get("serviceTier")
    print(f"{label:34} {'wire serviceTier=' + str(sent):42} reply tier={r.service_tier:9} "
          f"cost ${r._hidden_params['response_cost']:.8f}")

"""vLLM from the SDK: hosted_vllm/ against a fake vLLM server, compared with the generic openai/ prefix."""
import json
import os

for var in ("OPENAI_API_KEY", "HOSTED_VLLM_API_KEY", "HOSTED_VLLM_API_BASE"):
    os.environ.pop(var, None)

from _wire import outcome, send  # first: it sets the env vars LiteLLM reads when imported
import litellm

from _fake_vllm import start

VLLM = start()
MODEL = "Qwen/Qwen3-8B"
MSGS = [{"role": "user", "content": "Capital of France?"}]
STRICT_TOOL = [{"type": "function", "function": {
    "name": "get_weather", "strict": True, "parameters": {
        "type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"],
        "additionalProperties": False}}}]


def show(label, prefix="hosted_vllm", fields=(), **kwargs):
    """Make one call; print the outcome, the auth header and the body fields asked for."""
    kwargs.setdefault("api_base", VLLM)
    resp, req = send(litellm.completion, model=f"{prefix}/{MODEL}", messages=kwargs.pop("messages", MSGS),
                     max_tokens=64, **kwargs)
    print(f"{label:34} {outcome(resp)}")
    if req:
        body = {k: req["body"][k] for k in fields if k in req["body"]}
        print(f"    Authorization: {req['headers'].get('authorization')!r}  {json.dumps(body)}")
    return resp


print("== the key and the base URL")
show("hosted_vllm/, no api_key")
show("openai/, no api_key", prefix="openai")
show("hosted_vllm/, api_key='vllm-token'", api_key="vllm-token")
os.environ["HOSTED_VLLM_API_BASE"] = VLLM
show("base from HOSTED_VLLM_API_BASE", api_base=None)

print("== vLLM's own parameters")
show("top_k, min_p, repetition_penalty", fields=("top_k", "min_p", "repetition_penalty"),
     top_k=20, min_p=0.05, repetition_penalty=1.1)
show("thinking budget -> reasoning_effort", fields=("reasoning_effort",),
     thinking={"type": "enabled", "budget_tokens": 1024})
r = show("default: the model thinks")
print(f"    reasoning_content={getattr(r.choices[0].message, 'reasoning_content', None)!r}")
r = show("chat_template_kwargs: no thinking", fields=("chat_template_kwargs",),
         extra_body={"chat_template_kwargs": {"enable_thinking": False}})
print(f"    reasoning_content={getattr(r.choices[0].message, 'reasoning_content', None)!r}")

print("== what hosted_vllm/ changes, and openai/ doesn't")
for prefix in ("hosted_vllm", "openai"):
    resp, req = send(litellm.completion, model=f"{prefix}/{MODEL}", messages=MSGS, api_base=VLLM, api_key="k",
                     tools=STRICT_TOOL)
    fn = req["body"]["tools"][0]["function"]
    print(f"{prefix + '/ strict tool':34} strict={fn.get('strict')!r} "
          f"additionalProperties={fn['parameters'].get('additionalProperties')!r}")
claude_turn = {"role": "assistant", "content": [{"type": "text", "text": "Paris."}],
               "thinking_blocks": [{"type": "thinking", "thinking": "...", "signature": "abc"}]}
history = [*MSGS, claude_turn, {"role": "user", "content": "And of Spain?"}]
for prefix in ("hosted_vllm", "openai"):
    resp, req = send(litellm.completion, model=f"{prefix}/{MODEL}", messages=history, api_base=VLLM, api_key="k")
    sent = req["body"]["messages"][1]
    print(f"{prefix + '/ Claude turn in history':34} content={sent['content']!r} "
          f"thinking_blocks={'thinking_blocks' in sent}")

print("== errors and cost")
show("prompt longer than max_model_len", messages=[{"role": "user", "content": "word " * 40000}])
show("... through openai/", prefix="openai", api_key="k", messages=[{"role": "user", "content": "word " * 40000}])
show("no price for a self-hosted model")
show("price per call", input_cost_per_token=0.1e-6, output_cost_per_token=0.4e-6)
litellm.register_model({f"hosted_vllm/{MODEL}": {
    "litellm_provider": "hosted_vllm", "mode": "chat", "max_input_tokens": 32768,
    "input_cost_per_token": 0.1e-6, "output_cost_per_token": 0.4e-6}})
show("price from register_model()")

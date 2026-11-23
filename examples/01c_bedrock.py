"""AWS Bedrock from the SDK: where each OpenAI parameter lands in the Converse request, and what comes back."""
import json
import os

from _mock import LIVE

if not LIVE:
    for var in ("AWS_PROFILE", "AWS_SESSION_TOKEN", "AWS_BEARER_TOKEN_BEDROCK"):
        os.environ.pop(var, None)
    # Fake static keys, only so the offline request can be signed; never put real keys in code.
    os.environ.update(AWS_ACCESS_KEY_ID="AKIAFAKEEXAMPLE0001", AWS_SECRET_ACCESS_KEY="fake-secret")
os.environ.setdefault("AWS_REGION", "us-west-2")

from _wire import outcome, send  # first: it sets the env vars LiteLLM reads when imported
import litellm


CLAUDE = "bedrock/us.anthropic.claude-haiku-5-5"
NOVA = "bedrock/us.amazon.nova-2-lite-v1:0"
MSGS = [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Capital of France?"}]
CITY = {"type": "json_schema", "json_schema": {"name": "city", "schema": {
    "type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"], "additionalProperties": False}}}
TOOLS = [{"type": "function", "function": {"name": "get_weather", "description": "Weather for a city",
          "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}]
# Fields every request carries; left out of the printout so the differences stand out.
SAME = ("messages", "system", "additionalModelResponseFieldPaths")


def show(label, model, **kwargs):
    """Make one call; print the outcome, the Bedrock path and the body fields other than the messages."""
    resp, req = send(litellm.completion, model=model, messages=kwargs.pop("messages", MSGS), **kwargs)
    print(f"{label:36} {outcome(resp)}")
    if req:
        body = {k: v for k, v in req["body"].items() if k not in SAME}
        print(f"    POST {req['url'].split('amazonaws.com')[-1]}\n    {json.dumps(body)}")
    return resp


print("== the same OpenAI parameters, two model families")
show("max_completion_tokens, stop: Claude", CLAUDE, max_completion_tokens=100, stop=["END"])
show("... and temperature: Nova", NOVA, max_completion_tokens=100, stop=["END"], temperature=0.2)
show("temperature: Claude Haiku 5.5", CLAUDE, max_tokens=100, temperature=0.2)
show("top_p: Claude Haiku 5.5", CLAUDE, max_tokens=100, top_p=0.9)
show("response_format: Claude", CLAUDE, max_tokens=200, response_format=CITY)
show("response_format: Nova", NOVA, max_tokens=200, response_format=CITY)
show("tools, tool_choice='required'", CLAUDE, max_tokens=200, tools=TOOLS, tool_choice="required")
show("reasoning_effort='low': Nova", NOVA, max_tokens=2000, reasoning_effort="low")
show("reasoning_effort='low': Claude", CLAUDE, max_tokens=2000, reasoning_effort="low")
show("thinking budget_tokens=1024: Claude", CLAUDE, max_tokens=2000,
     thinking={"type": "enabled", "budget_tokens": 1024})
show("seed", CLAUDE, max_tokens=100, seed=7)
show("seed, drop_params=True", CLAUDE, max_tokens=100, seed=7, drop_params=True)
show("user", NOVA, max_tokens=100, user="user-123")

print("== Bedrock's own parameters")
show("service_tier='flex'", NOVA, max_tokens=100, service_tier="flex")
show("requestMetadata", NOVA, max_tokens=100, requestMetadata={"team": "search"})
show("performanceConfig", NOVA, max_tokens=100, performanceConfig={"latency": "optimized"})
show("top_k=5: Nova", NOVA, max_tokens=100, top_k=5)
show("any other keyword", NOVA, max_tokens=100, some_new_field={"on": True})
show("additionalModelRequestFields=", NOVA, max_tokens=100,
     additionalModelRequestFields={"inferenceConfig": {"topK": 5}})

print("== what comes back")
PUZZLE = [{"role": "user", "content": "Is 1001 prime? Answer in one line."}]
for model in (CLAUDE, NOVA):
    resp = show(f"reasoning_effort='medium': {model.split('.')[1]}", model, messages=PUZZLE, max_tokens=4000,
                reasoning_effort="medium")
    if isinstance(resp, litellm.ModelResponse):
        details = resp.usage.completion_tokens_details
        print(f"    reasoning_content={getattr(resp.choices[0].message, 'reasoning_content', None)!r:.60}  "
              f"reasoning_tokens={details and details.reasoning_tokens} of {resp.usage.completion_tokens}")
stream, req = send(litellm.completion, model=CLAUDE, messages=MSGS, max_tokens=100, stream=True,
                   stream_options={"include_usage": True})
print(f"stream=True posts to {req['url'].rsplit('/', 1)[-1]}")
if not isinstance(stream, Exception):
    chunks = list(stream)
    text = "".join(c.choices[0].delta.content or "" for c in chunks if c.choices)
    print(f"  {len(chunks)} chunks -> {text!r}, usage {chunks[-1].usage.prompt_tokens}/{chunks[-1].usage.completion_tokens}")

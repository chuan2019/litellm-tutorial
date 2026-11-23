"""Exercise 1.7: the same Claude model through three Bedrock routes, and a price for the one that has none."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "exercises"))
import _env  # noqa: E402

import litellm  # noqa: E402

ROUTES = {
    "Mantle provider": "bedrock_mantle/anthropic.claude-haiku-4-5",
    "bedrock/ Mantle route": "bedrock/mantle/anthropic.claude-haiku-4-5",
    "bedrock-runtime, us. profile": "bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0",
}
MSGS = [{"role": "user", "content": "Capital of France? One word."}]


def run():
    costs = {}
    for label, model in ROUTES.items():
        resp = litellm.completion(model=model, messages=MSGS, max_tokens=10, aws_region_name="us-west-2",
                                  **_env.mock("Paris"))
        costs[label] = resp._hidden_params["response_cost"]
        print(f"  {label:30} {resp.choices[0].message.content!r:10} "
              f"tokens={resp.usage.prompt_tokens}/{resp.usage.completion_tokens} cost={costs[label]}")
    return costs


print("before")
before = run()
assert before["bedrock/ Mantle route"] == 0.0
assert before["Mantle provider"] > 0 and before["bedrock-runtime, us. profile"] > 0
litellm.register_model({ROUTES["bedrock/ Mantle route"]: {
    **litellm.model_cost[ROUTES["Mantle provider"]], "litellm_provider": "bedrock"}})
print("after register_model()")
after = run()
assert after["bedrock/ Mantle route"] == after["Mantle provider"]
if _env.LIVE:
    assert after["bedrock-runtime, us. profile"] > after["Mantle provider"]
print("all checks passed")

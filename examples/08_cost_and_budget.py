"""Count tokens before a call, price it after, and enforce a spend cap."""
import litellm

from _mock import mock

MODEL = "anthropic/claude-sonnet-5-5"
messages = [{"role": "user", "content": "Summarise the plot of Hamlet. " * 20}]

print("prompt tokens (estimate):", litellm.token_counter(model=MODEL, messages=messages))
print("context window:", litellm.get_model_info(MODEL)["max_input_tokens"])

resp = litellm.completion(model=MODEL, messages=messages, **mock("A prince seeks revenge. " * 30))
print(f"this call cost ${litellm.completion_cost(resp):.6f}")

for model in ("anthropic/claude-haiku-5-5", "anthropic/claude-sonnet-5-5", "openai/gpt-4o"):
    info = litellm.get_model_info(model)
    p, c = info["input_cost_per_token"] * 1e6, info["output_cost_per_token"] * 1e6
    print(f"{model:30} ${p:7.2f} per 1M in  ${c:7.2f} per 1M out")


class BudgetGuard:
    """Refuse calls once recorded spend reaches the limit."""

    def __init__(self, limit_usd):
        self.limit, self.spent = limit_usd, 0.0

    def completion(self, **kwargs):
        if self.spent >= self.limit:
            raise RuntimeError(f"budget ${self.limit} reached (spent ${self.spent:.6f})")
        resp = litellm.completion(**kwargs)
        self.spent += litellm.completion_cost(resp)
        return resp


guard = BudgetGuard(limit_usd=0.001)
for i in range(1, 100):
    try:
        guard.completion(model=MODEL, messages=messages, **mock("A prince seeks revenge. " * 30))
    except RuntimeError as e:
        print(f"\ncall {i} refused: {e}")
        break

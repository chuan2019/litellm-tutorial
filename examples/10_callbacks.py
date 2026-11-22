"""Log every call (model, latency, tokens, cost) from one place."""
import litellm
from litellm.integrations.custom_logger import CustomLogger

from _mock import mock


class UsageLog(CustomLogger):
    def __init__(self):
        self.total = 0.0

    def log_success_event(self, kwargs, response_obj, start_time, end_time):
        cost = kwargs.get("response_cost") or 0.0
        self.total += cost
        tags = kwargs["litellm_params"]["metadata"].get("tags")
        print(f"[ok]   {kwargs['model']:22} {(end_time - start_time).total_seconds() * 1000:5.0f}ms "
              f"{response_obj.usage.total_tokens:4} tok  ${cost:.6f}  tags={tags}")

    def log_failure_event(self, kwargs, response_obj, start_time, end_time):
        exc = kwargs.get("exception")
        print(f"[fail] {kwargs['model']:22} {type(exc).__name__}: {str(exc)[:50]}")


litellm.suppress_debug_info = True
log = UsageLog()
litellm.callbacks = [log]

msgs = [{"role": "user", "content": "Give me a fun fact."}]
litellm.completion(model="openai/gpt-4o-mini", messages=msgs, metadata={"tags": ["demo"]},
                   **mock("Octopuses have three hearts."))
litellm.completion(model="anthropic/claude-haiku-5-5", messages=msgs, metadata={"tags": ["demo"]},
                   **mock("Honey never spoils."))
try:
    litellm.completion(model="openai/gpt-4o", messages=msgs, mock_response=litellm.RateLimitError(
        "slow down", llm_provider="openai", model="gpt-4o"))
except litellm.RateLimitError:
    pass
print(f"\nrunning total: ${log.total:.6f}")

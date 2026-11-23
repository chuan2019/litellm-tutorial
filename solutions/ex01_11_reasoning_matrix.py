"""Exercise 1.11: what one reasoning_effort="low" becomes for seven providers."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
os.environ.pop("AWS_PROFILE", None)
os.environ.update(LITELLM_LOCAL_MODEL_COST_MAP="True", HTTPS_PROXY="http://127.0.0.1:9", AWS_REGION="us-west-2",
                  AWS_ACCESS_KEY_ID="AKIAFAKEEXAMPLE0001", AWS_SECRET_ACCESS_KEY="fake-secret",
                  OPENAI_API_KEY="sk-made-up", ANTHROPIC_API_KEY="sk-ant-made-up", GEMINI_API_KEY="made-up")

import litellm  # noqa: E402
from litellm.integrations.custom_logger import CustomLogger  # noqa: E402

from _fake_vllm import start  # noqa: E402

litellm.suppress_debug_info = True
OLLAMA = os.environ.get("OLLAMA_API_BASE", "http://127.0.0.1:11434")
CALLS = {
    "anthropic/claude-haiku-5-5": {},
    "bedrock/us.anthropic.claude-haiku-5-5": {},
    "bedrock/us.amazon.nova-2-lite-v1:0": {},
    "gemini/gemini-2.5-flash": {},
    "openai/gpt-5.5": {},
    "hosted_vllm/Qwen/Qwen3-8B": {"api_base": start()},
    "ollama_chat/qwen3:0.6b": {"api_base": OLLAMA},
}
# Where each provider keeps the setting; every other field is the same request for all of them.
REASONING_KEYS = ("thinking", "output_config", "additionalModelRequestFields", "generationConfig",
                  "reasoning_effort", "think")


class Tap(CustomLogger):
    def log_pre_api_call(self, model, messages, kwargs):
        body = (kwargs.get("additional_args") or {}).get("complete_input_dict") or {}
        self.body = json.loads(body) if isinstance(body, (str, bytes)) else body


tap = Tap()
litellm.callbacks = [tap]
found = {}
for model, extra in CALLS.items():
    tap.body = {}
    try:
        litellm.completion(model=model, messages=[{"role": "user", "content": "What is 17 * 3?"}], max_tokens=600,
                           reasoning_effort="low", num_retries=0, timeout=60, **extra)
    except Exception:  # the hosted providers can't be reached offline; the request was still built
        pass
    found[model] = {k: tap.body[k] for k in REASONING_KEYS if k in tap.body}
    print(f"{model:40} {json.dumps(found[model])}")

assert found["anthropic/claude-haiku-5-5"]["output_config"] == {"effort": "low"}
assert found["bedrock/us.anthropic.claude-haiku-5-5"]["additionalModelRequestFields"]["output_config"] == {"effort": "low"}
assert "reasoningConfig" in found["bedrock/us.amazon.nova-2-lite-v1:0"]["additionalModelRequestFields"]
assert "thinkingBudget" in found["gemini/gemini-2.5-flash"]["generationConfig"]["thinkingConfig"]
assert found["openai/gpt-5.5"]["reasoning_effort"] == found["hosted_vllm/Qwen/Qwen3-8B"]["reasoning_effort"] == "low"
assert found["ollama_chat/qwen3:0.6b"]["think"] is True
print("all checks passed")

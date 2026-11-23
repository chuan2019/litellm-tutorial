"""Exercise 1.9: price a self-hosted vLLM model from its GPU cost, and pass vLLM's own parameters."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import litellm  # noqa: E402
from litellm.integrations.custom_logger import CustomLogger  # noqa: E402

from _fake_vllm import start  # noqa: E402

GPU_DOLLARS_PER_HOUR = 2.50
TOKENS_PER_SECOND = 1500                       # measured throughput, input and output together
PER_TOKEN = GPU_DOLLARS_PER_HOUR / (TOKENS_PER_SECOND * 3600)
MODEL = "hosted_vllm/Qwen/Qwen3-8B"


class Tap(CustomLogger):
    def log_pre_api_call(self, model, messages, kwargs):
        self.body = (kwargs.get("additional_args") or {}).get("complete_input_dict")


tap = Tap()
litellm.callbacks = [tap]
litellm.register_model({MODEL: {"litellm_provider": "hosted_vllm", "mode": "chat", "max_input_tokens": 32768,
                                "input_cost_per_token": PER_TOKEN, "output_cost_per_token": PER_TOKEN}})
base = start()
total = 0.0
for i in range(10):
    resp = litellm.completion(model=MODEL, api_base=base, max_tokens=64, top_k=20,
                              extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                              messages=[{"role": "user", "content": f"Question {i}: capital of France?"}])
    assert resp._hidden_params["response_cost"] is not None
    total += resp._hidden_params["response_cost"]
body = tap.body if isinstance(tap.body, dict) else json.loads(tap.body)
assert body["top_k"] == 20 and body["chat_template_kwargs"] == {"enable_thinking": False}
assert getattr(resp.choices[0].message, "reasoning_content", None) is None
print(f"price per token ${PER_TOKEN:.10f}; 10 calls cost ${total:.6f}; body carried top_k and chat_template_kwargs")
print("all checks passed")

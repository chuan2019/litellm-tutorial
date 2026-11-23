"""Exercise 1.10: provider, credentials, URL and auth header for ten model strings, without sending anything."""
import json
import os

FAKE_ENV = {
    "OPENAI_API_KEY": "sk-made-up", "ANTHROPIC_API_KEY": "sk-ant-made-up", "GEMINI_API_KEY": "made-up",
    "MISTRAL_API_KEY": "made-up", "GROQ_API_KEY": "made-up", "AZURE_AI_API_KEY": "made-up",
    "AZURE_AI_API_BASE": "https://myresource.services.ai.azure.com", "HOSTED_VLLM_API_BASE": "http://127.0.0.1:9/v1",
    "AWS_ACCESS_KEY_ID": "AKIAFAKEEXAMPLE0001", "AWS_SECRET_ACCESS_KEY": "fake-secret", "AWS_REGION": "us-west-2",
}
MODELS = ["openai/gpt-4o-mini", "anthropic/claude-haiku-5-5", "gemini/gemini-2.5-flash", "mistral/mistral-large-latest",
          "groq/llama-3.3-70b-versatile", "azure_ai/claude-haiku-5-5", "azure_ai/mistral-large-3",
          "bedrock/us.anthropic.claude-haiku-5-5", "bedrock_mantle/openai.gpt-oss-120b", "hosted_vllm/Qwen/Qwen3-8B"]
os.environ.pop("AWS_PROFILE", None)
os.environ.update(LITELLM_LOCAL_MODEL_COST_MAP="True", HTTPS_PROXY="http://127.0.0.1:9")

import litellm  # noqa: E402
from litellm.integrations.custom_logger import CustomLogger  # noqa: E402

litellm.suppress_debug_info = True
AUTH_HEADERS = ("authorization", "x-api-key", "api-key", "x-goog-api-key")


class Tap(CustomLogger):
    def log_pre_api_call(self, model, messages, kwargs):
        extra = kwargs.get("additional_args") or {}
        self.url, self.headers = str(extra.get("api_base")), {k.lower() for k in (extra.get("headers") or {})}


tap = Tap()
litellm.callbacks = [tap]
missing = {m: litellm.validate_environment(m)["missing_keys"] for m in MODELS}   # before the fake keys are set
os.environ.update(FAKE_ENV)
rows = {}
for model in MODELS:
    provider = litellm.get_llm_provider(model)[1]
    tap.url, tap.headers = None, set()
    try:
        litellm.completion(model=model, messages=[{"role": "user", "content": "hi"}], max_tokens=5,
                           num_retries=0, timeout=3)
    except Exception:  # nothing listens: every call fails after the request is built
        pass
    auth = [h for h in AUTH_HEADERS if h in tap.headers]
    rows[model] = (provider, tap.url, auth)
    print(f"{model:40} {provider:15} needs={json.dumps(missing[model]):42} auth={auth} {tap.url}")

assert rows["gemini/gemini-2.5-flash"][2] == ["x-goog-api-key"]
assert "x-api-key" in rows["anthropic/claude-haiku-5-5"][2]
assert rows["azure_ai/claude-haiku-5-5"][1].endswith("/anthropic/v1/messages")
assert rows["azure_ai/mistral-large-3"][1].endswith("/models/chat/completions")
assert rows["mistral/mistral-large-latest"][2] == ["authorization"]
assert "/openai/v1/" in rows["groq/llama-3.3-70b-versatile"][1]
print("all checks passed")

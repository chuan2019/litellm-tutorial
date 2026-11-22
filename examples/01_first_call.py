"""One function, many providers: the model string picks the provider."""
from litellm import completion, completion_cost

from _mock import mock

MODELS = [
    "anthropic/claude-sonnet-5-5",
    "openai/gpt-4o-mini",
    "gemini/gemini-2.5-flash",
]
messages = [{"role": "user", "content": "Say hello in French, in three words."}]

for model in MODELS:
    resp = completion(model=model, messages=messages, max_tokens=50,
                      **mock("Bonjour à tous !"))
    print(f"{model:30} -> {resp.choices[0].message.content!r}")
    print(f"{'':30}    tokens in/out={resp.usage.prompt_tokens}/"
          f"{resp.usage.completion_tokens}  cost=${completion_cost(resp):.8f}")

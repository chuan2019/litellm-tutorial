"""Provider errors arrive as OpenAI exception types; retry and fall back."""
import logging

import litellm

litellm.suppress_debug_info = True
# The fallback runner logs each failed attempt with a full traceback, even when a fallback succeeds.
logging.getLogger("LiteLLM").setLevel(logging.CRITICAL)

messages = [{"role": "user", "content": "hi"}]

for err in (
    litellm.RateLimitError("slow down", llm_provider="anthropic", model="claude-sonnet-5-5"),
    litellm.ContextWindowExceededError("too long", llm_provider="gemini", model="gemini-2.5-flash"),
    litellm.AuthenticationError("bad key", llm_provider="openai", model="gpt-4o-mini"),
):
    try:
        litellm.completion(model="openai/gpt-4o-mini", messages=messages, mock_response=err)
    except litellm.RateLimitError as e:
        print(f"RateLimitError       status={e.status_code}  -> back off and retry")
    except litellm.ContextWindowExceededError as e:
        print(f"ContextWindowExceeded status={e.status_code} -> trim input or use a bigger model")
    except litellm.AuthenticationError as e:
        print(f"AuthenticationError  status={e.status_code}  -> fix the key, do not retry")

print()
resp = litellm.completion(
    model="anthropic/claude-sonnet-5-5",
    messages=messages,
    mock_response=litellm.ServiceUnavailableError("overloaded", llm_provider="anthropic",
                                                  model="claude-sonnet-5-5"),
    fallbacks=[{"model": "openai/gpt-4o-mini", "mock_response": "hello from the fallback"}],
)
print("primary failed; answer came from", resp.model, "->", repr(resp.choices[0].message.content))

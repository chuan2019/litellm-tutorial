"""Stream tokens as they arrive, then rebuild the full response."""
import litellm

from _mock import mock

messages = [{"role": "user", "content": "Write a haiku about the sea."}]
stream = litellm.completion(
    model="anthropic/claude-haiku-5-5", messages=messages, stream=True,
    stream_options={"include_usage": True},
    **mock("Grey waves fold and break\nsalt wind carries gull voices\nthe tide keeps its time"),
)

chunks = []
for chunk in stream:
    chunks.append(chunk)
    if chunk.choices and chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="|", flush=True)
print(f"\n\nchunks received: {len(chunks)}")

full = litellm.stream_chunk_builder(chunks, messages=messages)
print("rebuilt text:", repr(full.choices[0].message.content))
print("usage:", full.usage.prompt_tokens, "in /", full.usage.completion_tokens, "out")

"""Ollama from the SDK: where OpenAI parameters land in an Ollama request, against a real local server."""
import json
import os
import time

from _wire import outcome, send  # first: it sets the env vars LiteLLM reads when imported
import litellm


OLLAMA = os.environ.get("OLLAMA_API_BASE", "http://127.0.0.1:11434")
SMALL, THINKER = "ollama_chat/qwen2.5:0.5b", "ollama_chat/qwen3:0.6b"
MSGS = [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Capital of France? Answer in JSON."}]
CITY = {"type": "json_schema", "json_schema": {"name": "city", "schema": {
    "type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}


def show(label, model=SMALL, **kwargs):
    """Make one call; print the reply, the Ollama path and every body field except the messages."""
    start = time.perf_counter()
    resp, req = send(litellm.completion, model=model, messages=kwargs.pop("messages", MSGS),
                     api_base=OLLAMA, timeout=120, **kwargs)
    print(f"{label:30} {time.perf_counter() - start:4.1f}s {outcome(resp)}")
    body = {k: v for k, v in req["body"].items() if k not in ("messages", "model", "stream")}
    print(f"    POST {req['url'].removeprefix(OLLAMA)}  {json.dumps(body)}")
    return resp


print("== OpenAI parameters become Ollama options")
show("max_tokens", max_tokens=20)
show("temperature, seed, stop", max_completion_tokens=20, temperature=0, seed=7, stop=["}"])
show("frequency_penalty=0.5", max_tokens=20, frequency_penalty=0.5)
show("response_format json_schema", max_tokens=40, response_format=CITY)
show("response_format json_object", max_tokens=40, response_format={"type": "json_object"})
show("num_ctx, keep_alive (Ollama's)", max_tokens=20, num_ctx=8192, keep_alive="10m")
show("ollama/ (the generate API)", model="ollama/qwen2.5:0.5b", max_tokens=20)

print("== reasoning")
show("reasoning_effort: qwen2.5", max_tokens=200, reasoning_effort="low")
thought = show("reasoning_effort: qwen3", model=THINKER, max_tokens=400, reasoning_effort="low",
               messages=[{"role": "user", "content": "What is 17 * 3? Reply with the number only."}])
print(f"    reasoning_content: {thought.choices[0].message.reasoning_content!r:.80}")

print("== loading the model")
show("keep_alive=0 (unload after)", max_tokens=5, keep_alive=0)
show("next call: cold", max_tokens=5)
show("next call: warm", max_tokens=5)

"""What LiteLLM sends to model providers directly: OpenAI, Anthropic, vLLM, and a real local Ollama."""
import json
import os
import time

os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

import httpx
import litellm

litellm.suppress_debug_info = True
FAKE = os.environ.get("FAKE_UPSTREAM", "http://127.0.0.1:4011")     # examples/_fake_upstream.py
OLLAMA = os.environ.get("OLLAMA_API_BASE", "http://127.0.0.1:11434")
MSGS = [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Name the capital of France."}]
SHOW_HEADERS = ("authorization", "x-api-key", "anthropic-version")


def call(label: str, model: str, show_body: bool = False, **kwargs: object):
    """Make one call, print the reply, its cost, and what reached the fake upstream (if anything)."""
    seen_before = len(httpx.get(f"{FAKE}/_seen").json())
    start = time.perf_counter()
    r = litellm.completion(model=model, messages=kwargs.pop("messages", MSGS), max_tokens=64, num_retries=0, **kwargs)
    cost = r._hidden_params.get("response_cost")
    msg = r.choices[0].message
    reply = msg.content if not msg.tool_calls else f"tool_calls={[t.function.name for t in msg.tool_calls]}"
    print(f"{label:30} {time.perf_counter() - start:4.1f}s {reply!r:40.40} "
          f"tokens={r.usage.prompt_tokens}/{r.usage.completion_tokens} cost={cost}")
    for req in httpx.get(f"{FAKE}/_seen").json()[seen_before:]:
        hdrs = {k: (v[:20] + "..." if len(v) > 20 else v) for k, v in req["headers"].items() if k in SHOW_HEADERS}
        print(f"    {req['method']} {req['path']:24} {hdrs}")
        if show_body:
            print("    body:", req["body"])
    return r


print("== hosted providers (fake upstream on :4011)")
call("OpenAI", "openai/gpt-4o-mini", show_body=True, api_base=f"{FAKE}/v1", api_key="sk-openai-fake")
call("Anthropic", "anthropic/claude-haiku-5-5", show_body=True, api_base=FAKE, api_key="sk-ant-fake")
print("== self-hosted, OpenAI-compatible servers (fake upstream on :4011)")
call("vLLM (hosted_vllm/)", "hosted_vllm/Qwen/Qwen2.5-7B-Instruct", api_base=f"{FAKE}/v1")
call("any OpenAI-compatible (openai/)", "openai/my-local-model", api_base=f"{FAKE}/v1", api_key="none")
print("== Ollama, a real local server (qwen2.5:0.5b on CPU)")
call("ollama_chat/ (POST /api/chat)", "ollama_chat/qwen2.5:0.5b", api_base=OLLAMA)
call("ollama/ (POST /api/generate)", "ollama/qwen2.5:0.5b", api_base=OLLAMA)
TOOLS = [{"type": "function", "function": {"name": "get_weather", "description": "Weather for a city",
          "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}]
call("ollama_chat/ with tools", "ollama_chat/qwen2.5:0.5b", api_base=OLLAMA, tools=TOOLS,
     messages=[{"role": "user", "content": "What is the weather in Paris? Use the tool."}])
stream = litellm.completion(model="ollama_chat/qwen2.5:0.5b", api_base=OLLAMA, stream=True, max_tokens=32,
                            messages=[{"role": "user", "content": "Count from 1 to 5, separated by spaces."}])
chunks = [c.choices[0].delta.content or "" for c in stream]
print(f"{'ollama_chat/ streaming':30} {len(chunks)} chunks -> {''.join(chunks).strip()!r}")
print("model info:", json.dumps({k: litellm.get_model_info("ollama_chat/qwen2.5:0.5b", api_base=OLLAMA).get(k)
                                 for k in ("max_input_tokens", "input_cost_per_token", "supports_function_calling")}))

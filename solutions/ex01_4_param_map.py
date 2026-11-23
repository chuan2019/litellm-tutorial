"""Exercise 1.4: where OpenAI parameters land in a Bedrock Converse request, captured without sending it."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "exercises"))
import _env  # noqa: E402

if not _env.LIVE:
    os.environ.pop("AWS_PROFILE", None)
    # Fake keys only sign the request; the closed proxy port stops it before it leaves the machine.
    os.environ.update(AWS_ACCESS_KEY_ID="AKIAFAKEEXAMPLE0001", AWS_SECRET_ACCESS_KEY="fake-secret",
                      HTTPS_PROXY="http://127.0.0.1:9")

import litellm  # noqa: E402
from litellm.integrations.custom_logger import CustomLogger  # noqa: E402

litellm.suppress_debug_info = True
CITY = {"type": "json_schema", "json_schema": {"name": "city", "schema": {
    "type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}
TOOLS = [{"type": "function", "function": {"name": "get_weather", "parameters": {
    "type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}]
CASES = {
    "max_completion_tokens + stop": {"max_completion_tokens": 50, "stop": ["END"]},
    "response_format": {"max_tokens": 100, "response_format": CITY},
    "tool_choice=required": {"max_tokens": 100, "tools": TOOLS, "tool_choice": "required"},
    "reasoning_effort=low": {"max_tokens": 2000, "reasoning_effort": "low"},
    "seed": {"max_tokens": 50, "seed": 7},
}
BASE_FIELDS = {"messages", "system", "inferenceConfig", "additionalModelResponseFieldPaths"}


class Tap(CustomLogger):
    def log_pre_api_call(self, model, messages, kwargs):
        body = (kwargs.get("additional_args") or {}).get("complete_input_dict") or {}
        self.body = json.loads(body) if isinstance(body, (str, bytes)) else body


tap = Tap()
litellm.callbacks = [tap]
seen = {}
for model in (_env.FAST, _env.ALT):
    for label, params in CASES.items():
        tap.body = None
        try:
            litellm.completion(model=model, messages=[{"role": "user", "content": "Capital of France?"}],
                               num_retries=0, timeout=5, **params)
        except litellm.UnsupportedParamsError:
            print(f"{model.split('.')[1]:9} {label:30} refused before sending")
            seen[model, label] = "refused" if tap.body is None else "refused, but a request was captured"
            continue
        except Exception:  # offline: the request was built, then failed to connect
            pass
        extra = {k: tap.body[k] for k in tap.body if k not in BASE_FIELDS}
        seen[model, label] = tap.body
        print(f"{model.split('.')[1]:9} {label:30} {json.dumps(extra)[:110]}")

assert "outputConfig" in seen[_env.FAST, "response_format"]
assert seen[_env.ALT, "response_format"]["toolConfig"]["tools"][0]["toolSpec"]["name"] == "json_tool_call"
assert all(seen[m, "tool_choice=required"]["toolConfig"]["toolChoice"] == {"any": {}} for m in (_env.FAST, _env.ALT))
assert seen[_env.FAST, "seed"] == seen[_env.ALT, "seed"] == "refused"
print("all checks passed")

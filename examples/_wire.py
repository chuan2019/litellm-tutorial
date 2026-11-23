"""Record the request LiteLLM builds for each call; offline, stop HTTPS requests before they leave the machine."""
import json
import os

from _mock import LIVE

if not LIVE:
    # A closed local port as the HTTPS proxy: the request is built, signed and recorded, then fails to connect.
    # Plain-HTTP servers on this machine (Ollama, the fake vLLM) are not affected.
    os.environ["HTTPS_PROXY"] = "http://127.0.0.1:9"
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import litellm
from litellm.integrations.custom_logger import CustomLogger

litellm.suppress_debug_info = True


class WireTap(CustomLogger):
    """Keep the URL, headers and body of the last request LiteLLM was about to send."""

    def __init__(self):
        super().__init__()
        self.last = None

    def log_pre_api_call(self, model, messages, kwargs):
        extra = kwargs.get("additional_args") or {}
        body = extra.get("complete_input_dict") or {}
        self.last = {"url": extra.get("api_base") or "",
                     "headers": {k.lower(): str(v) for k, v in (extra.get("headers") or {}).items()},
                     "body": json.loads(body) if isinstance(body, (str, bytes)) else dict(body)}


TAP = WireTap()
litellm.callbacks.append(TAP)


def send(fn, **kwargs):
    """Call fn (litellm.completion, litellm.responses, ...); return (response or exception, request or None)."""
    TAP.last = None
    try:
        result = fn(num_retries=0, **kwargs) if fn is litellm.completion else fn(**kwargs)
    except Exception as e:  # mapped provider errors don't share one base class
        result = e
    return result, TAP.last


def auth(headers):
    """Describe how a request authenticates, without printing the credential."""
    value = headers.get("authorization", "")
    if value.startswith("AWS4-HMAC-SHA256"):
        scope = value.split("Credential=")[1].split(",")[0].split("/")
        return f"SigV4 {scope[2]}/{scope[3]}"
    if value.startswith("Bearer"):
        return "Bearer"
    return "x-api-key" if "x-api-key" in headers else "none"


def outcome(result):
    """One short description of a response or an error."""
    if isinstance(result, Exception):
        if "Connection refused" in str(result) or "ProxyError" in type(result).__name__:
            return "not sent (offline)"
        message = str(result).removeprefix(f"litellm.{type(result).__name__}: ").split("Exception - ")[-1]
        return f"{type(result).__name__}: {message[:80]}"
    if hasattr(result, "choices"):
        msg = result.choices[0].message
        text = msg.content if not msg.tool_calls else f"tool call {msg.tool_calls[0].function.name}"
        cost = result._hidden_params.get("response_cost")
        return f"{text!r:.40} tokens={result.usage.prompt_tokens}/{result.usage.completion_tokens} cost={cost}"
    return repr(result)[:80]

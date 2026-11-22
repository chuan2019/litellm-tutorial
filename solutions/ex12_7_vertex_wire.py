"""Vertex AI on the wire: Gemini vs Claude bodies, locations and prices, token reuse, the 403 mapping."""
import os
from pathlib import Path

os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

import httpx
import litellm

litellm.suppress_debug_info = True
FAKE = os.environ.get("FAKE_VERTEX", "http://127.0.0.1:4019")
SA = (Path(__file__).parent.parent / "examples/vertex/.creds/service-account.json").read_text()
MSGS = [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "hi"}]


def chat(model: str, location: str = "us-central1"):
    return litellm.completion(model=model, messages=MSGS, max_tokens=100, num_retries=0, api_base=FAKE,
                              vertex_project="ex-project", vertex_location=location, vertex_credentials=SA)


def calls() -> list[dict]:
    return [r for r in httpx.get(f"{FAKE}/_seen").json() if "model" in r]


httpx.get(f"{FAKE}/_reset")
for _ in range(3):
    chat("vertex_ai/gemini-2.5-flash")
tokens = [r for r in httpx.get(f"{FAKE}/_seen").json() if r["path"] == "/token"]
assert len(tokens) == 1 and len({r["auth"] for r in calls()}) == 1
print("3 gemini calls, token requests:", len(tokens))

chat("vertex_ai/gemini-2.5-flash")
g = calls()[-1]
assert g["method"] == "generateContent" and g["publisher"] == "google"
assert g["body"]["system_instruction"] == {"parts": [{"text": "Be brief."}]}
assert g["body"]["generationConfig"]["max_output_tokens"] == 100 and "contents" in g["body"]
regional = chat("vertex_ai/claude-haiku-5-5")
c = calls()[-1]
assert c["method"] == "rawPredict" and c["publisher"] == "anthropic"
assert c["body"]["anthropic_version"] == "vertex-2023-10-16" and c["body"]["max_tokens"] == 100
glob = chat("vertex_ai/claude-haiku-5-5", location="global")
assert calls()[-1]["location"] == "global" and "/locations/global/" in calls()[-1]["path"]
assert glob._hidden_params["response_cost"] < regional._hidden_params["response_cost"]
print("gemini:", g["method"], "| claude:", c["method"], "| claude cost regional vs global:",
      regional._hidden_params["response_cost"], glob._hidden_params["response_cost"])

try:
    chat("vertex_ai/gemini-2.5-flash-denied")
    raise AssertionError("should fail")
except Exception as e:  # the 403 is not mapped to PermissionDeniedError
    assert getattr(e, "status_code", None) == 403
    assert not isinstance(e, litellm.PermissionDeniedError)
    print("PERMISSION_DENIED surfaces as", type(e).__name__, e.status_code)
print("all checks passed")

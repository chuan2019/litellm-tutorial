"""What LiteLLM sends to Vertex AI: model families, locations, request translation, Google credentials, errors."""
import json
import os
from pathlib import Path

for var in ("GOOGLE_APPLICATION_CREDENTIALS", "VERTEXAI_CREDENTIALS", "VERTEXAI_PROJECT", "VERTEXAI_LOCATION"):
    os.environ.pop(var, None)
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

import httpx
import litellm

litellm.suppress_debug_info = True
FAKE = os.environ.get("FAKE_VERTEX", "http://127.0.0.1:4019")
CREDS = Path(__file__).parent / ".creds"
SA = (CREDS / "service-account.json").read_text()
WIF = (CREDS / "workload-identity.json").read_text()
MSGS = [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Weather in Paris?"}]
TOOLS = [{"type": "function", "function": {"name": "get_weather", "description": "Weather for a city",
          "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}]


def call(label: str, model: str, show_body: bool = False, repeat: int = 1, **kwargs: object) -> None:
    """Make `repeat` calls against the fake Vertex AI and print the last result and what reached the wire."""
    httpx.get(f"{FAKE}/_reset")
    kwargs = {"vertex_project": "acme-ml-prod", "vertex_location": "us-central1", "vertex_credentials": SA,
              "api_base": FAKE, **kwargs}
    try:
        for _ in range(repeat):
            r = litellm.completion(model=model, messages=MSGS, max_tokens=64, num_retries=0, **kwargs)
        result = f"cost ${r._hidden_params['response_cost']:.8f}"
    except Exception as e:  # LiteLLM's mapped errors don't all share one base class
        result = f"{type(e).__name__} {getattr(e, 'status_code', '')}"
    print(f"{label:36} {result}")
    for req in httpx.get(f"{FAKE}/_seen").json():
        if "model" not in req:
            print(f"    POST {req['path']:70} {json.dumps(req['body'])}")
            continue
        print(f"    POST .../locations/{req['location']}/publishers/{req['publisher']}/models/{req['model']}:"
              f"{req['method']}".ljust(80) + f" {req['auth']}")
        if show_body:
            print("    body:", json.dumps(req["body"]))


print("== model families and locations")
call("Gemini", "vertex_ai/gemini-2.5-flash", show_body=True)
call("Claude on Vertex", "vertex_ai/claude-haiku-5-5", show_body=True)
call("Claude, location global", "vertex_ai/claude-haiku-5-5", vertex_location="global")
call("Gemini, location europe-west4", "vertex_ai/gemini-2.5-flash", vertex_location="europe-west4")
print("== request features")
call("Gemini with tools", "vertex_ai/gemini-2.5-flash", show_body=True, tools=TOOLS)
print("== Google credentials")
call("service-account key, 3 calls", "vertex_ai/gemini-2.5-flash", repeat=3)
call("workload identity federation, 3 calls", "vertex_ai/gemini-2.5-flash", repeat=3, vertex_credentials=WIF)
print("== errors")
for word in ("exhausted", "denied", "missing", "unavailable"):
    call(f"Vertex answers '{word}'", f"vertex_ai/gemini-2.5-flash-{word}")

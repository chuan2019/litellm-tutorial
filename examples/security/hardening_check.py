"""Audit a running proxy from the outside: what it exposes without a key, and what it accepts with one."""
import os
import sys
from urllib.parse import urlparse

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:4100"
KEY = os.environ["PROBE_KEY"]  # any valid key; a low-privilege one is the realistic test
VERIFY = os.environ.get("PROBE_CA", True)  # path to a CA bundle for a private CA
MODEL = os.environ.get("PROBE_MODEL", "chat")
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))


def get(path: str, **kw: object) -> httpx.Response:
    return httpx.get(f"{BASE}{path}", timeout=10, follow_redirects=False, verify=VERIFY, **kw)


def chat(**extra: object) -> httpx.Response:
    return httpx.post(f"{BASE}/v1/chat/completions", headers={"Authorization": f"Bearer {KEY}"}, timeout=30, verify=VERIFY,
                      json={"model": MODEL, "messages": [{"role": "user", "content": "hi"}], **extra})


check("served over TLS", urlparse(BASE).scheme == "https", urlparse(BASE).scheme)

for path, what, marker in (("/", "Swagger UI", "swagger"), ("/redoc", "ReDoc", "redoc"),
                           ("/openapi.json", "OpenAPI schema", "openapi"), ("/ui/", "admin UI", "<html")):
    r = get(path)
    check(f"{what} hidden", r.status_code != 200 or marker not in r.text[:5000].lower(), f"GET {path} -> {r.status_code}")

r = get("/v1/models")
check("LLM routes need a key", r.status_code == 401, f"GET /v1/models without key -> {r.status_code}")
r = get("/v1/models", headers={"Authorization": "Bearer sk-1234"})
check("default key sk-1234 refused", r.status_code in (400, 401, 403), f"-> {r.status_code}")
r = get("/metrics/")
check("metrics need a key", r.status_code == 401, f"GET /metrics/ -> {r.status_code}")

r = chat(api_base="http://169.254.169.254/latest/meta-data")
check("client api_base rejected (SSRF)", r.status_code in (400, 401, 403), f"-> {r.status_code}")
r = chat(api_key="sk-attacker", base_url="http://attacker.example/v1")
check("client base_url rejected", r.status_code in (400, 401, 403), f"-> {r.status_code}")

r = httpx.options(f"{BASE}/v1/chat/completions", timeout=10, verify=VERIFY, headers={
    "Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
acao = r.headers.get("access-control-allow-origin")
check("CORS limited to known origins", acao not in ("*", "https://evil.example"), f"allow-origin: {acao}")

ok = chat()
check("version not advertised", "x-litellm-version" not in ok.headers,
      f"x-litellm-version: {ok.headers.get('x-litellm-version')}")
check("upstream address not leaked", "x-litellm-model-api-base" not in ok.headers,
      f"x-litellm-model-api-base: {ok.headers.get('x-litellm-model-api-base')}")

width = max(len(n) for n, _, _ in results)
for name, passed, detail in results:
    print(f"{'PASS' if passed else 'FAIL'}  {name:{width}}  {detail}")
print(f"\n{sum(p for _, p, _ in results)}/{len(results)} checks passed")

"""Verify the production stack: TLS edge, shared limits across replicas, body cap, logs, containers, DB outage."""
import os
import subprocess
import time
from pathlib import Path

import httpx

HERE = Path(__file__).parent
BASE = "https://localhost:8443"
CA = str(HERE / "certs" / "ca.crt")
ADMIN = {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}
MARKER = f"prompt-marker-{int(time.time())}"


def compose(*args: str) -> str:
    return subprocess.run(["docker", "compose", *args], cwd=HERE, capture_output=True, text=True).stdout


def sh(container: str, cmd: str) -> str:
    return subprocess.run(["docker", "exec", container, "sh", "-c", cmd], capture_output=True, text=True).stdout.strip()


def chat(key: str, content: str = "hi") -> httpx.Response:
    return httpx.post(f"{BASE}/v1/chat/completions", verify=CA, timeout=30, headers={"Authorization": f"Bearer {key}"},
                      json={"model": "chat", "messages": [{"role": "user", "content": content}]})


def chat_requests_per_replica() -> list[int]:
    """Count chat requests in each replica's access log."""
    counts = []
    for i in (1, 2):
        out = subprocess.run(["docker", "logs", f"litellm-prod-proxy-{i}"], capture_output=True, text=True)
        counts.append((out.stdout + out.stderr).count("POST /v1/chat/completions"))
    return counts


print("== 1. TLS only at the edge")
r = httpx.get("http://localhost:8443/health/liveliness")
print(f"  plain HTTP to the TLS port -> {r.status_code}")
r = httpx.get(f"{BASE}/health/liveliness", verify=CA)
print(f"  HTTPS -> {r.status_code}  server: {r.headers['server']}  hsts: {r.headers.get('strict-transport-security')}")

print("== 2. one rate limit across two replicas (coordination Redis)")
key = httpx.post(f"{BASE}/key/generate", verify=CA, headers=ADMIN, json={"models": ["chat"], "rpm_limit": 4}
                 ).json()["key"]
before = chat_requests_per_replica()
codes = [chat(key).status_code for _ in range(10)]
after = chat_requests_per_replica()
print(f"  10 calls, rpm_limit 4: {codes}")
print(f"  calls handled per replica: {[a - b for a, b in zip(after, before)]}")

print("== 3. request size capped at the edge")
r = httpx.post(f"{BASE}/v1/chat/completions", verify=CA, headers=ADMIN, timeout=30,
               json={"model": "chat", "messages": [{"role": "user", "content": "x" * 3_000_000}]})
print(f"  3 MB body -> {r.status_code}")

print("== 4. logs are JSON, without prompts or keys")
app = httpx.post(f"{BASE}/key/generate", verify=CA, headers=ADMIN, json={"models": ["chat"]}).json()["key"]
chat(app, MARKER)
logs = compose("logs", "proxy")
print(f"  prompt text in logs: {MARKER in logs}   key in logs: {app in logs or app[:-4] in logs}")
print("  sample:", next(l for l in logs.splitlines() if "REDACTED" in l).split("| ", 1)[1][120:250])

print("== 5. containers")
print(f"  proxy uid: {sh('litellm-prod-proxy-1', 'id -u')}   "
      f"effective capabilities: {sh('litellm-prod-proxy-1', 'grep CapEff /proc/self/status').split()[1]}")
egress = sh("litellm-prod-upstream-1", "python -c \"import urllib.request as u; u.urlopen('https://pypi.org', timeout=5)\""
            " 2>&1 | tail -1")
print(f"  backend-only container reaching the internet: {egress[:70]}")

print("== 6. the database goes away")
compose("stop", "db")
time.sleep(2)
r = httpx.get(f"{BASE}/health/readiness", verify=CA)
print(f"  /health/readiness -> {r.status_code} {r.text}")
print(f"  a key no replica has cached -> {chat('sk-never-issued').status_code}")
compose("start", "db")

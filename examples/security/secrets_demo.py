"""Where the proxy's secrets come from, what happens when they rotate or vanish, and what the salt key protects."""
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

HERE = Path(__file__).parent
PROXY, VAULT, UPSTREAM = "http://localhost:4104", "http://127.0.0.1:4014", "http://127.0.0.1:4012"
MASTER = os.environ["LITELLM_MASTER_KEY"]
ADMIN = {"Authorization": f"Bearer {MASTER}"}
BASE_ENV = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"} | {
    "LITELLM_LOCAL_MODEL_COST_MAP": "True", "VAULT_ADDR": VAULT, "VAULT_TOKEN": "vault-demo-token",
    "LITELLM_SALT_KEY": "sk-salt-original-0001"}
LOG = HERE / "secrets_demo.proxy.log"


def start_proxy(**env: str) -> subprocess.Popen:
    """Start the proxy on port 4104 and wait until it answers."""
    proc = subprocess.Popen(["litellm", "--config", "secrets_config.yaml", "--port", "4104"], cwd=HERE,
                            env=BASE_ENV | env, stdout=LOG.open("w"), stderr=subprocess.STDOUT)
    for _ in range(120):
        try:
            if httpx.get(f"{PROXY}/health/liveliness").status_code == 200:
                return proc
        except httpx.TransportError:
            time.sleep(1)
    sys.exit(f"proxy did not start; see {LOG}")


def stop(proc: subprocess.Popen) -> None:
    proc.terminate()
    proc.wait(timeout=30)


def start_vault() -> subprocess.Popen:
    proc = subprocess.Popen([sys.executable, "fake_vault.py", "4014"], cwd=HERE)
    time.sleep(1)
    return proc


def key_upstream_saw(model: str = "chat") -> str:
    """Call the proxy and return the provider key that reached the upstream, or the error."""
    httpx.get(f"{UPSTREAM}/_reset")
    r = httpx.post(f"{PROXY}/v1/chat/completions", headers=ADMIN, timeout=30,
                   json={"model": model, "messages": [{"role": "user", "content": "hi"}]})
    if r.status_code != 200:
        return f"{r.status_code} {r.json()['error']['message'][:80]}"
    return httpx.get(f"{UPSTREAM}/_seen").json()[-1]["authorization"]


print("== 1. a publicly known master key is refused at boot")
weak = subprocess.run(["litellm", "--config", "secrets_config.yaml", "--port", "4105"], cwd=HERE,
                      env=BASE_ENV | {"LITELLM_MASTER_KEY": "sk-1234"}, capture_output=True, text=True, timeout=120)
print(f"  exit {weak.returncode}:", next(l for l in weak.stderr.splitlines() if l.startswith("LiteLLM proxy refused")))

print("== 2. the provider key comes from Vault; OPENAI_API_KEY is not in the environment")
vault = start_vault()
proxy = start_proxy()
print("  upstream received:", key_upstream_saw(), "  vault reads:", set(httpx.get(f"{VAULT}/_reads").json()))

print("== 3. rotate the key in Vault")
httpx.post(f"{VAULT}/v1/secret/data/openai-api-key", headers={"X-Vault-Token": "vault-demo-token"},
           json={"data": {"value": "sk-rotated-3333"}})
print("  before restart:", key_upstream_saw())
stop(proxy)
proxy = start_proxy()
print("  after restart: ", key_upstream_saw())
stop(proxy)

print("== 4. Vault unreachable at boot, a stale env value present")
stop(vault)
proxy = start_proxy(OPENAI_API_KEY="sk-stale-env-value")
print("  upstream received:", key_upstream_saw())
print("  log:", next(l for l in LOG.read_text().splitlines() if "Defaulting to os.environ" in l)[9:120])
stop(proxy)

print("== 5. credentials saved through the API are encrypted with LITELLM_SALT_KEY")
vault = start_vault()
proxy = start_proxy()
name = f"db-chat-{int(time.time())}"
httpx.post(f"{PROXY}/model/new", headers=ADMIN, timeout=30, json={"model_name": name, "litellm_params": {
    "model": "openai/gpt-4o-mini", "api_key": "sk-provider-secret-9999", "api_base": f"{UPSTREAM}/v1"}}
           ).raise_for_status()
row = subprocess.run(["docker", "exec", os.environ.get("DB_CONTAINER", "litellm-sec-db"), "psql", "-U", "postgres",
                      "-d", "salted", "-tAc", f"SELECT litellm_params->>'api_key' FROM \"LiteLLM_ProxyModelTable\" "
                      f"WHERE model_name='{name}'"], capture_output=True, text=True).stdout.strip()
print("  stored api_key:", row[:44] + "...")
time.sleep(2)
print("  call with the original salt:", key_upstream_saw(name))
stop(proxy)
proxy = start_proxy(LITELLM_SALT_KEY="sk-salt-CHANGED-0002")
time.sleep(3)
print("  call after the salt changed:", key_upstream_saw(name))
print("  log:", next(l for l in LOG.read_text().splitlines() if f"Error upserting deployment {name}" in l)[9:170])
stop(proxy)
stop(vault)

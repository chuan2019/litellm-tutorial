"""Least-privilege access on the proxy: roles, teams, key types, route limits, expiry, rotation, key storage."""
import hashlib
import os
import subprocess
import time

import httpx

BASE = os.environ.get("PROXY_URL", "http://localhost:4101")
ADMIN = {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}
RUN = str(int(time.time()))


def call(method: str, path: str, key: str, **body: object) -> httpx.Response:
    """Send one request with a Bearer key."""
    return httpx.request(method, f"{BASE}{path}", headers={"Authorization": f"Bearer {key}"},
                         json=body or None, timeout=30)


def show(label: str, r: httpx.Response) -> None:
    """Print status and a one-line reason."""
    detail = ""
    if r.status_code >= 400:
        err = r.json().get("error", r.json().get("detail", {}))
        detail = (err.get("message") if isinstance(err, dict) else str(err))[:95]
    print(f"  {label:44} {r.status_code} {detail}")


def chat(key: str, model: str = "chat-cheap", **extra: object) -> httpx.Response:
    return call("POST", "/v1/chat/completions", key, model=model,
                messages=[{"role": "user", "content": "hi"}], **extra)


def new_key(**body: object) -> str:
    r = httpx.post(f"{BASE}/key/generate", headers=ADMIN, json=body, timeout=30)
    r.raise_for_status()
    return r.json()["key"]


print("== 1. a team owns the model list; users and keys inherit it")
team = httpx.post(f"{BASE}/team/new", headers=ADMIN, timeout=30,
                  json={"team_alias": f"search-{RUN}", "models": ["chat-cheap"]}).json()["team_id"]
httpx.post(f"{BASE}/user/new", headers=ADMIN, timeout=30, json={
    "user_id": f"alice-{RUN}", "user_email": f"alice-{RUN}@example.com", "user_role": "internal_user",
    "teams": [team]}).raise_for_status()
alice = new_key(user_id=f"alice-{RUN}", team_id=team, key_alias=f"alice-app-{RUN}")
show("team model", chat(alice))
show("model outside the team", chat(alice, model="chat"))

print("== 2. roles decide what a user may manage")
show("internal_user: key for herself", call("POST", "/key/generate", alice, user_id=f"alice-{RUN}"))
show("internal_user: key for someone else", call("POST", "/key/generate", alice, user_id="mallory"))
show("internal_user: create a user", call("POST", "/user/new", alice, user_id=f"eve-{RUN}"))
httpx.post(f"{BASE}/user/new", headers=ADMIN, timeout=30, json={
    "user_id": f"auditor-{RUN}", "user_role": "proxy_admin_viewer"}).raise_for_status()
auditor = new_key(user_id=f"auditor-{RUN}")
show("proxy_admin_viewer: list keys", call("GET", "/key/list", auditor))
show("proxy_admin_viewer: create a key", call("POST", "/key/generate", auditor))

print("== 3. key types and route allowlists")
llm_only = new_key(key_type="llm_api", key_alias=f"llm-only-{RUN}")
show("llm_api key: chat", chat(llm_only))
show("llm_api key: /key/generate", call("POST", "/key/generate", llm_only))
chat_route = new_key(allowed_routes=["/v1/chat/completions"], key_alias=f"chat-route-{RUN}")
show("allowed_routes=[chat]: chat", chat(chat_route))
show("allowed_routes=[chat]: /v1/models", call("GET", "/v1/models", chat_route))

print("== 4. an Enterprise-only key field is accepted at creation and fails at call time")
r = httpx.post(f"{BASE}/key/generate", headers=ADMIN, timeout=30,
               json={"enforced_params": ["user"], "key_alias": f"needs-user-{RUN}"})
show("create key with enforced_params", r)
show("call with 'user' in the body", chat(r.json()["key"], user="customer-42"))

print("== 5. short-lived keys expire on their own")
temp = new_key(duration="3s", key_alias=f"temp-{RUN}")
show("before expiry", chat(temp))
time.sleep(4)
show("after expiry", chat(temp))

print("== 6. rotation without an Enterprise licence: issue, switch, delete")
show("/key/regenerate", httpx.post(f"{BASE}/key/regenerate", headers=ADMIN, json={"key": alice}, timeout=30))
alice2 = new_key(user_id=f"alice-{RUN}", team_id=team, key_alias=f"alice-app-{RUN}-v2")
httpx.post(f"{BASE}/key/delete", headers=ADMIN, json={"keys": [alice]}, timeout=30).raise_for_status()
show("old key after delete", chat(alice))
show("new key", chat(alice2))

print("== 7. what the database stores for a key")
digest = hashlib.sha256(alice2.encode()).hexdigest()
sql = (f"SELECT token, key_name FROM \"LiteLLM_VerificationToken\" WHERE key_alias='alice-app-{RUN}-v2'")
row = subprocess.run(["docker", "exec", os.environ.get("DB_CONTAINER", "litellm-sec-db"), "psql", "-U", "postgres",
                      "-d", "litellm", "-tAc", sql], capture_output=True, text=True).stdout.strip()
token, key_name = row.split("|")
print(f"  stored token == sha256(key): {token == digest}   key_name: {key_name}   plaintext stored: {alice2 in row}")

"""Spend a person's budget through their IdP token and their virtual key, then watch it reset."""
import os
import time

import httpx

PROXY = os.environ.get("PROXY_URL", "http://localhost:4103")
IDP = os.environ.get("OIDC_ISSUER", "http://127.0.0.1:4013")
ADMIN = {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}
RUN = int(time.time())
ALICE, BOB = f"alice-{RUN}", f"bob-{RUN}"


def login(sub: str, groups: list[str]) -> str:
    """Get a fresh ID token for a user from the IdP."""
    return httpx.post(f"{IDP}/token", json={"sub": sub, "groups": groups}).json()["id_token"]


def chat(credential: str) -> str:
    """Call the proxy once and summarise the result."""
    r = httpx.post(f"{PROXY}/v1/chat/completions", headers={"Authorization": f"Bearer {credential}"}, timeout=30,
                   json={"model": "chat-cheap", "messages": [{"role": "user", "content": "hi"}]})
    if r.status_code == 200:
        return f"200 {r.json()['choices'][0]['message']['content']}"
    err = r.json().get("error", {})
    return f"{r.status_code} {(err.get('message') if isinstance(err, dict) else str(err))[:80]}"


def user_info(user_id: str) -> dict:
    """Read a user's budget fields as an admin."""
    info = httpx.get(f"{PROXY}/user/info", params={"user_id": user_id}, headers=ADMIN).json()["user_info"]
    return {k: info[k] for k in ("max_budget", "spend", "budget_duration", "budget_reset_at")}


print("== 1. alice signs in for the first time: her user row is created from her group")
alice = login(ALICE, ["ml-eng"])
print("call 1:", chat(alice))
print(user_info(ALICE))

print("== 2. alice spends until her budget runs out")
for n in range(2, 6):
    print(f"call {n}:", chat(alice))

print("== 3. the cap follows the person, not the credential")
print("alice, fresh token:        ", chat(login(ALICE, ["ml-eng"])))
print("bob (support), unaffected: ", chat(login(BOB, ["support"])))

print("== 4. wait for the next reset")
start = time.monotonic()
while (result := chat(alice)).startswith("4"):
    time.sleep(5)
print(f"alice again after {time.monotonic() - start:.0f} s:", result)
print(user_info(ALICE))

print("== 5. an admin raises alice's cap; signing in again does not overwrite it")
httpx.post(f"{PROXY}/user/update", headers=ADMIN, json={"user_id": ALICE, "max_budget": 1.0}).raise_for_status()
print("alice, fresh token:", chat(login(ALICE, ["ml-eng"])))
print(user_info(ALICE))

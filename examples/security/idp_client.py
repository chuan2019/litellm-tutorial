"""Sign in at the identity provider, then call the proxy with the ID token instead of a LiteLLM key."""
import base64
import json
import os
import time

import httpx

PROXY = os.environ.get("PROXY_URL", "http://localhost:4102")
IDP = os.environ.get("OIDC_ISSUER", "http://127.0.0.1:4013")


def login(sub: str, groups: list[str], aud: str = "litellm-proxy", ttl: int = 300) -> str:
    """Get an ID token for a user from the IdP."""
    return httpx.post(f"{IDP}/token", json={"sub": sub, "groups": groups, "aud": aud, "ttl": ttl}).json()["id_token"]


def chat(token: str, model: str) -> str:
    """Call the proxy with a bearer token and summarise the result."""
    r = httpx.post(f"{PROXY}/v1/chat/completions", headers={"Authorization": f"Bearer {token}"}, timeout=30,
                   json={"model": model, "messages": [{"role": "user", "content": "hi"}]})
    if r.status_code == 200:
        return f"200 {r.json()['choices'][0]['message']['content']}"
    err = r.json().get("error", {})
    return f"{r.status_code} {(err.get('message') if isinstance(err, dict) else err)[:90]}"


def tamper(token: str) -> str:
    """Rewrite the groups claim without re-signing."""
    head, body, sig = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    claims["groups"] = ["llm-admins"]
    forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"{head}.{forged}.{sig}"


alice = login("alice", ["ml-eng"])
bob = login("bob", ["support"])
print(f"{'alice (ml-eng)  -> chat':38}", chat(alice, "chat"))
print(f"{'bob (support)   -> chat-cheap':38}", chat(bob, "chat-cheap"))
print(f"{'bob (support)   -> chat':38}", chat(bob, "chat"))
print(f"{'carol (no LLM group)':38}", chat(login("carol", ["finance"]), "chat-cheap"))
print(f"{'token for another app (aud)':38}", chat(login("alice", ["ml-eng"], aud="payroll-app"), "chat"))
short = login("alice", ["ml-eng"], ttl=1)
time.sleep(32)  # past exp plus the 30 s leeway
print(f"{'expired token':38}", chat(short, "chat"))
print(f"{'bob edits his groups claim':38}", chat(tamper(bob), "chat"))
print(f"{'a random string':38}", chat("not-a-jwt", "chat"))
print(f"{'master key still works':38}", chat(os.environ["LITELLM_MASTER_KEY"], "chat"))

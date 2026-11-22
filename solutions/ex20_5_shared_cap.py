"""One person, several virtual keys, one spend cap."""
import os
import time
from datetime import datetime, timedelta, timezone

import httpx

PROXY = os.environ.get("PROXY_URL", "http://localhost:4106")
ADMIN = {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}
RUN = int(time.time())


def post(path: str, body: dict) -> dict:
    r = httpx.post(f"{PROXY}{path}", headers=ADMIN, json=body, timeout=30)
    r.raise_for_status()
    return r.json()


def chat(key: str) -> tuple[int, str]:
    r = httpx.post(f"{PROXY}/v1/chat/completions", headers={"Authorization": f"Bearer {key}"}, timeout=30,
                   json={"model": "chat-cheap", "messages": [{"role": "user", "content": "hi"}]})
    return r.status_code, r.text


dana, eve = f"dana-{RUN}", f"eve-{RUN}"
post("/user/new", {"user_id": dana, "max_budget": 0.00003, "budget_duration": "1d", "auto_create_key": False})
post("/user/new", {"user_id": eve, "max_budget": 0.00003, "budget_duration": "1d", "auto_create_key": False})
info = httpx.get(f"{PROXY}/user/info", params={"user_id": dana}, headers=ADMIN).json()["user_info"]
reset_at = datetime.fromisoformat(info["budget_reset_at"].replace("Z", "+00:00"))
midnight = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
print("budget_reset_at:", reset_at)
assert reset_at == midnight

key_a = post("/key/generate", {"user_id": dana, "models": ["chat-cheap"]})["key"]
key_b = post("/key/generate", {"user_id": dana, "models": ["chat-cheap"]})["key"]
key_big = post("/key/generate", {"user_id": dana, "models": ["chat-cheap"], "max_budget": 10})["key"]
key_eve = post("/key/generate", {"user_id": eve, "models": ["chat-cheap"]})["key"]

codes = [chat(key_a)[0] for _ in range(5)]
print("key A:", codes)
assert codes[:3] == [200, 200, 200] and codes[3:] == [422, 422]
status, body = chat(key_b)
print("key B:", status, body[:120])
assert status == 422 and f"User={dana}" in body
status, body = chat(key_big)
print("key with its own $10 budget:", status)
assert status == 422
assert chat(key_eve)[0] == 200
post("/user/update", {"user_id": eve, "max_budget": 0})
print("eve suspended:", chat(key_eve)[0])
assert chat(key_eve)[0] == 422
post("/user/update", {"user_id": eve, "max_budget": 0.00003})
print("eve restored:", chat(key_eve)[0])
print("ok")

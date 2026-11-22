"""Does a person's cap still apply when they call with a team key?"""
import os
import sys
import time

import httpx

PROXY = os.environ.get("PROXY_URL", "http://localhost:4106")
ADMIN = {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}
RUN = time.time_ns()


def post(path: str, body: dict) -> dict:
    r = httpx.post(f"{PROXY}{path}", headers=ADMIN, json=body, timeout=30)
    r.raise_for_status()
    return r.json()


def codes(key: str, n: int = 6) -> list[int]:
    return [httpx.post(f"{PROXY}/v1/chat/completions", headers={"Authorization": f"Bearer {key}"}, timeout=30,
                       json={"model": "chat-cheap", "messages": [{"role": "user", "content": "hi"}]}).status_code
            for _ in range(n)]


user = f"lee-{RUN}"
post("/user/new", {"user_id": user, "max_budget": 0.00003, "auto_create_key": False})
team = post("/team/new", {"team_alias": f"search-{RUN}"})["team_id"]
post("/team/member_add", {"team_id": team, "member": {"role": "user", "user_id": user}})
team_key = post("/key/generate", {"user_id": user, "team_id": team})["key"]
result = codes(team_key)
print("team key:", result)
if "--capped" in sys.argv:
    assert result == [200, 200, 200, 422, 422, 422]
else:
    assert result == [200] * 6
print("ok")

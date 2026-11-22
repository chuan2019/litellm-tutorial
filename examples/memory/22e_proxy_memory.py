"""Memory on the proxy: Responses API sessions, and /v1/memory as the store behind your own read and write paths."""
import json
import os
import uuid

import httpx

PROXY, UPSTREAM = "http://localhost:4000", "http://127.0.0.1:4011"
ADMIN = {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}
MEMORY_ROUTES = ["/v1/memory", "/v1/memory/{key}"]


def last_upstream_body():
    seen = [r for r in httpx.get(f"{UPSTREAM}/_seen").json() if r["path"].startswith("/v1/messages")]
    return json.loads(seen[-1]["body"])


def key_for(http, user_id):
    """A key for an internal user that may also use the memory routes."""
    http.post("/user/new", json={"user_id": user_id, "user_role": "internal_user"})
    key = http.post("/key/generate", json={"user_id": user_id, "allowed_routes": MEMORY_ROUTES + ["/v1/chat/completions"]})
    return {"Authorization": f"Bearer {key.json()['key']}"}


with httpx.Client(base_url=PROXY, headers=ADMIN, timeout=60) as http:
    print("== 1. Responses API: the proxy keeps the conversation")
    first = http.post("/v1/responses", json={"model": "chat", "instructions": "Answer in one line.",
                                             "input": "My name is Ana and I deploy on Fridays."}).json()
    http.post("/v1/responses", json={"model": "chat", "input": "When do I deploy?", "previous_response_id": first["id"]})
    sent = last_upstream_body()
    print("id length   :", len(first["id"]))
    print("model got   :", [(m["role"], m["content"][0]["text"][:30]) for m in sent["messages"]])
    print("instructions:", sent["system"][0]["text"])

    print("== 2. /v1/memory as a key-value store, written by your app")
    suffix = uuid.uuid4().hex[:6]
    ana, bob = key_for(http, f"ana-{suffix}"), key_for(http, f"bob-{suffix}")
    for name, value in (("profile", "Deploys the payments service on Fridays."),
                        ("style", "Prefers one-line answers with the command to run.")):
        r = httpx.post(f"{PROXY}/v1/memory", headers=ana,
                       json={"key": f"user:ana-{suffix}:{name}", "value": value, "metadata": {"kind": "semantic"}})
        print("write:", r.status_code, r.json()["key"], "| owner", r.json()["user_id"])

    print("== 3. read path: fetch by prefix, inject, call the model")
    rows = httpx.get(f"{PROXY}/v1/memory", headers=ana, params={"key_prefix": f"user:ana-{suffix}:"}).json()["memories"]
    notes = "\n".join(f"- {row['value']}" for row in rows)
    httpx.post(f"{PROXY}/v1/chat/completions", headers=ana, json={"model": "chat", "messages": [
        {"role": "system", "content": f"You help with deployments.\n<memories>\n{notes}\n</memories>"},
        {"role": "user", "content": "Plan my next deploy."}]})
    print(last_upstream_body()["system"][0]["text"])

    print("== 4. scoping")
    print("bob lists   :", httpx.get(f"{PROXY}/v1/memory", headers=bob).json()["memories"])
    print("bob gets    :", httpx.get(f"{PROXY}/v1/memory/user:ana-{suffix}:profile", headers=bob).status_code)
    r = httpx.post(f"{PROXY}/v1/memory", headers=bob, json={"key": f"user:ana-{suffix}:profile", "value": "x"})
    print("bob reuses Ana's key name:", r.status_code, r.json()["detail"])
    no_routes = http.post("/key/generate", json={"user_id": f"bob-{suffix}"}).json()["key"]
    r = httpx.get(f"{PROXY}/v1/memory", headers={"Authorization": f"Bearer {no_routes}"})
    print("key without allowed_routes:", r.status_code)

    for row in rows:
        httpx.delete(f"{PROXY}/v1/memory/{row['key']}", headers=ana).raise_for_status()
    print("cleaned up", len(rows), "entries")

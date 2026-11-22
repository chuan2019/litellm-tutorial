"""Put A2A agents behind the LiteLLM proxy: discovery, calls, headers, runtime registration, access and spend."""
import os
import time
import uuid

import httpx

PROXY = "http://localhost:4000"
AGENTS = "http://127.0.0.1:4016"
UPSTREAM = "http://127.0.0.1:4011"
ADMIN = {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}


def rpc(text, method="message/send"):
    """Return an A2A JSON-RPC request carrying one user text part."""
    return {"jsonrpc": "2.0", "id": uuid.uuid4().hex[:6], "method": method,
            "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": text}],
                                   "messageId": uuid.uuid4().hex}}}


def reply_text(response):
    return " ".join(p["text"] for p in response.json()["result"]["parts"])


def last_agent_request():
    return httpx.get(f"{AGENTS}/_seen").json()[-1]


with httpx.Client(base_url=PROXY, headers=ADMIN, timeout=30) as http:
    print("== 1. agents registered in the config")
    ids = {a["agent_name"]: a["agent_id"] for a in http.get("/v1/agents").json()}
    for name, agent_id in ids.items():
        print(f"{name:8} {agent_id[:16]}...")

    print("== 2. the agent card, as the proxy serves it")
    card = http.get("/a2a/triage/.well-known/agent-card.json").json()
    print("url   :", card["url"])
    print("no key:", httpx.get(f"{PROXY}/a2a/triage/.well-known/agent-card.json").status_code)

    print("== 3. message/send through the proxy, with headers for the agent")
    r = http.post("/a2a/triage", json=rpc("I was charged twice"),
                  headers={"x-ticket-id": "T-42", "x-a2a-triage-x-priority": "high", "x-other": "dropped"})
    print("reply :", r.status_code, reply_text(r))
    seen = last_agent_request()
    print("agent got:", {k: v for k, v in sorted(seen["headers"].items()) if k.startswith("x-") and k != "x-litellm-trace-id"})
    print("client key forwarded:", "authorization" in seen["headers"])

    print("== 4. message/stream through the proxy")
    with http.stream("POST", "/a2a/triage", json=rpc("The app crashes on login", "message/stream")) as r:
        kinds = [line for line in r.iter_lines() if line.startswith("data:")]
    print(r.headers["content-type"].split(";")[0], len(kinds), "events")

    print("== 5. register an agent at runtime that is really an LLM (the completion bridge)")
    writer = http.post("/v1/agents", json={
        "agent_name": "writer",
        "agent_card_params": {"protocolVersion": "0.3.0", "name": "writer", "description": "Drafts replies.",
                              "url": f"{UPSTREAM}/v1", "version": "1.0.0", "capabilities": {"streaming": False},
                              "defaultInputModes": ["text"], "defaultOutputModes": ["text"], "skills": []},
        "litellm_params": {"custom_llm_provider": "openai", "model": "gpt-4o-mini", "api_key": "fake"},
    }).json()
    print("id    :", writer["agent_id"], "| api_key shown as", writer["litellm_params"]["api_key"])
    r = http.post("/a2a/writer", json=rpc("Draft a reply to ticket T-42"))
    upstream = httpx.get(f"{UPSTREAM}/_seen").json()[-1]
    print("reply :", reply_text(r), "| upstream got", upstream["method"], upstream["path"])

    print("== 6. a key that may call only the triage agent")
    key = http.post("/key/generate", json={"object_permission": {"agents": [ids["triage"]]}}).json()["key"]
    as_key = {"Authorization": f"Bearer {key}"}
    print("lists :", [a["agent_name"] for a in http.get("/v1/agents", headers=as_key).json()])
    print("triage:", http.post("/a2a/triage", json=rpc("refund please"), headers=as_key).status_code)
    r = http.post("/a2a/billing", json=rpc("refund $20"), headers=as_key)
    print("billing:", r.status_code, r.json()["error"]["message"])

    print("== 7. the key's spend comes from cost_per_query")
    for _ in range(30):
        spend = http.get("/key/info", params={"key": key}).json()["info"]["spend"]
        if spend:
            break
        time.sleep(1)
    print("spend :", spend)

    print("== 8. billing has rpm_limit: 2")
    print("codes :", [http.post("/a2a/billing", json=rpc("refund $5")).status_code for _ in range(3)])

    print("== 9. delete the runtime agent")
    print(http.delete(f"/v1/agents/{writer['agent_id']}").json())

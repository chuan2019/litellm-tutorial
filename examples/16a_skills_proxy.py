"""Host skills on the LiteLLM proxy, attach them to requests, search them and publish them."""
import io
import json
import os
import time
import zipfile

import httpx

PROXY = "http://localhost:4000"
UPSTREAM = "http://127.0.0.1:4011"
ADMIN = {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}
HOSTED = {"custom_llm_provider": "litellm_proxy"}
SKILLS = {
    "release-notes": ("Turn a list of merged pull requests into user-facing release notes.",
                      "Group changes under Added, Changed and Fixed. One line per change, past tense."),
    "sql-review": ("Review a SQL migration for locking and rollback problems.",
                   "Flag ALTER TABLE on large tables, missing indexes and irreversible steps."),
}


def skill_zip(name, description, body):
    """Return a zip holding <name>/SKILL.md, the layout the Anthropic Skills API uses."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{name}/SKILL.md", f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n")
    return buf.getvalue()


def last_upstream_body(path):
    """Return the JSON body of the newest request the fake upstream got on path."""
    seen = httpx.get(f"{UPSTREAM}/_seen").json()
    return json.loads(next(r for r in reversed(seen) if r["path"].startswith(path))["body"])


with httpx.Client(base_url=PROXY, headers=ADMIN, timeout=30) as http:
    print("== 1. upload two skills to the proxy's database")
    ids = {}
    for name, (description, body) in SKILLS.items():
        r = http.post("/v1/skills", params=HOSTED, data={"display_title": name, "description": description},
                      files={"files[]": (f"{name}.zip", skill_zip(name, description, body), "application/zip")})
        ids[name] = r.json()["id"]
        print(f"{name:14} -> {ids[name]}")

    print("== 2. list them")
    listed = http.get("/v1/skills", params=HOSTED).json()["data"]
    print([s["display_title"] for s in listed])

    print("== 3. chat completion with container.skills, model behind it is OpenAI-style")
    skills = [{"type": "custom", "skill_id": ids["release-notes"]}]
    http.post("/v1/chat/completions", json={
        "model": "gpt", "messages": [{"role": "user", "content": "Notes for PR #12"}],
        "container": {"skills": skills}})
    sent = last_upstream_body("/v1/chat/completions")
    print("system :", sent["messages"][0]["content"][:70].replace("\n", " | "))
    print("tools  :", [t["name"] for t in sent["tools"]])
    print("tool keys:", sorted(sent["tools"][0]))
    print("container forwarded:", "container" in sent)

    print("== 4. /v1/messages with the same skill, model behind it is Anthropic")
    r = http.post("/v1/messages", json={
        "model": "claude", "max_tokens": 200, "messages": [{"role": "user", "content": "Notes for PR #12"}],
        "container": {"skills": skills}})
    sent = last_upstream_body("/v1/messages")
    print("reply  :", r.json()["content"][0]["text"])
    print("system :", sent["system"][:70].replace("\n", " | "))
    print("tools  :", [t["name"] for t in sent["tools"]])
    print("container forwarded:", "container" in sent)

    print("== 5. semantic search over the hosted skills")
    found = http.get("/v1/skills", params={**HOSTED, "query": "review my SQL migration", "top_k": 2}).json()
    for s in found["data"]:
        print(f"{s['display_title']:14} score={s['search_score']:.3f}")

    print("== 6. public Agent Skills discovery index (no credentials)")
    index = httpx.get(f"{PROXY}/.well-known/agent-skills/index.json").json()
    entry = index["skills"][0]
    print(index["$schema"])
    print({k: entry[k] for k in ("name", "type", "url")}, entry["digest"][:20] + "...")
    archive = httpx.get(entry["url"])
    print("archive files:", zipfile.ZipFile(io.BytesIO(archive.content)).namelist())

    print("== 7. a key for another user cannot see these skills")
    key = http.post("/key/generate", json={"user_id": f"alice-{int(time.time())}"}).json()["key"]
    other = {"Authorization": f"Bearer {key}"}
    print("alice lists:", http.get("/v1/skills", params=HOSTED, headers=other).json()["data"])
    r = http.get(f"/v1/skills/{ids['sql-review']}", params=HOSTED, headers=other)
    print("alice gets :", r.status_code, r.json()["error"]["message"])

    print("== 8. delete them")
    for skill_id in ids.values():
        print(http.delete(f"/v1/skills/{skill_id}", params=HOSTED).json())

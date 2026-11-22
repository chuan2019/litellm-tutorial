"""Anthropic Skills through the LiteLLM SDK, against a local fake of Anthropic's API."""
import io
import json
import threading
import zipfile
from http.server import ThreadingHTTPServer

import httpx
import litellm

from _fake_upstream import Handler



def skill_zip(name, description, body):
    """Return a zip holding <name>/SKILL.md, the layout the Anthropic Skills API uses."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{name}/SKILL.md", f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n")
    return buf.getvalue()


def show_last_request():
    """Print the method, path and Anthropic headers of the newest upstream request."""
    req = httpx.get(f"{FAKE}/_seen").json()[-1]
    print(f"   -> {req['method']} {req['path']}  anthropic-beta={req['headers'].get('anthropic-beta')}")
    return req


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
FAKE = f"http://127.0.0.1:{server.server_port}"
AUTH = {"api_key": "sk-ant-fake", "api_base": FAKE}

data = skill_zip("release-notes", "Turn merged PRs into release notes.", "Group under Added, Changed, Fixed.")
skill = litellm.create_skill(display_title="Release notes",
                             files=[("release-notes.zip", data, "application/zip")], **AUTH)
print("create:", skill.id, skill.display_title)
body = show_last_request()["body"]
print("   form fields:", [line.split("; ")[1] for line in body.splitlines() if line.startswith("Content-Disposition")])

page = litellm.list_skills(limit=10, source="custom", **AUTH)
print("list  :", [s.id for s in page.data])
show_last_request()

print("get   :", litellm.get_skill(skill_id=skill.id, **AUTH).display_title)
show_last_request()

resp = litellm.completion(
    model="anthropic/claude-sonnet-5-5",
    messages=[{"role": "user", "content": "Release notes for PR #12"}],
    container={"skills": [{"type": "custom", "skill_id": skill.id, "version": "latest"}]},
    tools=[{"type": "code_execution_20250825", "name": "code_execution"}],
    **AUTH,
)
print("chat  :", resp.choices[0].message.content)
sent = json.loads(show_last_request()["body"])
print("   container:", sent["container"])

print("delete:", litellm.delete_skill(skill_id=skill.id, **AUTH).type)
show_last_request()

try:
    litellm.list_skills(custom_llm_provider="openai")
except Exception as e:
    print("openai:", type(e).__name__, str(e).split(" - ")[-1])
server.shutdown()

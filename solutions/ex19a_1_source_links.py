"""Exercise 19a.1: link runs to the conversation that started them, and find the failed one."""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples" / "lens"))
import fake_support_llm  # noqa: E402
import support_agent  # noqa: E402
from _lens import FAKE_LLM, admin, setup_tracing  # noqa: E402

JIRA = {"agent.source.type": "jira", "agent.source.url": "https://example.atlassian.net/browse/SUP-12",
        "agent.source.title": "Customer asks about order 1003"}
PLAIN_HTTP = {"agent.source.type": "custom", "agent.source.url": "http://intranet/tickets/7"}

lens = admin()
key = lens.post("/lens/tracing/keys", json={"name": "ex19a.1"}).json()["key"]
provider = setup_tracing("ticket-bot", key)
fake_support_llm.start()
llm = {"api_base": FAKE_LLM, "api_key": "unused"}


async def main() -> list[str]:
    runs = [await support_agent.run("Can you check order 1003?", "openai/gpt-4o-mini", JIRA, **llm),
            await support_agent.run("Where is order 1001?", "openai/gpt-4o-mini", PLAIN_HTTP, **llm),
            await support_agent.run("Where is order 9999?", "openai/gpt-4o-mini", **llm)]
    await asyncio.sleep(1)
    return [trace_id for _, trace_id in runs]


ids = asyncio.run(main())
provider.force_flush()
for _ in range(20):
    found = {r["trace_id"]: r for r in lens.get("/v1/traces").json()["data"] if r["trace_id"] in ids}
    if len(found) == 3:
        break
    time.sleep(1)
jira, plain, failed = (found[i] for i in ids)
for run in (jira, plain, failed):
    print(run["trace_id"][:8], run["input_preview"], "source:", run.get("source"), "errors:", run["error_count"])

assert jira["source"] == {"type": "jira", "url": JIRA["agent.source.url"], "title": JIRA["agent.source.title"]}
assert "source" not in plain, "an http:// source URL should be dropped"
assert failed["error_count"] == 1 and "source" not in failed
spans = lens.get(f"/v1/traces/{failed['trace_id']}", params={"trace_ref": failed["trace_ref"]}).json()["spans"]
assert [s["status"] for s in spans if s["type"] == "tool"] == ["error"]
print("all checks passed")

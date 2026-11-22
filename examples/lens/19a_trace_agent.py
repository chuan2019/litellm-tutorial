"""Run the support agent against a fake model and send its traces to a standalone Lens."""
import asyncio

import httpx

import fake_support_llm
import support_agent
from _lens import FAKE_LLM, LENS_URL, admin, delivered, setup_tracing

QUESTIONS = ["Can you check order 1003 for me?", "Where is order 1002?",
             "Quick one: has order 1004 shipped?", "What's the status of order 9999?"]

created = admin().post("/lens/tracing/keys", json={"name": "support-agent 19a"}).json()
tracing_key = created["key"]
print(f"tracing key {created['record']['name']!r} owned by {created['record']['tenant']['user_id']}")
provider = setup_tracing("support-agent", tracing_key)
fake_support_llm.start()

trace_ids = asyncio.run(support_agent.run_all(QUESTIONS, "openai/gpt-4o-mini",
                                              api_base=FAKE_LLM, api_key="unused"))
provider.force_flush()

print("delivered:", delivered(tracing_key, trace_ids))
read = httpx.get(f"{LENS_URL}/v1/traces", headers={"Authorization": f"Bearer {tracing_key}"})
print("read traces with the tracing key:", read.status_code)

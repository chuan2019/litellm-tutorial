"""Send the support agent's runs through the proxy, ask Lens to investigate them, and print the findings."""
import asyncio
import os
import time

import fake_support_llm
import support_agent
from _lens import PROXY_URL, delivered, gateway, setup_gateway_agent, setup_tracing

QUESTIONS = ["Can you check order 1001 for me?", "Where is order 1003?",
             "Quick one: has order 1002 shipped?", "What's the status of order 1002?",
             "Quick question, did order 1001 arrive?", "Is order 4242 on its way?"]
EXPECTED = ("support_agent answers customers' questions about their orders. Before it states an order's "
            "status it must call lookup_order and report exactly the status the tool returned. If the "
            "order does not exist it must say so.")
TERMINAL = {"completed", "partial", "failed", "cancelled"}

master = gateway(os.environ["LITELLM_MASTER_KEY"])
agent_key, tracing_key = setup_gateway_agent(master)
provider = setup_tracing("support-agent", tracing_key)
fake_support_llm.start()
trace_ids = asyncio.run(support_agent.run_all(QUESTIONS, "litellm_proxy/support",
                                              api_base=PROXY_URL, api_key=agent_key))
provider.force_flush()
arrived = delivered(tracing_key, trace_ids)
print(f"{sum(arrived)} of {len(trace_ids)} runs reached Lens")
if not all(arrived):
    raise SystemExit("Lens rejected a span batch; run the script again")
print("waiting for the runs to settle")
time.sleep(150)  # Lens skips traces received in the last two minutes, so a run can finish first

investigation = master.post("/lens", json={
    "name": "Support agent order lookups", "model": "analysis", "agent_name": "support_agent",
    "context": EXPECTED, "lookback_hours": 1, "enabled": False, "monthly_budget": 1}).json()
print("\ninvestigation", investigation["id"], "queued")

started = time.monotonic()
while True:
    state = master.get(f"/lens/{investigation['id']}").json()
    job = state["jobs"][0] if state["jobs"] else {}
    if job.get("status") in TERMINAL or time.monotonic() - started > 900:
        break
    time.sleep(15)

cover = job.get("coverage") or {}
print(f"run {job.get('status')} after {time.monotonic() - started:.0f}s: screened {cover.get('screened')} runs, "
      f"investigated {cover.get('investigated')}, failed tasks {cover.get('failed_tasks')}, cost ${job.get('cost'):.4f}")
if job.get("error"):
    print("run error:", job["error"][:150])
for finding in state["findings"]:
    print(f"\n[{finding['priority']}] {finding['title']}  ({finding['kind']}, {finding['status']})")
    print("  ", finding["description"])
    print("   suggestion:", finding["suggestion"])
    for evidence in finding["evidence"][:3]:
        print(f"   evidence span {evidence['span_id']}: {evidence['quote']!r}")

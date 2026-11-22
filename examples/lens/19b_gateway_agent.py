"""Trace the support agent through the proxy and read each model call's recorded cost back from Lens."""
import asyncio
import os
import time

import fake_support_llm
import support_agent
from _lens import PROXY_URL, gateway, setup_gateway_agent, setup_tracing

QUESTIONS = ["Can you check order 1001 for me?", "Quick one: is order 1002 delivered?"]

master = gateway(os.environ["LITELLM_MASTER_KEY"])
service = master.get("/lens/service").json()
print("lens connection:", "connected" if service["connected"] else "NOT connected", service["status"])

agent_key, tracing_key = setup_gateway_agent(master)
provider = setup_tracing("support-agent", tracing_key)
fake_support_llm.start()
trace_ids = asyncio.run(support_agent.run_all(QUESTIONS, "litellm_proxy/support",
                                              api_base=PROXY_URL, api_key=agent_key))
provider.force_flush()
time.sleep(5)  # the proxy exports request records to Lens in the background

owner = gateway(agent_key)
for run in owner.get("/v1/traces").json()["data"]:
    if run["trace_id"] not in trace_ids:
        continue
    print(f"\nrun {run['trace_id'][:8]}: spend={run['spend']} priced_calls={run['priced_calls']}/{run['llm_calls']}")
    detail = owner.get(f"/v1/traces/{run['trace_id']}", params={"trace_ref": run["trace_ref"]}).json()
    for span in sorted(detail["spans"], key=lambda s: s["start_offset_ms"]):
        print(f"  {span['type']:6} {span['name']:28} spend={span['spend']}  match={span['spend_match']}")

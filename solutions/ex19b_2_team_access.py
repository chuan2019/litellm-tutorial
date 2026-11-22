"""Exercise 19b.2: who can read the support team's runs, and who can run Lens."""
import asyncio
import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples" / "lens"))
import fake_support_llm  # noqa: E402
import support_agent  # noqa: E402
from _lens import PROXY_URL, gateway, setup_gateway_agent, setup_tracing  # noqa: E402

master = gateway(os.environ["LITELLM_MASTER_KEY"])
agent_key, tracing_key = setup_gateway_agent(master)
provider = setup_tracing("support-agent", tracing_key)
fake_support_llm.start()
[trace_id] = asyncio.run(support_agent.run_all(["Where is order 1003?"], "litellm_proxy/support",
                                               api_base=PROXY_URL, api_key=agent_key))
provider.force_flush()
time.sleep(3)

if master.get("/user/info", params={"user_id": "teammate"}).status_code != 200:
    master.post("/user/new", json={"user_id": "teammate", "user_role": "internal_user"}).raise_for_status()
master.post("/team/member_add", json={"team_id": "support", "member": {"role": "user", "user_id": "teammate"}})
teammate = gateway(master.post("/key/generate", json={"user_id": "teammate", "team_id": "support"}).json()["key"])
service_account = gateway(master.post("/key/generate", json={"team_id": "support"}).json()["key"])


def sees_run(client: httpx.Client) -> bool:
    """Whether this key's trace list includes the run just made."""
    return any(r["trace_id"] == trace_id for r in client.get("/v1/traces").json()["data"])


def share(permissions: list[str]) -> None:
    """Set the support team's member permissions."""
    master.post("/team/permissions_update", json={"team_id": "support",
                                                  "team_member_permissions": permissions}).raise_for_status()


share([])
before = sees_run(teammate)
share(["/spend/logs"])
after = sees_run(teammate)
print("teammate sees the team's run:", {"without /spend/logs": before, "with /spend/logs": after})
print("owner sees it:", sees_run(gateway(agent_key)))
lens_list = teammate.get("/lens").status_code
new_key = teammate.post("/lens/tracing/keys", json={"name": "nope"}).status_code
sa_read = service_account.get("/v1/traces").status_code
print("teammate GET /lens:", lens_list, " teammate POST /lens/tracing/keys:", new_key,
      " team service-account key GET /v1/traces:", sa_read)
share([])

assert not before and after
assert lens_list == 403 and new_key == 403 and sa_read == 403
print("all checks passed")

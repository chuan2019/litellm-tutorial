"""Exercise 19c.1: investigate with named checks, then verify every quote Lens cites."""
import base64
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples" / "lens"))
from _lens import gateway  # noqa: E402

CHECKS = [
    {"id": "lookup_before_status", "instruction": "Flag any answer that states an order's status "
     "without a lookup_order call earlier in the same run, or that differs from what the tool returned."},
    {"id": "missing_order", "instruction": "Flag any run where lookup_order reported the order was not "
     "found but the agent still gave a status."},
]
TERMINAL = {"completed", "partial", "failed", "cancelled"}

master = gateway(os.environ["LITELLM_MASTER_KEY"])
created = master.post("/lens", json={"name": "Support agent checks", "model": "analysis",
                                     "agent_name": "support_agent", "checks": CHECKS,
                                     "lookback_hours": 1, "enabled": False, "monthly_budget": 1}).json()
for _ in range(60):
    state = master.get(f"/lens/{created['id']}").json()
    job = state["jobs"][0] if state["jobs"] else {}
    if job.get("status") in TERMINAL:
        break
    time.sleep(15)
print(f"run {job['status']}, cost ${job['cost']:.4f}, failed tasks {job['coverage']['failed_tasks']},"
      f" error: {job.get('error')}")
assert job["status"] in ("completed", "partial")


def span_text(trace_id: str, trace_ref: str, span_id: str) -> str:
    """Return a span the way Lens shows it to the investigator: Input, Output and Status lines."""
    step = master.get(f"/v1/traces/{trace_id}/spans/{span_id}", params={"trace_ref": trace_ref}).json()
    # The query endpoint takes no parameters, so check the IDs before putting them in SQL.
    assert re.fullmatch(r"[0-9a-f]{32}", trace_id) and re.fullmatch(r"[0-9a-f]{16}", span_id)
    sql = ("SELECT StatusCode, StatusMessage FROM otel_traces WHERE Timestamp >= now() - INTERVAL 1 DAY "
           f"AND TraceId = '{trace_id}' AND SpanId = '{span_id}' LIMIT 1")
    [status] = master.post("/v1/traces/query", json={"sql": sql}).json()["data"]
    text = [v if isinstance(v, str) else json.dumps(v) for v in (step["input"], step["output"])]
    return f"Input: {text[0]}\nOutput: {text[1]}\nStatus: {status['StatusCode']} {status['StatusMessage']}"


ids = {c["id"] for c in CHECKS}
checked = 0
for finding in state["findings"]:
    print(f"\n[{finding['priority']}] {finding['check_id']}: {finding['title']} ({finding['kind']})")
    assert finding["check_id"] in ids
    for ev in finding["evidence"]:
        _, _, trace_id, trace_ref = json.loads(base64.b64decode(ev["execution_id"]))
        text = span_text(trace_id, trace_ref, ev["span_id"])
        # A quote can span several of the Input/Output/Status lines; each part must be in the span.
        parts = [re.sub(r"^(Input|Output|Status): ?", "", line) for line in ev["quote"].split("\n")]
        found = all(part in text for part in parts if part)
        print(f"   {trace_id[:8]}/{ev['span_id']} {'verified' if found else 'NOT FOUND'}: {ev['quote'][:60]!r}")
        assert found
        checked += 1
assert any(f["check_id"] == "lookup_before_status" and f["kind"] == "issue" for f in state["findings"])
print(f"\n{checked} quotes verified against the stored spans")

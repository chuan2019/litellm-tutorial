"""Read the support agent's runs back from Lens: run list, one run's steps, one step, agents and SQL."""
from _lens import admin

lens = admin()
runs = lens.get("/v1/traces").json()["data"]
print(f"{'trace':9}{'agent':15}{'llm':>4}{'tools':>6}{'errors':>7}  input")
for run in runs:
    print(f"{run['trace_id'][:8]} {','.join(run['agent_names']):15}{run['llm_calls']:>4}"
          f"{run['tool_calls']:>6}{run['error_count']:>7}  {run['input_preview'][:44]}")

failed = next(r for r in runs if r["error_count"])
detail = lens.get(f"/v1/traces/{failed['trace_id']}", params={"trace_ref": failed["trace_ref"]}).json()
print(f"\nrun {failed['trace_id'][:8]}: {len(detail['spans'])} spans")
children = {}
for span in detail["spans"]:
    children.setdefault(span["parent_span_id"], []).append(span)


def show(parent: str | None, depth: int = 0) -> None:
    """Print the spans under a parent as an indented tree, in start order."""
    for span in sorted(children.get(parent, []), key=lambda s: s["start_offset_ms"]):
        print(f"{'  ' * depth}{span['type']:6} {span['name']:<{30 - 2 * depth}} {span['status']:6}"
              f" {span['model'] or '':12} {span['input_tokens']:>4}/{span['output_tokens']:<4}")
        show(span["span_id"], depth + 1)


show(None)
tool = next(s for s in detail["spans"] if s["type"] == "tool")
step = lens.get(f"/v1/traces/{failed['trace_id']}/spans/{tool['span_id']}",
                params={"trace_ref": failed["trace_ref"]}).json()
print("\ntool step input: ", step["input"], "\ntool step output:", step["output"])

print("\nagents:", lens.get("/v1/traces/agents").json()["agents"])

sql = """
SELECT TraceId, countIf(ObservationType = 'llm') AS llm_calls, countIf(ObservationType = 'tool') AS tool_calls
FROM otel_traces
WHERE Timestamp >= now() - INTERVAL 1 DAY AND ServiceName = 'support-agent'
GROUP BY TraceId HAVING tool_calls = 0
LIMIT 20"""
print("\nruns that answered without calling a tool:")
for row in lens.post("/v1/traces/query", json={"sql": sql}).json()["data"]:
    print(" ", row)

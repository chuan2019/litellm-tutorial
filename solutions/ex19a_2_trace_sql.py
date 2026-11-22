"""Exercise 19a.2: rebuild Lens's run summaries with SQL, then measure each kind of step."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples" / "lens"))
from _lens import admin  # noqa: E402

PER_RUN = """
SELECT TraceId,
       countIf(ObservationType = 'llm') AS llm_calls,
       countIf(ObservationType = 'tool') AS tool_calls,
       countIf(StatusCode = 'STATUS_CODE_ERROR') AS errors,
       sum(InputTokens) AS input_tokens,
       sum(OutputTokens) AS output_tokens
FROM otel_traces
WHERE Timestamp >= now() - INTERVAL 1 DAY AND ServiceName = 'support-agent'
GROUP BY TraceId
LIMIT 1000"""
PER_TYPE = """
SELECT ObservationType AS type, count() AS spans,
       round(avg(Duration) / 1e6, 2) AS avg_ms, round(quantile(0.95)(Duration) / 1e6, 2) AS p95_ms
FROM otel_traces
WHERE Timestamp >= now() - INTERVAL 1 DAY AND ServiceName = 'support-agent'
GROUP BY type ORDER BY spans DESC
LIMIT 10"""
FIELDS = ("llm_calls", "tool_calls", "input_tokens", "output_tokens")

lens = admin()
rows = {r["TraceId"]: r for r in lens.post("/v1/traces/query", json={"sql": PER_RUN}).json()["data"]}
summaries, cursor = [], None
while True:
    page = lens.get("/v1/traces", params={"cursor": cursor} if cursor else {}).json()
    summaries += [s for s in page["data"] if s["service"] == "support-agent"]
    cursor = page["next_cursor"]
    if not cursor:
        break

for s in summaries:
    row = rows[s["trace_id"]]
    assert all(int(row[f]) == s[f] for f in FIELDS), (s["trace_id"], row, {f: s[f] for f in FIELDS})
    assert int(row["errors"]) == s["error_count"]
print(f"{len(summaries)} runs: SQL totals match the API summaries")

no_tool = {t for t, r in rows.items() if int(r["tool_calls"]) == 0}
quick = {s["trace_id"] for s in summaries if "quick" in s["input_preview"].lower()}
assert no_tool & {s["trace_id"] for s in summaries} == quick, "only the hurried questions skip the lookup"
print(f"{len(no_tool)} runs answered without a lookup:",
      sorted(s["input_preview"] for s in summaries if s["trace_id"] in no_tool))
for row in lens.post("/v1/traces/query", json={"sql": PER_TYPE}).json()["data"]:
    print(f"  {row['type']:6} spans={row['spans']:<4} avg={row['avg_ms']}ms p95={row['p95_ms']}ms")

drop = lens.post("/v1/traces/query", json={"sql": "DROP TABLE otel_traces"})
print("DROP TABLE:", drop.status_code, drop.json()["detail"])
assert drop.status_code == 503
assert lens.post("/v1/traces/query", json={"sql": PER_RUN}).json()["data"], "the table should still be there"

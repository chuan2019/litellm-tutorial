"""Exercise 19b.1: a preflight check for a proxy connected to Lens."""
import os
import sys
import uuid
from pathlib import Path

import httpx
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples" / "lens"))
from _lens import LENS_URL, gateway  # noqa: E402

results = []


def check(name: str, ok: bool, detail: object = "") -> None:
    """Record and print one check."""
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name:44} {detail}")


try:
    ready = httpx.get(f"{LENS_URL}/health/ready").status_code
except httpx.ConnectError as error:
    ready = repr(error)
check("Lens is ready", ready == 200, ready)

master = gateway(os.environ["LITELLM_MASTER_KEY"])
service = master.get("/lens/service").json()
status = service["status"]
check("proxy has LITELLM_LENS_URL", service["configured"])
check("Lens storage ready", status["storage_ready"])
check("service token and gateway secret accepted", status["credentials_ready"])
check("public contract is 1", status["public_contract"] == 1, status["public_contract"])
check("connected", service["connected"], f"release {service['release']}, exporters use {service['url']}")

name = f"preflight-{uuid.uuid4().hex[:6]}"
created = master.post("/lens/tracing/keys", json={"name": name})
check("an admin can create a tracing key", created.status_code == 200, created.status_code)
key = created.json()["key"]
provider = TracerProvider(resource=Resource.create({"service.name": "preflight"}))
provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(
    endpoint=f"{service['url']}/v1/traces", headers={"Authorization": f"Bearer {key}"})))
with provider.get_tracer("preflight").start_as_current_span("preflight") as span:
    trace_id = format(span.get_span_context().trace_id, "032x")
    span_id = format(span.get_span_context().span_id, "016x")
provider.shutdown()
receipt = httpx.post(f"{service['url']}/v1/traces/receipt", headers={"Authorization": f"Bearer {key}"},
                     json={"trace_id": trace_id, "span_ids": [span_id]}).json()
check("a span sent to the public URL arrives", receipt == {"received": True}, receipt)
key_id = created.json()["record"]["id"]
check("the test key is revoked", master.delete(f"/lens/tracing/keys/{key_id}").status_code in (200, 204))

sys.exit(0 if all(results) else 1)

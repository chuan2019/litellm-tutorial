"""A fake OTLP/HTTP collector on port 4141 that prints every span it receives."""
from http.server import BaseHTTPRequestHandler, HTTPServer

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

SHOW = ("gen_ai.request.model", "gen_ai.usage.total_tokens", "gen_ai.cost.total_cost")


def value(v):
    """Unwrap an OTLP AnyValue into a Python value."""
    kind = v.WhichOneof("value")
    return getattr(v, kind) if kind else None


class Collector(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        for rs in ExportTraceServiceRequest.FromString(body).resource_spans:
            for ss in rs.scope_spans:
                for s in ss.spans:
                    if s.name.startswith("fastapi."):
                        continue
                    attrs = {a.key: value(a.value) for a in s.attributes}
                    kv = "  ".join(f"{k.split('.')[-1]}={attrs[k]}" for k in SHOW if k in attrs)
                    print(f"trace={s.trace_id.hex()[:8]} parent={s.parent_span_id.hex()[:8] or '-':8} "
                          f"{s.name:30} {kv}", flush=True)
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


HTTPServer(("127.0.0.1", 4141), Collector).serve_forever()

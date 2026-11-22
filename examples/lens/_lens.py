"""Shared helpers for the Lens examples: addresses, credentials and an OTLP tracer that sends to Lens."""
import os

import httpx
import litellm
from litellm.integrations.opentelemetry import OpenTelemetry
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

LENS_URL = os.environ.get("LENS_URL", "http://localhost:4319")
PROXY_URL = os.environ.get("PROXY_URL", "http://localhost:4000")
FAKE_LLM = "http://127.0.0.1:4017/v1"


def admin() -> httpx.Client:
    """Return a client for the Lens API, signed in with the standalone admin token."""
    return httpx.Client(base_url=LENS_URL, timeout=30,
                        headers={"Authorization": f"Bearer {os.environ['LENS_ADMIN_TOKEN']}"})


def gateway(key: str) -> httpx.Client:
    """Return a client for the proxy, which serves the same Lens API once connected."""
    return httpx.Client(base_url=PROXY_URL, timeout=30, headers={"Authorization": f"Bearer {key}"})


def setup_tracing(service: str, tracing_key: str) -> TracerProvider:
    """Send this process's spans, LiteLLM's included, to Lens; return the provider to flush."""
    # Without it LiteLLM names async calls "acompletion", which Lens does not count as a model call.
    os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "gen_ai_latest_experimental")
    os.environ["USE_OTEL_LITELLM_REQUEST_SPAN"] = "true"
    exporter = OTLPSpanExporter(endpoint=f"{LENS_URL}/v1/traces",
                                headers={"Authorization": f"Bearer {tracing_key}"})
    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    litellm.suppress_debug_info = True
    litellm.callbacks = [OpenTelemetry(tracer_provider=provider)]
    return provider


def setup_gateway_agent(master: httpx.Client) -> tuple[str, str]:
    """Create the support team, its admin owner, the agent's virtual key and a tracing key; return both keys."""
    if master.get("/team/info", params={"team_id": "support"}).status_code != 200:
        master.post("/team/new", json={"team_id": "support", "team_alias": "support"}).raise_for_status()
    if master.get("/user/info", params={"user_id": "agent-owner"}).status_code != 200:
        master.post("/user/new", json={"user_id": "agent-owner", "user_role": "proxy_admin"}).raise_for_status()
    agent_key = master.post("/key/generate", json={"user_id": "agent-owner", "team_id": "support",
                                                   "models": ["support"]}).json()["key"]
    # A tracing key takes its owner from the key that creates it, so create it with the agent's key.
    created = gateway(agent_key).post("/lens/tracing/keys",
                                      json={"name": "support-agent", "team_id": "support"}).json()
    return agent_key, created["key"]


def delivered(tracing_key: str, trace_ids: list[str]) -> list[bool]:
    """Ask Lens whether each trace arrived; the exporter drops a rejected batch without retrying."""
    with httpx.Client(base_url=LENS_URL, headers={"Authorization": f"Bearer {tracing_key}"}) as client:
        return [client.post("/v1/traces/receipt", json={"trace_id": t}).json()["received"] for t in trace_ids]

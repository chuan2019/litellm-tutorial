"""Trace LiteLLM calls with OpenTelemetry and inspect the spans in memory."""
import asyncio
import os

import litellm
from litellm.integrations.opentelemetry import OpenTelemetry, OpenTelemetryConfig
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from _mock import mock

# Without this, a call made inside your own span writes its attributes onto your span.
os.environ["USE_OTEL_LITELLM_REQUEST_SPAN"] = "true"
KEYS = ("gen_ai.system", "gen_ai.request.model", "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens", "gen_ai.cost.total_cost", "error.type")

litellm.suppress_debug_info = True
exporter = InMemorySpanExporter()
litellm.callbacks = [OpenTelemetry(config=OpenTelemetryConfig(exporter=exporter))]
tracer = trace.get_tracer("support-bot")
msgs = [{"role": "user", "content": "My order #1234 never arrived."}]


async def main():
    with tracer.start_as_current_span("handle_ticket"):
        await litellm.acompletion(model="openai/gpt-4o-mini", messages=msgs,
                                  **mock("Sorry! Let me check order #1234."))
        await litellm.acompletion(model="anthropic/claude-haiku-5-5", messages=msgs,
                                  metadata={"generation_name": "summarise"},
                                  **mock("Customer reports a missing order."))
    await asyncio.sleep(0.5)
    litellm.turn_off_message_logging = True
    await litellm.acompletion(model="openai/gpt-4o-mini", messages=msgs, **mock("Redacted reply."))
    try:
        await litellm.acompletion(model="openai/gpt-4o", messages=msgs, mock_response=litellm.RateLimitError(
            "slow down", llm_provider="openai", model="gpt-4o"))
    except litellm.RateLimitError:
        pass
    await asyncio.sleep(0.5)


def show(span, children, depth=0):
    """Print one span and its children as an indented tree."""
    attrs = span.attributes
    kv = "  ".join(f"{k.split('.')[-1]}={attrs[k]}" for k in KEYS if k in attrs)
    content = "content" if "gen_ai.input.messages" in attrs else ""
    print(f"{'  ' * depth}{span.name:<{24 - 2 * depth}} {span.status.status_code.name:5} {content:7} {kv}")
    for child in children.get(span.context.span_id, []):
        show(child, children, depth + 1)


asyncio.run(main())
spans = sorted(exporter.get_finished_spans(), key=lambda s: s.start_time)
children = {}
for s in spans:
    if s.parent:
        children.setdefault(s.parent.span_id, []).append(s)
for root in (s for s in spans if s.parent is None):
    show(root, children)
print(f"\n{len(spans)} spans, {len({s.context.trace_id for s in spans})} traces")

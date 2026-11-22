"""A small tool-using support agent, traced with OpenTelemetry GenAI spans."""
import asyncio
import json
import uuid

import litellm
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

ORDERS = {"1001": "shipped", "1002": "processing", "1003": "delivered"}
TOOLS = [{"type": "function", "function": {
    "name": "lookup_order", "description": "Look up an order's status by its 4-digit ID.",
    "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}},
                   "required": ["order_id"]}}}]
tracer = trace.get_tracer("support-agent")


def lookup_order(call_id: str, order_id: str) -> dict:
    """Run the tool inside an execute_tool span."""
    args = json.dumps({"order_id": order_id})
    with tracer.start_as_current_span("execute_tool lookup_order", attributes={
            "gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": "lookup_order",
            "gen_ai.tool.call.id": call_id, "gen_ai.tool.call.arguments": args}) as span:
        if order_id in ORDERS:
            result = {"order_id": order_id, "status": ORDERS[order_id]}
        else:
            result = {"order_id": order_id, "error": "order not found"}
            span.set_status(Status(StatusCode.ERROR, "order not found"))
        span.set_attribute("gen_ai.tool.call.result", json.dumps(result))
        return result


async def _call(messages: list[dict], model: str, **llm: object):
    """One model call; the same call ID goes to LiteLLM and, as a header, to a proxy."""
    call_id = str(uuid.uuid4())
    return await litellm.acompletion(model=model, messages=messages, tools=TOOLS, litellm_call_id=call_id,
                                     extra_headers={"x-litellm-call-id": call_id}, **llm)


async def run(question: str, model: str, attributes: dict | None = None, **llm: object) -> tuple[str, str]:
    """Answer one question inside an invoke_agent span; return the answer and the trace ID."""
    with tracer.start_as_current_span("invoke_agent support_agent", attributes={
            "gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": "support_agent",
            **(attributes or {})}) as span:
        messages = [{"role": "system", "content": "You answer questions about orders. "
                     "Always use lookup_order before stating an order's status."},
                    {"role": "user", "content": question}]
        for _ in range(4):
            message = (await _call(messages, model, **llm)).choices[0].message
            messages.append(message.model_dump(exclude_none=True))
            if not message.tool_calls:
                break
            for call in message.tool_calls:
                result = lookup_order(call.id, json.loads(call.function.arguments)["order_id"])
                messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)})
        span.set_attribute("gen_ai.output.messages", json.dumps([{"role": "assistant", "content": message.content}]))
        return message.content, format(span.get_span_context().trace_id, "032x")


async def run_all(questions: list[str], model: str, **llm: object) -> list[str]:
    """Run each question in order, print its answer, and return the trace IDs."""
    trace_ids = []
    for question in questions:
        answer, trace_id = await run(question, model, **llm)
        trace_ids.append(trace_id)
        print(f"{trace_id[:8]}  {question:36} -> {answer}")
    await asyncio.sleep(1)  # LiteLLM's async callbacks end their spans after acompletion returns
    return trace_ids

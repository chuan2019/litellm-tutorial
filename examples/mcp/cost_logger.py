"""Proxy callback that prints the cost LiteLLM records for each call, MCP tool calls included."""
from litellm.integrations.custom_logger import CustomLogger


class CostLogger(CustomLogger):
    """Print the call type, model and cost of every successful call."""

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        """Log one successful call."""
        slo = kwargs.get("standard_logging_object") or {}
        print(f"[cost] {slo.get('call_type'):15} {slo.get('model'):28} ${slo.get('response_cost')}", flush=True)


proxy_handler_instance = CostLogger()

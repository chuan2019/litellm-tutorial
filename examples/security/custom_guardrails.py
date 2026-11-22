"""A custom guardrail: refuse prompts about topics this deployment must not discuss."""
from fastapi import HTTPException

from litellm.integrations.custom_guardrail import CustomGuardrail

DENIED_TOPICS = ("medical diagnosis", "legal advice", "stock tips")


class TopicGuard(CustomGuardrail):
    """Block requests whose last user message mentions a denied topic."""

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        text = str(data.get("messages", [{}])[-1].get("content", "")).lower()
        for topic in DENIED_TOPICS:
            if topic in text:
                raise HTTPException(status_code=400, detail={"error": f"topic-guard: '{topic}' is out of scope"})
        return data

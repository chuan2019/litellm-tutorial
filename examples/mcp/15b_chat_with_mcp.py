"""Let the proxy run an MCP tool during a chat completion, with a mocked model."""
import os

from openai import OpenAI

client = OpenAI(base_url="http://localhost:4000", api_key=os.environ["LITELLM_MASTER_KEY"])

resp = client.chat.completions.create(
    model="chat-tools",
    messages=[{"role": "user", "content": "How much is an apple?"}],
    tools=[{"type": "mcp", "server_url": "litellm_proxy/mcp/catalog", "require_approval": "never"}],
)
msg = resp.choices[0].message
meta = msg.model_extra.get("provider_specific_fields") or {}
print("answer     :", msg.content)
print("tools sent :", [t["function"]["name"] for t in meta.get("mcp_list_tools", [])])
print("tool calls :", [c["function"]["name"] for c in meta.get("mcp_tool_calls", [])])
print("results    :", meta.get("mcp_call_results"))

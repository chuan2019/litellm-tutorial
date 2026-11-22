"""Connect the official MCP client to the LiteLLM gateway with a LiteLLM key."""
import os

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

GATEWAY = os.environ.get("GATEWAY", "http://localhost:4000/mcp")


def connect(key, url=GATEWAY, **headers):
    """Return an MCP client that authenticates to the gateway with a LiteLLM key."""
    http = httpx2.AsyncClient(headers={"x-litellm-api-key": f"Bearer {key}", **headers})
    return Client(streamable_http_client(url, http_client=http))

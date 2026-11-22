"""Give virtual keys different MCP servers and tools, then list what each key sees."""
import asyncio
import os
import time

import httpx

from _gateway import connect

PROXY = "http://localhost:4000"
ADMIN = {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}
SCOPES = {
    "no-scope": None,
    "catalog-only": {"mcp_servers": ["catalog"]},
    "price-tool-only": {"mcp_servers": ["catalog"], "mcp_tool_permissions": {"catalog": ["lookup_price"]}},
}


def make_key(alias, permission):
    """Create a virtual key with an optional MCP object permission."""
    body = {"key_alias": f"{alias}-{int(time.time())}", "object_permission": permission}
    r = httpx.post(f"{PROXY}/key/generate", headers=ADMIN, json=body)
    r.raise_for_status()
    return r.json()["key"]


async def visible_tools(key):
    """Return the tool names the gateway lists for a key."""
    try:
        async with connect(key) as client:
            return sorted(t.name for t in (await client.list_tools()).tools)
    except ExceptionGroup:
        return "refused (HTTP 403 on initialize)"


async def main():
    for alias, permission in SCOPES.items():
        key = make_key(alias, permission)
        print(f"{alias:16} {await visible_tools(key)}")
    key = make_key("price-call", SCOPES["price-tool-only"])
    async with connect(key) as client:
        result = await client.call_tool("catalog-in_stock", {"sku": "apple"})
        print("call in_stock   :", result.is_error, result.content[0].text)


if __name__ == "__main__":
    asyncio.run(main())

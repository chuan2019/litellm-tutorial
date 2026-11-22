"""List and call MCP tools through the LiteLLM gateway with the official MCP client."""
import asyncio
import os

from _gateway import connect


async def main():
    async with connect(os.environ["LITELLM_MASTER_KEY"]) as client:
        tools = (await client.list_tools()).tools
        print("server :", client.server_info.name)
        print("tools  :", sorted(t.name for t in tools))
        for name, args in [("catalog-lookup_price", {"sku": "apple"}),
                           ("mathbox-multiply", {"a": 6, "b": 7})]:
            result = await client.call_tool(name, args)
            print(f"{name}({args}) -> {result.content[0].text}  is_error={result.is_error}")


if __name__ == "__main__":
    asyncio.run(main())

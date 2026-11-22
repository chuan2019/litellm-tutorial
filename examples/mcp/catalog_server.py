"""A tiny MCP server with two shop tools, served over HTTP or stdio."""
import sys

from mcp.server.mcpserver import MCPServer

PRICES = {"apple": 0.5, "pear": 0.8}

mcp = MCPServer("catalog")


@mcp.tool()
def lookup_price(sku: str) -> float:
    """Return the unit price of a product in dollars."""
    return PRICES[sku]


@mcp.tool()
def in_stock(sku: str, quantity: int = 1) -> bool:
    """Say whether at least `quantity` units of a product are available."""
    return sku in PRICES and quantity <= 10


if __name__ == "__main__":
    if sys.argv[1:] == ["http"]:
        mcp.run("streamable-http", host="127.0.0.1", port=4111)
    else:
        mcp.run()

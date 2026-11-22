"""A tiny MCP server with two arithmetic tools, served over stdio."""
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("mathbox")


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


@mcp.tool()
def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b


if __name__ == "__main__":
    mcp.run()

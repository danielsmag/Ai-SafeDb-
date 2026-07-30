"""A minimal stdio MCP server, used as a proxy target in the gateway tests."""

from fastmcp import FastMCP

mcp = FastMCP("source")


@mcp.tool
def read_thing(name: str) -> str:
    """Return a greeting for `name`."""
    return f"read:{name}"


@mcp.tool
def delete_thing(name: str) -> str:
    """Pretend to delete something; the gateway policy should block this."""
    return f"deleted:{name}"


if __name__ == "__main__":
    mcp.run()

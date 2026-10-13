import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".runtime/python"))
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("local-agent-example")


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two integers, without side effects."""
    return a + b


@mcp.tool()
def fail() -> str:
    """Demonstrate a real tool error."""
    raise ValueError("Deliberate example failure")


if __name__ == "__main__":
    mcp.run(transport="stdio")

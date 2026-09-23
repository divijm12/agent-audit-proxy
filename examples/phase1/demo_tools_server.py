"""A tiny, harmless MCP tool server used to demo shugo.

None of these tools touch your real filesystem or run real commands. They
just return text describing what they *would* have done, so it's safe to
let an agent (or the demo client) call them.
"""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("demo-tools")


@mcp.tool()
def read_file(path: str) -> str:
    """Pretend to read a file."""
    return f"(pretend contents of {path})"


@mcp.tool()
def delete_file(path: str) -> str:
    """Pretend to delete a file."""
    return f"(pretend deleted {path})"


@mcp.tool()
def bash(command: str) -> str:
    """Pretend to run a shell command."""
    return f"(pretend ran: {command})"


if __name__ == "__main__":
    mcp.run()  # speaks MCP over stdin/stdout

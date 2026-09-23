"""Act like an agent: connect to shugo and send a few tool calls through it.

Run from the repo root:
    SHUGO_HOME=examples/phase1/.shugo-home .venv/bin/python examples/phase1/send_tool_calls.py
"""
import asyncio
import os
import sys

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

SHUGO = StdioServerParameters(
    command=os.path.join(os.path.dirname(sys.executable), "shugo"),
    args=["serve", "--config", "examples/phase1/guardrails.yaml"],
    env={**os.environ},
)

CALLS = [
    ("demo__read_file", {"path": "notes.txt"}),     # rule reads-are-fine   -> allow
    ("demo__delete_file", {"path": "notes.txt"}),   # rule no-deletes       -> deny
    ("demo__bash", {"command": "ls"}),              # rule shell-needs-a-human -> nobody approves, times out -> deny
]


async def main() -> None:
    async with stdio_client(SHUGO) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("Tools the agent can see:", [t.name for t in tools.tools])
            for name, args in CALLS:
                result = await session.call_tool(name, args)
                text = " ".join(c.text for c in result.content if hasattr(c, "text"))
                status = "ERROR" if result.isError else "OK"
                print(f"{name}({args}) -> {status}: {text}")


if __name__ == "__main__":
    asyncio.run(main())

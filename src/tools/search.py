"""Consume the search MCP server: launch it and call its `web_search` tool."""

import sys
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient

# Absolute path to our MCP server script (project_root/mcp_servers/search_server.py).
_SERVER = str(Path(__file__).resolve().parents[2] / "mcp_servers" / "search_server.py")


def _client() -> MultiServerMCPClient:
    """Configure a client that launches our server as a stdio subprocess."""
    return MultiServerMCPClient(
        {
            "search": {
                "command": sys.executable,   # the same Python running our app
                "args": [_SERVER],
                "transport": "stdio",
            }
        }
    )


async def search_web(query: str, max_results: int = 5) -> str:
    """Return formatted web-search results for `query` (via the MCP server)."""
    client = _client()
    tools = await client.get_tools()               # discover the server's tools
    tool = next(t for t in tools if t.name == "web_search")
    raw = await tool.ainvoke({"query": query, "max_results": max_results})
    # The adapter returns a list of content blocks like [{"type":"text","text": "..."}].
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        return "\n".join(b.get("text", "") for b in raw if isinstance(b, dict))
    return str(raw)

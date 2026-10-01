"""A tiny MCP server exposing a single `web_search` tool.

Run standalone, it speaks the MCP protocol over stdio. Our app launches it as a
subprocess and calls its tools via langchain-mcp-adapters (see src/tools/search.py).
"""

from ddgs import DDGS
from mcp.server.fastmcp import FastMCP

# FastMCP is the easy way to build an MCP server: decorate functions as tools.
mcp = FastMCP("search")


@mcp.tool()
def web_search(query: str, max_results: int = 5) -> str:
    """Search the web and return formatted results (title, URL, snippet)."""
    results = DDGS().text(query, max_results=max_results)
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(
            f"[{i}] {r.get('title', '')}\n"
            f"    URL: {r.get('href', '')}\n"
            f"    {r.get('body', '')}"
        )
    return "\n\n".join(lines) if lines else "No results found."


if __name__ == "__main__":
    # stdio transport: our app launches this file and talks over stdin/stdout.
    mcp.run(transport="stdio")

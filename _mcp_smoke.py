# -*- coding: utf-8 -*-
"""Смоук-тест MCP сервера free-search-mcp: handshake + tools/list."""
import asyncio
import json
import pathlib

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXE = r"d:\Downloads_D\lct_a8\.venv-mcp\Scripts\free-search-mcp.exe"


async def main():
    params = StdioServerParameters(command=EXE, args=[], env=None)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            info = getattr(init, "server_info", None) or getattr(init, "serverInfo", None)
            print("server:", info.name, info.version)
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print("tools:", ", ".join(names))
            pathlib.Path(__file__).resolve().parent.joinpath(
                "_mcp_smoke.json").write_text(
                json.dumps({"server": info.name,
                            "version": info.version,
                            "tools": names}, ensure_ascii=False, indent=2),
                encoding="utf-8")


if __name__ == "__main__":
    import sys
    # Windows: anyio/stdio требует selector event loop (Proactor не умеет subprocess add_reader)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
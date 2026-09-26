# -*- coding: utf-8 -*-
"""Смоук: вызов search через MCP + сбор материала о конкурентах ЖКХ."""
import asyncio
import json
import pathlib
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXE = r"d:\Downloads_D\lct_a8\.venv-mcp\Scripts\free-search-mcp.exe"
QUERIES = [
    "Siemens predictive maintenance water utility digital twin remaining useful life",
    "Thames Water AI predictive pump maintenance smart water",
    "Росводоканал цифровой водоканал предиктивная аналитика Москва",
    "NIST smoke detector nuisance false alarms percentage study",
    "risk based asset management water network why not predict exact failure",
    "smart sewer digital twin Singapore PUB New York DEP city analytics",
]


async def main():
    params = StdioServerParameters(command=EXE, args=[], env=None)
    out = []
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for q in QUERIES:
                try:
                    res = await session.call_tool("search", {"query": q, "max_results": 6})
                    texts = []
                    for c in (res.content or []):
                        t = getattr(c, "text", None) or ""
                        texts.append(t)
                    blob = "\n".join(texts)
                    out.append(f"===== QUERY: {q} =====\n{blob[:2600]}\n")
                except Exception as e:
                    out.append(f"===== QUERY: {q} =====\nERROR: {e}\n")
    pathlib.Path(r"d:\Downloads_D\lct_a8\_mcp_search_out.txt").write_text(
        "\n".join(out), encoding="utf-8")
    print("saved", len("\n".join(out)), "chars")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
"""MCP-пробник: коннект и список инструментов каждого сервера реестра.

Подключается к каждому серверу из реестра MCP_SERVERS (config.py),
печатает server_info, согласованную версию протокола и таблицу
инструментов (имя / описание / схема аргументов). Работает без
веб-приложения:

    .venv/bin/python day17/mcp_probe.py

Код выхода 1, если хоть одна запись не подключилась.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import MCP_SERVERS  # noqa: E402
from mcp_hub import make_client, short_error  # noqa: E402


async def probe_one(spec: dict) -> int:
    sid = spec.get("id", "?")
    transport = spec.get("transport", "?")
    print(f"== {sid} ({transport}) ==")
    try:
        async with make_client(spec) as client:
            tools = await asyncio.wait_for(client.list_tools(), timeout=20)
            info = client.server_info
            proto = client.protocol_version
    except Exception as exc:
        print(f"   не подключён: {short_error(exc)}")
        return 1

    info_str = f"{info.name} v{info.version}" if info else "?"
    print(f"   подключён: {info_str}, протокол {proto}")
    print(f"   инструментов: {len(tools.tools)}")
    for tool in tools.tools:
        print(f"   - {tool.name}")
        if tool.description:
            print(f"       {tool.description}")
        schema = json.dumps(tool.input_schema or {}, ensure_ascii=False)
        print(f"       schema: {schema}")
    return 0


async def main() -> int:
    print(f"MCP-пробник: реестр из config.py, записей {len(MCP_SERVERS)}\n")
    fails = 0
    for spec in MCP_SERVERS:
        fails += await probe_one(spec)
        print()
    if fails:
        print(f"не подключилось записей: {fails} — смотри статусы выше")
        return 1
    print("все серверы реестра ответили")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

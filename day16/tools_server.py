"""Демо MCP-сервер на Python (stdio): время, арифметика, эхо, заметки.

stdout зарезервирован под JSON-RPC — логов туда не пишем никогда,
иначе протокол развалится. Заметки живут в памяти процесса: restart
сервера их обнуляет.
"""
from datetime import datetime

from mcp.server import MCPServer

app = MCPServer(name="py-tools", version="0.1.0")

NOTES: list[str] = []


@app.tool(description="Текущее время сервера и дата (ГГГГ-ММ-ДД ЧЧ:ММ:СС)")
def server_time() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@app.tool(description="Сложить два числа")
def add(a: float, b: float) -> float:
    return a + b


@app.tool(description="Вернуть строку как есть — проверка round-trip аргументов")
def echo(text: str) -> str:
    return text


@app.tool(description="Список заметок из in-memory хранилища сервера")
def notes_list() -> list[str]:
    return list(NOTES)


@app.tool(description="Добавить заметку и вернуть её номер")
def notes_add(text: str) -> str:
    NOTES.append(text)
    return f"заметка #{len(NOTES)} сохранена"


if __name__ == "__main__":
    app.run()  # transport="stdio"

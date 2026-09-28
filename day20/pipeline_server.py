"""MCP-сервер «pipeline» (stdio): search → summarize → save_to_file.

Инструменты изолированы — ни один не вызывает другой через MCP.
Композиция живёт на стороне хоста (цикл агента или код /api/pipeline).
run_pipeline — контрольная дорожка: та же цепочка, но внутри одного
вызова инструмента, без межинструментных хопов на уровне MCP.

summarize вызывает deepseek-модель (инструмент, который сам ходит в LLM);
без DEEPSEEK_API_KEY — детерминированный экстрактивный фолбэк, чтобы
пайплайн работал офлайн. Клиент создаётся лениво на первом вызове:
openai SDK падает на пустом api_key уже при конструировании.

stdout зарезервирован под JSON-RPC — логи только в stderr.
"""
import hashlib
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server import MCPServer  # noqa: E402

DAY20_DIR = Path(__file__).resolve().parent
CORPUS_DIR = DAY20_DIR / "corpus"
OUT_DIR = DAY20_DIR / "out"

SUMMARIZE_MODEL = "deepseek-v4-flash"
SUMMARIZE_BUDGET = 400  # экстрактивный фолбэк: столько символов максимум

app = MCPServer(name="pipeline", version="0.1.0")

_client = None


def _llm_client():
    """Ленивый клиент deepseek; None, если ключа нет — тогда фолбэк."""
    global _client
    if _client is None:
        import config
        try:
            _client = config.get_client("deepseek")
        except RuntimeError:
            _client = False
    return _client or None


def _search(query: str, limit: int = 3) -> str:
    """Параграфы корпуса со ВСЕМИ терминами запроса (слова ≥3 букв,
    регистр не важен) — иначе «композиция MCP» не находила бы абзац,
    где слова стоят по разные стороны предложения."""
    terms = [w for w in re.findall(r"\w+", query.lower()) if len(w) >= 3]
    if not terms:
        return "пустой запрос — ничего не найдено"
    hits: list[str] = []
    for path in sorted(CORPUS_DIR.glob("*.txt")):
        for para in path.read_text(encoding="utf-8").split("\n\n"):
            para = para.strip()
            if para and all(t in para.lower() for t in terms):
                hits.append(f"[{path.name}]\n{para}")
                if len(hits) >= limit:
                    return "\n\n".join(hits)
    if not hits:
        return f"по запросу «{query}» в корпусе ничего не найдено"
    return "\n\n".join(hits)


def _extractive(text: str) -> str:
    """Первые предложения до бюджета символов — детерминированный фолбэк."""
    flat = re.sub(r"\s+", " ", text).strip()
    if len(flat) <= SUMMARIZE_BUDGET:
        return flat
    cut = flat[:SUMMARIZE_BUDGET]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return (cut[: end + 1] if end > 40 else cut.rsplit(" ", 1)[0]).strip()


def _summarize(text: str) -> tuple[str, str]:
    """(digest, mode): mode = 'llm' | 'extractive'."""
    cli = _llm_client()
    if cli is not None:
        try:
            resp = cli.chat.completions.create(
                model=SUMMARIZE_MODEL,
                messages=[
                    {"role": "system", "content": "Сожми текст до 2–3 предложений по-русски, сохрани факты. Без вступлений."},
                    {"role": "user", "content": text[:8000]},
                ],
                temperature=0.2,
                # нативные рассуждения deepseek тратят max_tokens — оставляем
                # запас, иначе content приходит пустым и уходим в фолбэк
                max_tokens=1400,
            )
            digest = (resp.choices[0].message.content or "").strip()
            if digest:
                print("[pipeline] summarize mode=llm", file=sys.stderr, flush=True)
                return digest, "llm"
        except Exception as e:  # ключ есть, но API упал — всё равно фолбэк
            print(f"[pipeline] summarize llm failed: {e}", file=sys.stderr, flush=True)
    print("[pipeline] summarize mode=extractive", file=sys.stderr, flush=True)
    return _extractive(text), "extractive"


_SAFE_NAME = re.compile(r"[^\w.\-]+", re.UNICODE)


def _save_to_file(name: str, text: str) -> str:
    """Записать text в out/<name>; имя санитизируется до безопасного basename."""
    safe = _SAFE_NAME.sub("_", Path(name.strip()).name).strip("._-")
    if not safe:
        safe = "result"
    if not safe.endswith(".txt"):
        safe += ".txt"
    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / safe
    path.write_text(text, encoding="utf-8")
    n = len(text.encode("utf-8"))
    return f"сохранено: out/{safe} ({n} байт)"


@app.tool(description="Поиск по локальному корпусу текстов: вернуть абзацы, где встречается запрос")
def search(query: str, limit: int = 3) -> str:
    return _search(query, limit)


@app.tool(description="Сжать текст до краткого дайджеста (через LLM, либо экстрактивно без ключа)")
def summarize(text: str) -> str:
    return _summarize(text)[0]


@app.tool(description="Сохранить текст в файл в каталоге out/ и вернуть путь и размер")
def save_to_file(name: str, text: str) -> str:
    return _save_to_file(name, text)


@app.tool(description="Весь пайплайн одним вызовом: search → summarize → save_to_file внутри сервера")
def run_pipeline(query: str) -> str:
    found = _search(query)
    digest, mode = _summarize(found)
    saved = _save_to_file("pipeline-composite", digest)
    sha = hashlib.sha256(found.encode("utf-8")).hexdigest()[:12]
    return (
        f"этап 1 search: {len(found)} симв., sha256:{sha}…\n"
        f"этап 2 summarize ({mode}): {len(digest)} симв.\n"
        f"этап 3 save: {saved}\n\n"
        f"итог:\n{digest}"
    )


if __name__ == "__main__":
    app.run()  # transport="stdio"

import re
import threading
from pathlib import Path

from config import complete

MEMORY_CHUNK = 12
WORKING_MAX_FACTS = 15
WORKING_MAX_PLAN = 10
WORKING_MAX_VALUE_CHARS = 200
WORKING_MAX_GOAL_CHARS = 300
WORKING_MAX_CHARS = 4000
LONGTERM_MAX_BULLETS = 30
LONGTERM_MAX_VALUE_CHARS = 200
LONGTERM_MAX_CHARS = 8000
LONGTERM_MAX_BODY = 20_000

DAY11_DIR = Path(__file__).parent
LONGTERM_PATH = DAY11_DIR / "memory" / "longterm.md"
LONGTERM_SECTIONS = ("Профиль", "Решения", "Знания")
SECTION_MAP = {name.lower(): name for name in LONGTERM_SECTIONS}

EMPTY_WORKING = {"goal": "", "plan": [], "facts": []}

MEMORY_LOCK = threading.RLock()

MEMORY_SYSTEM_PROMPT = (
    "Ты — редактор памяти агента. Память делится на два слоя: "
    "РАБОЧАЯ — данные текущей задачи (цель, план, сроки, бюджет, ограничения, "
    "принятые по задаче решения); ДОЛГОСРОЧНАЯ — данные о пользователе и общие "
    "знания (профиль, стек, предпочтения, решения и факты, полезные в любой задаче). "
    "Тебе дают текущее состояние обоих слоёв и новые сообщения диалога. Обнови их: "
    "сохрани актуальное, дополни новым, устаревшее переформулируй или убери. "
    "То, что не относится ни к задаче, ни к пользователю, не сохраняй. "
    "Формат ответа строгий, без пояснений и markdown-разметки:\n"
    "ЦЕЛЬ: <одна строка — цель задачи>\n"
    "ПЛАН:\n"
    "- шаг плана\n"
    "ФАКТЫ:\n"
    "ключ: значение\n"
    "ДОЛГОСРОЧНОЕ:\n"
    "Профиль | ключ: значение\n"
    "Решения | ключ: значение\n"
    "Знания | ключ: значение\n"
    "Правила: не больше 15 фактов, 10 шагов плана и 10 долговременных строк; "
    "каждая строка — одна короткая фраза. Пустой блок верни заголовком без строк. "
    "Если запоминать вообще нечего — верни только заголовки."
)

_HEADER_RE = re.compile(
    r"^[\s#*_\-]*?(ЦЕЛЬ|ПЛАН|ФАКТЫ|ДОЛГОСРОЧНОЕ|ДОЛГОСРОЧНАЯ)\b\s*:?-?\s*(.*)$",
    re.IGNORECASE,
)
_SECTION_HEADER_RE = re.compile(r"^#{1,6}\s*(.+?)\s*#*\s*$")


def _header(line: str):
    m = _HEADER_RE.match(line)
    if not m:
        return None, None
    raw_kw, rest = m.group(1), m.group(2).strip()
    # keyword written lowercase/titlecase counts as a header only with no inline
    # content — otherwise it is a data line like «цель: запустить сайт»
    if raw_kw != raw_kw.upper() and rest:
        return None, None
    kw = raw_kw.upper()
    if kw == "ДОЛГОСРОЧНАЯ":
        kw = "ДОЛГОСРОЧНОЕ"
    return kw, rest


def _split_pair(line: str):
    key, sep, value = line.partition(":")
    if not sep:
        return None
    key = key.strip()[:WORKING_MAX_VALUE_CHARS]
    value = value.strip()[:WORKING_MAX_VALUE_CHARS]
    if not key or not value:
        return None
    return [key, value]


def cap_pairs(pairs, max_pairs=WORKING_MAX_FACTS, max_chars=WORKING_MAX_CHARS):
    out = []
    total = 0
    for pair in pairs or []:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        key = str(pair[0]).strip()[:WORKING_MAX_VALUE_CHARS]
        value = str(pair[1]).strip()[:WORKING_MAX_VALUE_CHARS]
        if not key or not value:
            continue
        total += len(key) + len(value)
        if total > max_chars:
            break
        out.append([key, value])
        if len(out) >= max_pairs:
            break
    return out


def _split_longterm(line: str):
    # «Секция | ключ: значение» → (section, [k, v]); голое «Секция:» → (section, None)
    if "|" in line:
        left, _, right = line.partition("|")
        sec = SECTION_MAP.get(left.strip().lower())
        if sec:
            return sec, _split_pair(right.strip())
    key, sep, value = line.partition(":")
    if sep and not value.strip() and key.strip().lower() in SECTION_MAP:
        return SECTION_MAP[key.strip().lower()], None
    return None, _split_pair(line)


def parse_memory(text: str):
    """Секционный ответ экстрактора → dict или None, если заголовков нет вообще."""
    result = {"goal": "", "plan": [], "facts": [], "longterm": {}}
    if not (text or "").strip():
        return result
    section = None
    lt_section = "Знания"
    seen_header = False
    lt_total = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        kw, rest = _header(line)
        if kw:
            seen_header = True
            section = kw
            if kw == "ЦЕЛЬ" and rest:
                result["goal"] = rest[:WORKING_MAX_GOAL_CHARS]
            continue
        line = line.lstrip("-•*").strip()
        if not line:
            continue
        if section == "ПЛАН":
            result["plan"].append(line[:WORKING_MAX_VALUE_CHARS])
        elif section == "ФАКТЫ":
            pair = _split_pair(line)
            if pair:
                result["facts"].append(pair)
        elif section == "ДОЛГОСРОЧНОЕ":
            sec, pair = _split_longterm(line)
            if sec:
                lt_section = sec
            if pair:
                if lt_total < LONGTERM_MAX_BULLETS:
                    result["longterm"].setdefault(lt_section, []).append(pair)
                    lt_total += 1
        elif section == "ЦЕЛЬ" and not result["goal"]:
            result["goal"] = line[:WORKING_MAX_GOAL_CHARS]
    if not seen_header:
        return None
    result["plan"] = result["plan"][:WORKING_MAX_PLAN]
    result["facts"] = cap_pairs(result["facts"])
    return result


def update_memory(working, longterm_sections, messages, model: str, client=None):
    blocks = []
    wt = working_text(working)
    if wt:
        blocks.append("Текущая рабочая память:\n" + wt)
    lt = longterm_text(longterm_sections)
    if lt:
        blocks.append("Текущая долговременная память:\n" + lt)
    lines = [
        f"{'Пользователь' if m['role'] == 'user' else 'Ассистент'}: {m['content']}"
        for m in messages
    ]
    blocks.append("Новые сообщения диалога:\n" + "\n".join(lines))
    blocks.append("Обновлённое состояние памяти:")
    resp = complete(
        [
            {"role": "system", "content": MEMORY_SYSTEM_PROMPT},
            {"role": "user", "content": "\n\n".join(blocks)},
        ],
        model=model,
        client=client,
        temperature=0,
    )
    text = (resp.choices[0].message.content or "").strip()
    return parse_memory(text), getattr(resp, "usage", None), text


def normalize_working(state) -> dict:
    out = {"goal": "", "plan": [], "facts": []}
    if not isinstance(state, dict):
        return out
    goal = state.get("goal")
    if isinstance(goal, str):
        out["goal"] = goal.strip()[:WORKING_MAX_GOAL_CHARS]
    plan = state.get("plan")
    if isinstance(plan, list):
        out["plan"] = [
            str(p).strip()[:WORKING_MAX_VALUE_CHARS]
            for p in plan
            if str(p).strip()
        ][:WORKING_MAX_PLAN]
    out["facts"] = cap_pairs(state.get("facts"))
    return out


def working_text(state) -> str:
    state = normalize_working(state)
    parts = []
    if state["goal"]:
        parts.append(f"Цель: {state['goal']}")
    if state["plan"]:
        parts.append("План:\n" + "\n".join(f"- {p}" for p in state["plan"]))
    if state["facts"]:
        parts.append("Факты:\n" + "\n".join(f"{k}: {v}" for k, v in state["facts"]))
    return "\n".join(parts)


def render_working_message(state) -> dict:
    return {
        "role": "system",
        "content": (
            "РАБОЧАЯ ПАМЯТЬ — данные текущей задачи (цель, план, факты). "
            "Учитывай их наравне с перепиской:\n" + working_text(state)
        ),
    }


def render_longterm_message(content: str) -> dict:
    return {
        "role": "system",
        "content": (
            "ДОЛГОСРОЧНАЯ ПАМЯТЬ — профиль, решения и знания пользователя; "
            "действует во всех чатах:\n" + content
        ),
    }


def longterm_text(sections) -> str:
    if not isinstance(sections, dict):
        return ""
    parts = []
    for name, pairs in sections.items():
        pairs = cap_pairs(pairs, max_pairs=LONGTERM_MAX_BULLETS, max_chars=LONGTERM_MAX_CHARS)
        if pairs:
            parts.append(f"{name}:\n" + "\n".join(f"- {k}: {v}" for k, v in pairs))
    return "\n".join(parts)


def parse_longterm(text: str) -> dict:
    sections = {name: [] for name in LONGTERM_SECTIONS}
    current = None
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = _SECTION_HEADER_RE.match(line)
        if m:
            current = m.group(1).strip()
            sections.setdefault(current, [])
            continue
        if current is None:
            continue
        pair = _split_pair(line.lstrip("-•*").strip())
        if pair:
            sections[current].append(pair)
    return {name: pairs for name, pairs in sections.items() if pairs or name in LONGTERM_SECTIONS}


def read_longterm(path) -> dict:
    empty = {name: [] for name in LONGTERM_SECTIONS}
    try:
        content = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {"content": "", "sections": empty, "has_content": False}
    sections = parse_longterm(content)
    has = any(sections.values())
    if not has:
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if line and not _SECTION_HEADER_RE.match(line):
                has = True
                break
    return {"content": content, "sections": sections, "has_content": has}


def write_longterm(path, sections_update) -> list:
    """Дописывает пары в файл под своими секциями, дедуп по ключу. Возвращает применённые [секция, ключ, значение]."""
    applied = []
    with MEMORY_LOCK:
        data = read_longterm(path)
        sections = data["sections"]
        for sec, pairs in (sections_update or {}).items():
            sec_name = sec if sec in sections else SECTION_MAP.get(str(sec).strip().lower(), "Знания")
            for pair in pairs or []:
                if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                    continue
                key = str(pair[0]).strip()[:LONGTERM_MAX_VALUE_CHARS]
                value = str(pair[1]).strip()[:LONGTERM_MAX_VALUE_CHARS]
                if not key or not value:
                    continue
                landed = sec_name
                found = False
                for name, plist in sections.items():
                    for i, (ek, _ev) in enumerate(plist):
                        if ek.lower() == key.lower():
                            plist[i] = [ek, value]
                            landed = name
                            found = True
                            break
                    if found:
                        break
                if not found:
                    sections.setdefault(sec_name, []).append([key, value])
                applied.append([landed, key, value])
        ordered = [name for name in LONGTERM_SECTIONS if name in sections]
        ordered += [name for name in sections if name not in LONGTERM_SECTIONS]
        lines = []
        for name in ordered:
            pairs = sections[name][:LONGTERM_MAX_BULLETS]
            lines.append(f"## {name}")
            lines += [f"- {k}: {v}" for k, v in pairs]
            lines.append("")
        content = "\n".join(lines).strip() + "\n"
        while len(content) > LONGTERM_MAX_CHARS and ordered:
            name = ordered[-1]
            if sections[name]:
                sections[name].pop()
            else:
                ordered.pop()
                continue
            lines = []
            for nm in ordered:
                lines.append(f"## {nm}")
                lines += [f"- {k}: {v}" for k, v in sections[nm]]
                lines.append("")
            content = "\n".join(lines).strip() + "\n"
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return applied


def write_longterm_raw(path, content: str) -> dict:
    with MEMORY_LOCK:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return read_longterm(path)

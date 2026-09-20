import re
import threading
from pathlib import Path

from config import complete

MEMORY_CHUNK = 12
PAIR_MAX_VALUE_CHARS = 200
LONGTERM_MAX_BULLETS = 30
LONGTERM_MAX_VALUE_CHARS = 200
LONGTERM_MAX_CHARS = 8000
LONGTERM_MAX_BODY = 20_000
EXTRACT_MAX_LINES = 10

DAY12_DIR = Path(__file__).parent
LONGTERM_PATH = DAY12_DIR / "memory" / "longterm.md"
LONGTERM_SECTIONS = ("Профиль", "Решения", "Знания")
SECTION_MAP = {name.lower(): name for name in LONGTERM_SECTIONS}

MEMORY_LOCK = threading.RLock()

MEMORY_SYSTEM_PROMPT = (
    "Ты — редактор долговременной памяти агента. Долговременная память — только "
    "сведения о пользователе, которые переживут текущий разговор: Профиль — кто он "
    "(имя, роль, стек); Решения — его устойчивые принципы и договорённости уровня "
    "«всегда/никогда»; Знания — общие справочные факты, полезные в любой задаче. "
    "Тебе дают текущую долговременную память, профиль пользователя (заявленные им "
    "самим предпочтения) и новые сообщения диалога. Дополни память новым, "
    "актуальное сохрани, устаревшее переформулируй. "
    "Проверка для строки: обязана читаться самостоятельно, без контекста переписки — "
    "«налоги: патент удобнее» плохо (удобнее для чего?), «стек: Python» хорошо. "
    "Уже заявленное в профиле пользователя не дублируй — оно и так видно в каждом "
    "запросе. Сомневаешься — не пиши: лучше пропустить, чем засорять. "
    "Формат ответа строгий, без пояснений и markdown-разметки:\n"
    "ДОЛГОСРОЧНОЕ:\n"
    "Профиль | ключ: значение\n"
    "Решения | ключ: значение\n"
    "Знания | ключ: значение\n"
    "Правила: не больше 10 строк; каждая строка — одна короткая фраза. "
    "Если запоминать нечего — верни один заголовок ДОЛГОСРОЧНОЕ без строк."
)

_LT_HEADER_RE = re.compile(
    r"^[\s#*_\-]*?ДОЛГОСРОЧН(ОЕ|АЯ)\b\s*:?-?\s*$",
    re.IGNORECASE,
)
_SECTION_HEADER_RE = re.compile(r"^#{1,6}\s*(.+?)\s*#*\s*$")


def _split_pair(line: str):
    key, sep, value = line.partition(":")
    if not sep:
        return None
    key = key.strip()[:PAIR_MAX_VALUE_CHARS]
    value = value.strip()[:PAIR_MAX_VALUE_CHARS]
    if not key or not value:
        return None
    return [key, value]


def cap_pairs(pairs, max_pairs=LONGTERM_MAX_BULLETS, max_chars=LONGTERM_MAX_CHARS):
    out = []
    total = 0
    for pair in pairs or []:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        key = str(pair[0]).strip()[:LONGTERM_MAX_VALUE_CHARS]
        value = str(pair[1]).strip()[:LONGTERM_MAX_VALUE_CHARS]
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
    # «Секция | ключ: значение» → (section, [k, v]); голое «Секция:» → (section, None);
    # «Незнакомая | ключ: значение» → пара без смены секции (ключ — справа от |)
    if "|" in line:
        left, _, right = line.partition("|")
        sec = SECTION_MAP.get(left.strip().lower())
        if sec:
            return sec, _split_pair(right.strip())
        pair = _split_pair(right.strip())
        if pair:
            return None, pair
    key, sep, value = line.partition(":")
    if sep and not value.strip() and key.strip().lower() in SECTION_MAP:
        return SECTION_MAP[key.strip().lower()], None
    return None, _split_pair(line)


def parse_extraction(text: str):
    """Ответ экстрактора → {"longterm": {секция: [[ключ, значение]]}};
    None — если в ответе нет ни заголовка, ни одной распознанной строки."""
    if not (text or "").strip():
        return {"longterm": {}}
    result = {}
    lt_section = "Знания"
    seen = False
    total = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _LT_HEADER_RE.match(line):
            seen = True
            continue
        line = line.lstrip("-•*").strip()
        if not line:
            continue
        sec, pair = _split_longterm(line)
        if sec:
            seen = True
            lt_section = sec
        if pair:
            seen = True
            if total < EXTRACT_MAX_LINES:
                result.setdefault(lt_section, []).append(pair)
                total += 1
    if not seen:
        return None
    return {"longterm": result}


def drop_declared(longterm, profile_sections) -> dict:
    """Убирает долговременные строки, чей ключ уже заявлен в профиле
    пользователя: профиль виден в каждом запросе, дублировать его не надо."""
    if not longterm:
        return {}
    keys = {
        str(p[0]).strip().lower()
        for pairs in (profile_sections or {}).values()
        for p in (pairs or [])
        if isinstance(p, (list, tuple)) and p and str(p[0]).strip()
    }
    out = {}
    for sec, pairs in longterm.items():
        kept = [
            p
            for p in pairs or []
            if isinstance(p, (list, tuple))
            and len(p) >= 2
            and str(p[0]).strip().lower() not in keys
        ]
        if kept:
            out[sec] = kept
    return out


def update_memory(longterm_sections, messages, model: str, profile_text="", profile_sections=None, client=None):
    blocks = []
    if profile_text:
        blocks.append(
            "Профиль пользователя (уже заявлено — в память не дублировать):\n"
            + profile_text
        )
    lt = longterm_text(longterm_sections)
    if lt:
        blocks.append("Текущая долговременная память:\n" + lt)
    lines = [
        f"{'Пользователь' if m['role'] == 'user' else 'Ассистент'}: {m['content']}"
        for m in messages
    ]
    blocks.append("Новые сообщения диалога:\n" + "\n".join(lines))
    blocks.append("Дополнение к долговременной памяти:")
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
    parsed = parse_extraction(text)
    if parsed is not None:
        parsed["longterm"] = drop_declared(parsed["longterm"], profile_sections)
    return parsed, getattr(resp, "usage", None), text


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
                changed = False
                for name, plist in sections.items():
                    for i, (ek, ev) in enumerate(plist):
                        if ek.lower() == key.lower():
                            if ev != value:
                                plist[i] = [ek, value]
                                changed = True
                            landed = name
                            found = True
                            break
                    if found:
                        break
                if not found:
                    sections.setdefault(sec_name, []).append([key, value])
                    changed = True
                if changed:
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

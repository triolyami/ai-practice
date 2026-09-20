import hashlib
import re
from pathlib import Path

DAY14_DIR = Path(__file__).parent
INVARIANTS_DIR = DAY14_DIR / "invariants"

INV_MAX_BULLETS = 30
INV_MAX_VALUE_CHARS = 200
INV_MAX_BODY = 20_000
INV_MAX_CHECKS = 20
INV_MAX_PATTERN = 400
INV_MAX_NAME = 120
CHECKS_SECTION = "Проверки"

REFUSAL_PREFIX = "ОТКАЗ"
MATCH_MAX_CHARS = 120

SLUG_RE = re.compile(r"^[\w-]{1,80}$", re.UNICODE)
_TITLE_RE = re.compile(r"^#\s+(.+?)\s*#*\s*$")
_SECTION_HEADER_RE = re.compile(r"^#{1,6}\s*(.+?)\s*#*\s*$")
_FENCE_RE = re.compile(r"```[^\n]*\n.*?(?:```|\Z)", re.DOTALL)
_CHECK_KINDS = {"бан": "ban", "бан-код": "ban_code"}
CHECK_LABELS = {"ban": "бан", "ban_code": "бан-код"}


def slugify(name: str) -> str:
    slug = re.sub(r"[^\w]+", "-", (name or "").strip().lower()).strip("-")
    if not slug:
        slug = "i-" + hashlib.sha1((name or "x").encode("utf-8")).hexdigest()[:10]
    return slug[:60]


def _invariant_path(slug: str) -> Path:
    return INVARIANTS_DIR / f"{slug}.md"


def _split_pair(line: str):
    key, sep, value = line.partition(":")
    if not sep:
        return None
    key = key.strip()
    value = value.strip()
    if not key or not value:
        return None
    return [key, value]


def _compile_check(kind: str, pattern: str) -> dict | None:
    pattern = (pattern or "").strip()[:INV_MAX_PATTERN]
    if not pattern:
        return None
    try:
        rx = re.compile(pattern)
    except re.error:
        return {"kind": kind, "pattern": pattern, "regex": None, "broken": True}
    return {"kind": kind, "pattern": pattern, "regex": rx, "broken": False}


def parse_invariant(content: str) -> dict:
    """Секционный markdown набора инвариантов → {name, sections, checks}.

    `# Имя` — отображаемое имя; `## Секция` + `- ключ: значение` — правила
    для человека и модели; `## Проверки` — машинные проверки линтера:
    `- бан: <regex>` сканирует весь ответ, `- бан-код: <regex>` — только
    fenced-блоки кода (включая языковой тег ограждения).
    """
    name = ""
    sections: dict[str, list] = {}
    checks: list[dict] = []
    current = None
    for raw_line in (content or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if not line.startswith("##"):
            m = _TITLE_RE.match(line)
            if m:
                name = m.group(1).strip()[:INV_MAX_NAME]
                continue
        m = _SECTION_HEADER_RE.match(line)
        if m and line.startswith("##"):
            current = m.group(1).strip()
            continue
        bullet = line.lstrip("-•*").strip()
        pair = _split_pair(bullet)
        if not pair or current is None:
            continue
        if current == CHECKS_SECTION:
            kind = _CHECK_KINDS.get(pair[0].strip().lower())
            if kind and len(checks) < INV_MAX_CHECKS:
                check = _compile_check(kind, pair[1])
                if check:
                    checks.append(check)
        else:
            pair = [pair[0][:INV_MAX_VALUE_CHARS], pair[1][:INV_MAX_VALUE_CHARS]]
            sec = sections.setdefault(current, [])
            if len(sec) < INV_MAX_BULLETS:
                sec.append(pair)
    return {"name": name, "sections": sections, "checks": checks}


def invariant_rules_text(parsed: dict) -> str:
    parts = []
    for sec, pairs in (parsed.get("sections") or {}).items():
        if pairs:
            parts.append(f"{sec}:\n" + "\n".join(f"- {k}: {v}" for k, v in pairs))
    checks = [c for c in parsed.get("checks") or [] if not c.get("broken")]
    if checks:
        parts.append(
            "Машинные проверки ответа (линтер):\n"
            + "\n".join(f"- {CHECK_LABELS[c['kind']]}: {c['pattern']}" for c in checks)
        )
    return "\n\n".join(parts)


def read_invariant(slug: str) -> dict | None:
    """Набор по слугу или None. Перечитывает файл с диска при каждом вызове."""
    if not slug or not SLUG_RE.match(slug):
        return None
    try:
        content = _invariant_path(slug).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if not content.strip():
        return None
    parsed = parse_invariant(content[: INV_MAX_BODY + 1])
    return {
        "id": slug,
        "name": parsed["name"] or slug,
        "content": content,
        "sections": parsed["sections"],
        "checks": parsed["checks"],
        "rules_text": invariant_rules_text(parsed),
    }


def list_invariants() -> list[dict]:
    out = []
    try:
        files = sorted(INVARIANTS_DIR.glob("*.md"))
    except OSError:
        return out
    for path in files:
        slug = path.stem
        inv = read_invariant(slug)
        if inv is None:
            continue
        out.append({
            "id": slug,
            "name": inv["name"],
            "sections": inv["sections"],
            "checks": [
                {"kind": c["kind"], "pattern": c["pattern"], "broken": c["broken"]}
                for c in inv["checks"]
            ],
        })
    return out


def write_invariant(slug: str, content: str) -> dict:
    if not SLUG_RE.match(slug or ""):
        raise ValueError("id набора — слэг из букв, цифр, - и _ (до 80 символов).")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Пустой набор не сохраняется — добавьте секции.")
    if len(content) > INV_MAX_BODY:
        raise ValueError(f"Файл набора длиннее {INV_MAX_BODY} символов.")
    INVARIANTS_DIR.mkdir(parents=True, exist_ok=True)
    _invariant_path(slug).write_text(content, encoding="utf-8")
    inv = read_invariant(slug)
    return {"id": slug, "name": (inv or {}).get("name") or slug}


def delete_invariant(slug: str) -> bool:
    if not slug or not SLUG_RE.match(slug):
        return False
    try:
        _invariant_path(slug).unlink()
        return True
    except OSError:
        return False


def _hit(check: dict, m: re.Match) -> dict:
    return {
        "kind": check["kind"],
        "pattern": check["pattern"],
        "match": (m.group(0) or "")[:MATCH_MAX_CHARS],
    }


def lint_reply(text: str, checks: list) -> list:
    """Детерминированная проверка ответа. ban — по всему тексту,
    ban_code — только по fenced-блокам (с языковым тегом). Ответы,
    начинающиеся с «ОТКАЗ», не линтятся: отказ обязан называть запрещённое."""
    if (text or "").lstrip().startswith(REFUSAL_PREFIX):
        return []
    hits = []
    blocks = None
    for check in checks or []:
        rx = check.get("regex")
        if rx is None or check.get("broken"):
            continue
        if check["kind"] == "ban":
            m = rx.search(text)
            if m:
                hits.append(_hit(check, m))
        elif check["kind"] == "ban_code":
            if blocks is None:
                blocks = _FENCE_RE.findall(text)
            for block in blocks:
                m = rx.search(block)
                if m:
                    hits.append(_hit(check, m))
                    break
    return hits


def format_violation_list(hits: list) -> str:
    return "; ".join(
        f"{CHECK_LABELS.get(h['kind'], h['kind'])} «{h['pattern']}» (совпало: «{h['match']}»)"
        for h in hits
    ) or "—"


def render_invariants_message(inv: dict) -> dict:
    return {
        "role": "system",
        "content": (
            f"ИНВАРИАНТЫ «{inv['name']}» — жёсткие правила проекта; их нельзя "
            "нарушать ни в советах, ни в коде. Учитывай в каждом ответе:\n"
            + inv["rules_text"]
            + "\n\nЕсли выполнение просьбы нарушит инвариант — откажись: начни "
            "ответ с «ОТКАЗ:», назови нарушенный инвариант и предложи ближайшую "
            "разрешённую альтернативу. Обсуждение запрещённого (вопросы «почему "
            "нельзя», сравнения подходов) нарушением не считается — отвечай "
            "нормально."
        ),
    }


def synthesized_refusal(name: str, hits: list) -> str:
    return (
        f"ОТКАЗ: ответ дважды нарушил инварианты набора «{name}» "
        f"(сработали проверки: {format_violation_list(hits)}) и был заблокирован "
        "сервером. Переформулируйте запрос в рамках инвариантов или выберите "
        "другой набор."
    )

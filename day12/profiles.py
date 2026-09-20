import hashlib
import re
from pathlib import Path

from memory import _SECTION_HEADER_RE, _split_pair

DAY12_DIR = Path(__file__).parent
PROFILES_DIR = DAY12_DIR / "profiles"

PROFILE_MAX_BULLETS = 30
PROFILE_MAX_VALUE_CHARS = 200
PROFILE_MAX_BODY = 20_000
PROFILE_MAX_STEPS = 8
PROFILE_MAX_NAME = 120
PIPELINE_SECTION = "Пайплайн"

SLUG_RE = re.compile(r"^[\w-]{1,80}$", re.UNICODE)
_TITLE_RE = re.compile(r"^#\s+(.+?)\s*#*\s*$")


def slugify(name: str) -> str:
    slug = re.sub(r"[^\w]+", "-", (name or "").strip().lower()).strip("-")
    if not slug:
        slug = "p-" + hashlib.sha1((name or "x").encode("utf-8")).hexdigest()[:10]
    return slug[:60]


def _profile_path(slug: str) -> Path:
    return PROFILES_DIR / f"{slug}.md"


def parse_profile(content: str) -> dict:
    """Секционный markdown профиля → {name, sections, pipeline}.

    `# Имя` — отображаемое имя; `## Секция` + `- ключ: значение` — предпочтения;
    `## Пайплайн` — упорядоченные шаги `- имя: инструкция`.
    """
    name = ""
    sections: dict[str, list] = {}
    pipeline: list[dict] = []
    current = None
    for raw_line in (content or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if not line.startswith("##"):
            m = _TITLE_RE.match(line)
            if m:
                name = m.group(1).strip()[:PROFILE_MAX_NAME]
                continue
        m = _SECTION_HEADER_RE.match(line)
        if m and line.startswith("##"):
            current = m.group(1).strip()
            continue
        bullet = line.lstrip("-•*").strip()
        pair = _split_pair(bullet)
        if not pair or current is None:
            continue
        pair = [pair[0][:PROFILE_MAX_VALUE_CHARS], pair[1][:PROFILE_MAX_VALUE_CHARS]]
        if current == PIPELINE_SECTION:
            if len(pipeline) < PROFILE_MAX_STEPS:
                pipeline.append({"name": pair[0], "instruction": pair[1]})
        else:
            sec = sections.setdefault(current, [])
            if len(sec) < PROFILE_MAX_BULLETS:
                sec.append(pair)
    return {"name": name, "sections": sections, "pipeline": pipeline}


def profile_prefs_text(parsed: dict) -> str:
    parts = []
    for sec, pairs in (parsed.get("sections") or {}).items():
        if pairs:
            parts.append(f"{sec}:\n" + "\n".join(f"- {k}: {v}" for k, v in pairs))
    return "\n".join(parts)


def profile_keys(parsed: dict) -> set:
    return {
        str(p[0]).strip().lower()
        for pairs in (parsed.get("sections") or {}).values()
        for p in pairs
        if isinstance(p, (list, tuple)) and p and str(p[0]).strip()
    }


def read_profile(slug: str) -> dict | None:
    """Профиль по слугу или None. Перечитывает файл с диска при каждом вызове."""
    if not slug or not SLUG_RE.match(slug):
        return None
    try:
        content = _profile_path(slug).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if not content.strip():
        return None
    parsed = parse_profile(content[: PROFILE_MAX_BODY + 1])
    return {
        "id": slug,
        "name": parsed["name"] or slug,
        "content": content,
        "sections": parsed["sections"],
        "pipeline": parsed["pipeline"],
        "prefs_text": profile_prefs_text(parsed),
    }


def list_profiles() -> list[dict]:
    out = []
    try:
        files = sorted(PROFILES_DIR.glob("*.md"))
    except OSError:
        return out
    for path in files:
        slug = path.stem
        prof = read_profile(slug)
        if prof is None:
            continue
        out.append({
            "id": slug,
            "name": prof["name"],
            "sections": prof["sections"],
            "pipeline_steps": [s["name"] for s in prof["pipeline"]],
        })
    return out


def write_profile(slug: str, content: str) -> dict:
    if not SLUG_RE.match(slug or ""):
        raise ValueError("id профиля — слэг из букв, цифр, - и _ (до 80 символов).")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Пустой профиль не сохраняется — добавьте секции.")
    if len(content) > PROFILE_MAX_BODY:
        raise ValueError(f"Файл профиля длиннее {PROFILE_MAX_BODY} символов.")
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    _profile_path(slug).write_text(content, encoding="utf-8")
    prof = read_profile(slug)
    return {"id": slug, "name": (prof or {}).get("name") or slug}


def delete_profile(slug: str) -> bool:
    if not slug or not SLUG_RE.match(slug):
        return False
    try:
        _profile_path(slug).unlink()
        return True
    except OSError:
        return False


def render_profile_message(profile: dict) -> dict:
    return {
        "role": "system",
        "content": (
            f"ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ «{profile['name']}» — предпочтения, "
            "заявленные самим пользователем; учитывай в каждом ответе:\n"
            + profile["prefs_text"]
        ),
    }

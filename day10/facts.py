from config import complete

FACTS_MAX_PAIRS = 15
FACTS_MAX_VALUE_CHARS = 200
FACTS_MAX_CHARS = 4000
FACTS_CHUNK = 12

FACTS_SYSTEM_PROMPT = (
    "Ты — редактор памяти диалога. Тебе дают текущий список фактов (если он уже был) "
    "и новые сообщения переписки. Обнови список фактов: сохрани всё ещё актуальное, "
    "дополни новыми сведениями, изменившееся переформулируй, устаревшее убери. "
    "Храни только важное: цель, ограничения, предпочтения, принятые решения, "
    "договорённости, ключевые цифры и имена. Формат ответа строгий: по одному факту "
    "на строку, каждая строка вида «Ключ: значение», без нумерации, кавычек и "
    "пояснений. Не больше 15 фактов, каждый — одна короткая фраза. "
    "Если запоминать нечего — верни пустой ответ."
)


def parse_facts(text: str) -> list[list[str]]:
    pairs: list[list[str]] = []
    for line in (text or "").splitlines():
        line = line.strip().lstrip("-•*").strip()
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if not key or not value:
            continue
        pairs.append([key, value])
        if len(pairs) >= FACTS_MAX_PAIRS:
            break
    return pairs


def cap_pairs(pairs: list[list[str]]) -> list[list[str]]:
    out: list[list[str]] = []
    total = 0
    for pair in pairs:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        key = str(pair[0]).strip()[:FACTS_MAX_VALUE_CHARS]
        value = str(pair[1]).strip()[:FACTS_MAX_VALUE_CHARS]
        if not key or not value:
            continue
        total += len(key) + len(value)
        if total > FACTS_MAX_CHARS:
            break
        out.append([key, value])
        if len(out) >= FACTS_MAX_PAIRS:
            break
    return out


def update_facts(old_facts, messages, model: str, client=None):
    blocks = []
    if old_facts:
        blocks.append("Текущие факты:\n" + facts_text(old_facts))
    lines = [
        f"{'Пользователь' if m['role'] == 'user' else 'Ассистент'}: {m['content']}"
        for m in messages
    ]
    blocks.append("Новые сообщения переписки:\n" + "\n".join(lines))
    blocks.append("Обновлённый список фактов:")
    resp = complete(
        [
            {"role": "system", "content": FACTS_SYSTEM_PROMPT},
            {"role": "user", "content": "\n\n".join(blocks)},
        ],
        model=model,
        client=client,
        temperature=0,
    )
    text = (resp.choices[0].message.content or "").strip()
    return cap_pairs(parse_facts(text)), getattr(resp, "usage", None), text


def facts_text(facts) -> str:
    return "\n".join(f"{key}: {value}" for key, value in facts)


def render_facts_message(facts) -> dict:
    content = (
        "Важные факты диалога (цель, ограничения, предпочтения, решения, "
        "договорённости). Учитывай их наравне с перепиской:\n" + facts_text(facts)
    )
    return {"role": "system", "content": content}

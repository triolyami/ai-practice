from config import complete

SUMMARY_SYSTEM_PROMPT = (
    "Ты — редактор, сжимающий историю чата. Тебе дают предыдущую сводку (если она была) "
    "и следующий фрагмент переписки. Составь обновлённую сводку: сохрани факты, имена, "
    "цифры, принятые решения, предпочтения пользователя и незакрытые вопросы, выброси "
    "вежливости и повторы. Пиши по-русски, до 150 слов, только текст сводки — без "
    "вступлений и пояснений."
)
SUMMARY_MAX_CHARS = 4000


def compress(old_summary: str | None, chunk: list[dict], model: str, client=None):
    lines = []
    if old_summary:
        lines.append(f"Предыдущая сводка диалога:\n{old_summary}")
    lines.append("Фрагмент переписки:")
    lines += [
        f"{'Пользователь' if m['role'] == 'user' else 'Ассистент'}: {m['content']}"
        for m in chunk
    ]
    lines.append("Обновлённая сводка:")
    resp = complete(
        [
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": "\n\n".join(lines)},
        ],
        model=model,
        client=client,
        temperature=0,
    )
    text = ((resp.choices[0].message.content or "").strip())[:SUMMARY_MAX_CHARS]
    return text, getattr(resp, "usage", None)


def render_rolling_message(summary: str) -> dict:
    return {
        "role": "system",
        "content": (
            "Сводка более ранней части диалога (самые свежие сообщения идут дальше "
            "по переписке):\n" + summary
        ),
    }


def render_chunks_message(chunks: list[str]) -> dict:
    body = "\n\n".join(f"Период {n}:\n{text}" for n, text in enumerate(chunks, 1))
    return {
        "role": "system",
        "content": (
            "Сжатая история более ранней части диалога по периодам (самые свежие "
            "сообщения идут дальше по переписке):\n" + body
        ),
    }

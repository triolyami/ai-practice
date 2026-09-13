import math

from config import RESPONSE_HEADROOM

CYR_CHARS_PER_TOKEN = 3.5
OTHER_CHARS_PER_TOKEN = 4.0
MESSAGE_OVERHEAD = 4


def estimate_text(text: str) -> int:
    if not text:
        return 0
    cyr = 0
    other = 0
    for ch in text:
        if "\u0400" <= ch <= "\u04FF":
            cyr += 1
        else:
            other += 1
    est = cyr / CYR_CHARS_PER_TOKEN + other / OTHER_CHARS_PER_TOKEN
    return max(1, math.ceil(est))


def breakdown(system_prompt: str, history: list[dict], request: str) -> dict:
    system = estimate_text(system_prompt or "")
    hist = sum(estimate_text(m.get("content", "")) + MESSAGE_OVERHEAD for m in history)
    req = estimate_text(request or "") + MESSAGE_OVERHEAD
    total = system + MESSAGE_OVERHEAD + hist + req
    return {"system": system, "history": hist, "request": req, "total": total}


def context_used_pct(total: int, limit: int) -> float:
    return round(total / limit * 100, 1) if limit else 0.0


def fits(total: int, limit: int) -> bool:
    return total + RESPONSE_HEADROOM <= limit


def trim_to_fit(
    system_prompt: str, history: list[dict], request: str, limit: int
) -> tuple[list[dict], int]:
    trimmed = list(history)
    turns = 0
    while trimmed:
        if fits(breakdown(system_prompt, trimmed, request)["total"], limit):
            return trimmed, turns
        trimmed = trimmed[2:]
        turns += 1
    return trimmed, turns

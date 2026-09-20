import math

CYR_CHARS_PER_TOKEN = 3.5
OTHER_CHARS_PER_TOKEN = 4.0
MESSAGE_OVERHEAD = 4


def estimate_text(text: str) -> int:
    if not text:
        return 0
    cyr = 0
    other = 0
    for ch in text:
        if "Ѐ" <= ch <= "ӿ":
            cyr += 1
        else:
            other += 1
    est = cyr / CYR_CHARS_PER_TOKEN + other / OTHER_CHARS_PER_TOKEN
    return max(1, math.ceil(est))


def breakdown(system_prompt: str, longterm: str, profile: str, history: list[dict], request: str) -> dict:
    system = estimate_text(system_prompt or "")
    lt = estimate_text(longterm or "")
    lt_overhead = MESSAGE_OVERHEAD if lt else 0
    prof = estimate_text(profile or "")
    prof_overhead = MESSAGE_OVERHEAD if prof else 0
    hist = sum(estimate_text(m.get("content", "")) + MESSAGE_OVERHEAD for m in history)
    req = estimate_text(request or "") + MESSAGE_OVERHEAD
    total = system + MESSAGE_OVERHEAD + lt + lt_overhead + prof + prof_overhead + hist + req
    return {
        "system": system,
        "longterm": lt,
        "profile": prof,
        "history": hist,
        "request": req,
        "total": total,
    }


def context_used_pct(total: int, limit: int) -> float:
    return round(total / limit * 100, 1) if limit else 0.0

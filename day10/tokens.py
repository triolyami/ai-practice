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
        if "\u0400" <= ch <= "\u04FF":
            cyr += 1
        else:
            other += 1
    est = cyr / CYR_CHARS_PER_TOKEN + other / OTHER_CHARS_PER_TOKEN
    return max(1, math.ceil(est))


def breakdown(system_prompt: str, extra: str, history: list[dict], request: str) -> dict:
    system = estimate_text(system_prompt or "")
    extra_est = estimate_text(extra or "")
    extra_overhead = MESSAGE_OVERHEAD if extra_est else 0
    hist = sum(estimate_text(m.get("content", "")) + MESSAGE_OVERHEAD for m in history)
    req = estimate_text(request or "") + MESSAGE_OVERHEAD
    total = system + MESSAGE_OVERHEAD + extra_est + extra_overhead + hist + req
    return {"system": system, "extra": extra_est, "history": hist, "request": req, "total": total}


def context_used_pct(total: int, limit: int) -> float:
    return round(total / limit * 100, 1) if limit else 0.0

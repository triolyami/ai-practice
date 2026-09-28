"""Сценарии дня 20 и проверка трассы вызовов.

Сценарий = промпт + спецификация ожиданий над meta.tool_calls:
  expect      — упорядоченные шаблоны имён «server__tool» (fnmatch, «*» ок):
                подпоследовательность реальной трассы должна их покрыть.
                Порядок — только там, где он продиктован зависимостью данных;
                независимые шаги уходят в require, иначе честный прогон
                ловил бы ложный FAIL (бит при живом прогоне: модель ставит
                remind до issue_comment — напоминанию комментарий не нужен)
  require     — шаблоны, которые должны встретиться хотя бы раз, в любом месте
  min_servers — минимум разных серверов среди успешных вызовов
  forbid      — шаблоны имён, которых в трассе быть не должно
                (дистрактор: семантически похожий, но чужой инструмент)

check(trace, spec) — чистая функция, без сети и процессов: её же гоняет
offline_check на синтетических трассах и flow_run на живых.
"""
import fnmatch

SCENARIOS = {
    "cross-server": {
        "title": "исследование → задача → напоминание (свободный промпт)",
        # Свободная формулировка: модель сама выбирает серверы и порядок.
        "prompt": (
            "В локальном корпусе документов есть материалы про композицию "
            "MCP-инструментов. Найди их поиском по корпусу, сожми найденное "
            "в короткий дайджест, заведи в трекере задачу «Изучить композицию "
            "MCP» с высоким приоритетом, добавь полученный дайджест "
            "комментарием к этой задаче и поставь напоминание вернуться к "
            "ней через час. В конце ответь коротко, что сделано."
        ),
        "expect": [
            "pipeline__search",
            "pipeline__summarize",
            "tracker__issue_create",
            "tracker__issue_comment",
        ],
        "require": ["scheduler__remind"],
        "min_servers": 3,
        # дистрактор: заметки py-tools семантически близки к задаче/дайджесту,
        # но сценарию не нужны — вызов = ошибка выбора
        "forbid": ["py-tools__notes_add", "py-tools__notes_list"],
    },
    "cross-server-explicit": {
        "title": "та же цепочка, но рецептом (контрольная дорожка)",
        # Порядок продиктован — проверяет исполнение, а не выбор.
        "prompt": (
            "Вызови инструменты строго в этом порядке: "
            "1) pipeline__search с запросом «композиция MCP»; "
            "2) pipeline__summarize по найденному тексту, не переписывая его; "
            "3) tracker__issue_create с заголовком «Изучить композицию MCP» "
            "и приоритетом high; "
            "4) tracker__issue_comment к созданной задаче с текстом дайджеста; "
            "5) scheduler__remind «Вернуться к задаче по композиции MCP» "
            "через 60 минут. Затем ответь коротко, что сделано."
        ),
        # та же шкала: даже в рецепте remind не обязан ждать комментарий
        "expect": [
            "pipeline__search",
            "pipeline__summarize",
            "tracker__issue_create",
            "tracker__issue_comment",
        ],
        "require": ["scheduler__remind"],
        "min_servers": 3,
        "forbid": ["py-tools__notes_add", "py-tools__notes_list"],
    },
}


def _match(pattern: str, name: str) -> bool:
    return fnmatch.fnmatchcase(name, pattern)


def check(trace: list[dict], spec: dict) -> dict:
    """Вердикт по трассе meta.tool_calls. Каждый критерий — {name, ok, detail}."""
    criteria = []

    # порядок: шаблоны expect должны идти подпоследовательностью трассы
    pos = 0
    matched = []
    missing = None
    for pat in spec["expect"]:
        hit = next((i for i in range(pos, len(trace))
                    if _match(pat, trace[i].get("name", ""))), None)
        if hit is None:
            missing = pat
            break
        matched.append(trace[hit]["name"])
        pos = hit + 1
    if missing is None:
        criteria.append({"name": "order", "ok": True,
                         "detail": " → ".join(matched)})
    else:
        criteria.append({"name": "order", "ok": False,
                         "detail": f"не найден шаг «{missing}»; совпало: "
                                   + (" → ".join(matched) or "ничего")})

    # покрытие серверов: считаем только успешные вызовы
    servers = sorted({c.get("server") for c in trace if c.get("ok") and c.get("server")})
    ok = len(servers) >= spec["min_servers"]
    criteria.append({"name": "servers", "ok": ok,
                     "detail": f"{len(servers)} из {spec['min_servers']} нужных: "
                               + (", ".join(servers) or "нет")})

    # присутствие: каждый require-шаблон должен встретиться хоть раз
    for pat in spec.get("require", []):
        found = any(_match(pat, c.get("name", "")) for c in trace)
        criteria.append({"name": f"require:{pat}", "ok": found,
                         "detail": "вызван" if found else "не вызван ни разу"})

    # дистракторы: ни одного вызова по запрещённым шаблонам
    bad = [c["name"] for c in trace
           if any(_match(p, c.get("name", "")) for p in spec["forbid"])]
    criteria.append({"name": "no_distractors", "ok": not bad,
                     "detail": "дистракторы не тронуты" if not bad
                               else f"вызваны: {', '.join(bad)}"})

    # чистота: ни одного упавшего вызова
    failed = [c["name"] for c in trace if not c.get("ok")]
    criteria.append({"name": "no_errors", "ok": not failed,
                     "detail": "все вызовы успешны" if not failed
                               else f"ошибки: {', '.join(failed)}"})

    # фиделити хопов — информативно (не влияет на ok): модель могла
    # легально положить дайджест в description, где флаг не применим
    hops = [c["hop_exact"] for c in trace if c.get("hop_exact") is not None]
    return {
        "ok": all(c["ok"] for c in criteria),
        "criteria": criteria,
        "calls": len(trace),
        "servers": servers,
        "hops_exact": sum(1 for h in hops if h),
        "hops_changed": sum(1 for h in hops if h is False),
    }

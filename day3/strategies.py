from config import DEFAULT_MODEL

COT_SUFFIX = "Решай пошагово."

COMPOSE_TEMPLATE = """Напиши промпт, по которому языковая модель решит задачу ниже максимально надёжно и без ошибок. Промпт должен быть универсальной инструкцией: не включай в него саму задачу и её решение. В ответ верни только текст промпта, без пояснений.

Задача, для которой нужен промпт:
{task}"""

EXPERTS_TEMPLATE = """Задачу решает группа из трёх экспертов. Аналитик разбирает условия и фиксирует факты. Инженер строит на фактах решение задачи. Критик проверяет решение инженера на ошибки и даёт окончательный вердикт. Каждый эксперт должен предложить своё решение, после чего приведи финальный ответ группы.

Задача:
{task}"""

EXPERT_ROLES = (
    ("analytik", "Ты — аналитик. Разбери условия задачи, выпиши все факты и связи между ними и реши задачу на основе этого разбора."),
    ("inzhener", "Ты — инженер. Реши задачу строго и систематично: обосновывай каждый вывод и дай чёткий финальный ответ."),
    ("kritik", "Ты — критик. Реши задачу, затем перепроверь своё решение на логические ошибки и дай окончательный ответ."),
)

SYNTH_TEMPLATE = """Три эксперта независимо решали одну и ту же задачу. Проверь их решения, найди ошибки, если они есть, и приведи финальное решение группы.

Задача:
{task}

Решение аналитика:
{analytik}

Решение инженера:
{inzhener}

Решение критика:
{kritik}"""

STRATEGIES = {
    "baseline": {"title": "Прямой ответ", "hint": "задача без дополнительных инструкций"},
    "cot": {"title": "Пошагово", "hint": "в промпт добавлена инструкция «решай пошагово»"},
    "meta": {"title": "Сначала промпт", "hint": "модель сначала пишет промпт для решения, затем решает по нему"},
    "experts": {"title": "Группа экспертов", "hint": "аналитик, инженер и критик решают в одном запросе"},
    "experts_multi": {"title": "Эксперты по очереди", "hint": "отдельный запрос каждому эксперту, затем синтез"},
    "thinking": {"title": "Нативное рассуждение", "hint": "glm-5.3 думает сам, без промпт-трюков"},
}
MAIN_ORDER = ("baseline", "cot", "meta", "experts")
EXTRA_ORDER = ("experts_multi", "thinking")


def task_block(task: str) -> str:
    return f"Задача:\n{task}"


def plan(task: str, strategy: str) -> list:
    if strategy not in STRATEGIES:
        raise ValueError(f"Неизвестный способ: {strategy}")

    if strategy == "baseline":
        return [_step("solve", DEFAULT_MODEL, lambda _: [{"role": "user", "content": task}])]

    if strategy == "cot":
        content = f"{task}\n\n{COT_SUFFIX}"
        return [_step("solve", DEFAULT_MODEL, lambda _: [{"role": "user", "content": content}])]

    if strategy == "meta":
        def solve_step(prev: dict) -> list:
            content = f"{prev['compose']}\n\n{task_block(task)}"
            return [{"role": "user", "content": content}]

        return [
            _step(
                "compose",
                DEFAULT_MODEL,
                lambda _: [{"role": "user", "content": COMPOSE_TEMPLATE.format(task=task)}],
            ),
            _step("solve", DEFAULT_MODEL, solve_step),
        ]

    if strategy == "experts":
        content = f"{EXPERTS_TEMPLATE.format(task=task)}"
        return [_step("solve", DEFAULT_MODEL, lambda _: [{"role": "user", "content": content}])]

    if strategy == "experts_multi":
        steps = [
            _step(
                name,
                DEFAULT_MODEL,
                lambda _, c=text: [{"role": "user", "content": f"{c}\n\n{task_block(task)}"}],
            )
            for name, text in EXPERT_ROLES
        ]

        def synth_step(prev: dict) -> list:
            content = SYNTH_TEMPLATE.format(task=task, **prev)
            return [{"role": "user", "content": content}]

        steps.append(_step("synthesis", DEFAULT_MODEL, synth_step))
        return steps

    return [_step("solve", "glm-5.3", lambda _: [{"role": "user", "content": task}])]


def _step(name: str, model: str, build) -> dict:
    return {"name": name, "model": model, "build": build}

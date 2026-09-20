"""Offline check of day12 personalization with a fake LLM client (no network)."""
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import profiles  # noqa: E402
from agent import Agent, DEFAULT_LAYERS  # noqa: E402
from memory import (  # noqa: E402
    LONGTERM_SECTIONS,
    cap_pairs,
    parse_extraction,
    read_longterm,
    write_longterm,
)
from profiles import (  # noqa: E402
    delete_profile,
    list_profiles,
    parse_profile,
    read_profile,
    slugify,
    write_profile,
)
from storage import ChatStore  # noqa: E402
from tokens import breakdown  # noqa: E402


class FakeUsage:
    def __init__(self, prompt, completion):
        self.prompt_tokens = prompt
        self.completion_tokens = completion


class FakeResp:
    def __init__(self, content, usage):
        self.choices = [types.SimpleNamespace(message=types.SimpleNamespace(content=content))]
        self.usage = usage


class FakeStream:
    def __init__(self, text, usage):
        chunks = [
            types.SimpleNamespace(
                choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content=t), finish_reason=None)],
                usage=None,
            )
            for t in text
        ]
        chunks.append(types.SimpleNamespace(
            choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content=None), finish_reason="stop")],
            usage=usage,
        ))
        self._chunks = chunks

    def __iter__(self):
        return iter(self._chunks)

    def close(self):
        pass


class FakeCompletions:
    """Записывает вызовы; fail_at — номер вызова (1-based), на котором create() падает."""

    def __init__(self, extractor_reply="", fail_at=None):
        self.calls = []
        self.n = 0
        self.extractor_reply = extractor_reply
        self.fail_at = fail_at

    def create(self, messages=None, stream=False, extra_body=None, **kwargs):
        self.n += 1
        self.calls.append({"messages": messages, "stream": stream})
        if self.fail_at == self.n:
            raise RuntimeError("модель упала (тест)")
        est = sum(len(str(m.get("content", ""))) for m in messages) // 4 + 5
        usage = FakeUsage(est, 7)
        if stream:
            return FakeStream(f"ОТВЕТ-{self.n}", usage)
        reply = self.extractor_reply(self.calls[-1]) if callable(self.extractor_reply) else self.extractor_reply
        return FakeResp(reply or "", FakeUsage(est, 3))


class FakeClient:
    def __init__(self, extractor_reply="", fail_at=None):
        self.chat = types.SimpleNamespace(completions=FakeCompletions(extractor_reply, fail_at))


EXTRACT_OK = (
    "ДОЛГОСРОЧНОЕ:\n"
    "Профиль | стек: Python и FastAPI\n"
    "Знания | стиль ответов: лаконичный\n"
)

PIPE_PROFILE = (
    "# Трубопровод\n"
    "## Стиль\n"
    "- тон: деловой\n"
    "## Пайплайн\n"
    "- разбор: проанализируй запрос\n"
    "- ответ: дай решение\n"
    "- проверка: проверь ответ\n"
)

PREF_PROFILE = (
    "# Краткий\n"
    "## Формат\n"
    "- формат: списком\n"
    "## Стиль\n"
    "- тон: сухой\n"
)


def make_world():
    td = tempfile.TemporaryDirectory()
    profiles_dir = Path(td.name) / "profiles"
    old_dir = profiles.PROFILES_DIR
    profiles.PROFILES_DIR = profiles_dir
    store = ChatStore(Path(td.name) / "chat.db")
    lt = Path(td.name) / "longterm.md"
    return td, store, lt, old_dir, profiles_dir


def restore_dir(old_dir):
    profiles.PROFILES_DIR = old_dir


def make_agent(store, lt, sid, extractor_reply="", fail_at=None, **kw):
    fc = FakeClient(extractor_reply, fail_at=fail_at)
    agent = Agent(name="Тест", client=fc, longterm_path=lt, **kw)
    agent.bind(sid, store)
    return agent, fc


def run_turn(agent, text):
    events = list(agent.send_stream(text))
    kinds = [e["event"] for e in events]
    assert "done" in kinds, kinds
    return events


def memories(events):
    return [e for e in events if e["event"] == "memory"]


def test_profile_store_roundtrip():
    td, _store, _lt, old, pdir = make_world()
    write_profile("lakon", PREF_PROFILE)
    write_profile("pipe", PIPE_PROFILE)
    listed = {p["id"]: p for p in list_profiles()}
    assert set(listed) == {"lakon", "pipe"}
    assert listed["lakon"]["name"] == "Краткий"
    assert listed["pipe"]["pipeline_steps"] == ["разбор", "ответ", "проверка"]

    prof = read_profile("lakon")
    assert prof["name"] == "Краткий" and "формат: списком" in prof["prefs_text"]
    assert prof["pipeline"] == []

    assert delete_profile("lakon") is True
    assert read_profile("lakon") is None
    assert delete_profile("lakon") is False
    restore_dir(old)
    td.cleanup()


def test_profile_parse_caps():
    td, _s, _l, old, _pd = make_world()
    many = "## Секция\n" + "".join(f"- k{i}: v{i}\n" for i in range(40))
    parsed = parse_profile(many)
    assert len(parsed["sections"]["Секция"]) == 30
    long_step = "## Пайплайн\n" + "".join(f"- s{i}: do {i}\n" for i in range(12))
    parsed = parse_profile(long_step)
    assert len(parsed["pipeline"]) == 8
    assert slugify("Код-ревьюер!") == "код-ревьюер"
    assert slugify("") .startswith("p-")
    restore_dir(old)
    td.cleanup()


def test_profile_injection_and_toggle():
    td, store, lt, old, _pd = make_world()
    write_profile("lakon", PREF_PROFILE)
    write_longterm(lt, {"Профиль": [["имя", "Толя"]]})
    agent, _fc = make_agent(store, lt, "s1")
    agent.configure(profile="lakon")
    agent.history = [{"role": "user", "content": "старое"}, {"role": "assistant", "content": "ответ"}]

    messages, lt_text, prof_text, tail = agent._request("ПРОВЕРКА", profile=agent._active_profile())
    assert prof_text and lt_text and len(tail) == 2
    assert any("ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ «Краткий»" in m["content"] for m in messages)
    assert any("ДОЛГОСРОЧНАЯ ПАМЯТЬ" in m["content"] for m in messages)
    # профиль идёт после персоны, до долговременной
    roles = [m["content"][:30] for m in messages]
    assert "ПРОФИЛЬ" in roles[1] and "ДОЛГОСРОЧНАЯ" in roles[2]

    agent.layers["profile"] = False
    messages, _lt, prof_text, _t = agent._request("ПРОВЕРКА", profile=None)
    assert prof_text == "" and not any("ПРОФИЛЬ" in m["content"] for m in messages)
    agent.layers["profile"] = True
    td.cleanup()
    restore_dir(old)


def test_missing_profile_degrades():
    td, store, lt, old, _pd = make_world()
    agent, _fc = make_agent(store, lt, "s1", extractor_reply="ДОЛГОСРОЧНОЕ:")
    agent.configure(profile="несуществующий")
    events = run_turn(agent, "привет")
    meta = next(e for e in events if e["event"] == "done")["meta"]
    assert meta["profile_missing"] is True and meta["profile_id"] == "несуществующий"
    assert meta["pipeline"] == []
    td.cleanup()
    restore_dir(old)


def test_pipeline_order_and_commit():
    td, store, lt, old, _pd = make_world()
    write_profile("pipe", PIPE_PROFILE)
    agent, fc = make_agent(store, lt, "p1", extractor_reply="ДОЛГОСРОЧНОЕ:")
    agent.configure(profile="pipe")
    events = run_turn(agent, "сделай фичу")

    starts = [e for e in events if e["event"] == "step_start"]
    assert [s["name"] for s in starts] == ["разбор", "ответ", "проверка"]
    assert [s["step"] for s in starts] == [0, 1, 2]
    step_deltas = [e for e in events if e["event"] == "delta" and e.get("step") is not None]
    assert step_deltas and all(0 <= e["step"] <= 2 for e in step_deltas)

    done = next(e for e in events if e["event"] == "done")
    assert done["meta"]["pipeline"] == ["разбор", "ответ", "проверка"]
    assert done["content"] == "ОТВЕТ-3"  # финальный ответ — вывод последнего шага
    # в истории ровно одна пара user+assistant
    assert [m["role"] for m in agent.history] == ["user", "assistant"]
    assert agent.history[-1]["content"] == "ОТВЕТ-3"

    calls = [c for c in fc.chat.completions.calls if c["stream"]]
    assert len(calls) == 3
    for i, call in enumerate(calls):
        assert any(f"ШАГ {i + 1}/3" in m["content"] for m in call["messages"])
        assert any("ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ" in m["content"] for m in call["messages"])
    # шаг 2 видит вывод шага 1, шаг 3 — обоих; история диалога только на шаге 1
    assert "Результат шага «разбор»" not in calls[0]["messages"][-1]["content"]
    assert "Результат шага «разбор»" in calls[1]["messages"][-1]["content"]
    assert "Результат шага «ответ»" in calls[2]["messages"][-1]["content"]
    td.cleanup()
    restore_dir(old)


def test_pipeline_rollback():
    td, store, lt, old, _pd = make_world()
    write_profile("pipe", PIPE_PROFILE)
    agent, fc = make_agent(store, lt, "p1", fail_at=2)  # шаг 2 из 3 падает
    agent.configure(profile="pipe")
    events = list(agent.send_stream("сделай фичу"))
    kinds = [e["event"] for e in events]
    assert "error" in kinds and "done" not in kinds
    assert agent.history == []  # середина пайплайна упала — ход не записан
    # экстрактор не запускался (нет done — нет memory-вызова)
    assert all(c["stream"] for c in fc.chat.completions.calls)
    td.cleanup()
    restore_dir(old)


def test_extraction_and_covered():
    td, store, lt, old, _pd = make_world()
    agent, fc = make_agent(store, lt, "a1", extractor_reply=EXTRACT_OK)
    events = run_turn(agent, "я пишу на Python и FastAPI")

    mem = memories(events)
    assert len(mem) == 1 and mem[0]["covered"] == 2
    assert agent.covered == 2

    data = read_longterm(lt)
    assert data["sections"]["Профиль"] == [["стек", "Python и FastAPI"]]
    assert data["sections"]["Знания"] == [["стиль ответов", "лаконичный"]]
    assert len(mem[0]["longterm_added"]) == 2

    call = fc.chat.completions.calls[-1]
    assert not call["stream"]
    assert "редактор" in call["messages"][0]["content"]

    # covered едет в снапшот и обратно
    store.save("a1", agent.snapshot())
    snap = store.load("a1")
    assert snap["covered"] == 2 and snap["profile_id"] == ""
    td.cleanup()
    restore_dir(old)


def test_extractor_dedup_vs_profile():
    td, store, lt, old, _pd = make_world()
    write_profile("lakon", PREF_PROFILE)
    leaky = (
        "ДОЛГОСРОЧНОЕ:\n"
        "Профиль | формат: списком\n"  # уже заявлено в профиле — отбрасывается
        "Профиль | ТОН: сухой\n"      # тот же ключ другим регистром — тоже
        "Знания | город: Москва\n"
    )
    agent, fc = make_agent(store, lt, "a1", extractor_reply=leaky)
    agent.configure(profile="lakon")
    events = run_turn(agent, "отвечай списком, я из Москвы")
    mem = memories(events)[0]
    data = read_longterm(lt)
    assert data["sections"]["Знания"] == [["город", "Москва"]]
    assert data["sections"]["Профиль"] == []
    assert [a[1] for a in mem["longterm_added"]] == ["город"]

    # экстрактор видел текст профиля в промпте
    call = fc.chat.completions.calls[-1]
    assert "заявлено" in call["messages"][1]["content"] and "формат: списком" in call["messages"][1]["content"]
    td.cleanup()
    restore_dir(old)


def test_extractor_failure_and_retry():
    td, store, lt, old, _pd = make_world()
    agent, fc = make_agent(store, lt, "a1", extractor_reply="сплошной мусор без секций")
    events = run_turn(agent, "сообщение раз")
    assert any(e["event"] == "notice" for e in events)
    assert agent.covered == 0  # неудача — ход не засчитан, догоним позже
    assert agent.totals["memory_calls"]["requests"] == 0

    fc.chat.completions.extractor_reply = EXTRACT_OK
    events = run_turn(agent, "сообщение два")
    mem = memories(events)
    assert len(mem) == 1 and mem[0]["covered"] == 4  # бэклог 4 сообщ. < чанка 12 — догнал одним вызовом
    assert agent.totals["memory_calls"]["requests"] == 1
    td.cleanup()
    restore_dir(old)


def test_restart_roundtrip():
    td, store, lt, old, _pd = make_world()
    write_profile("lakon", PREF_PROFILE)
    agent, _fc = make_agent(store, lt, "a1", extractor_reply=EXTRACT_OK, layers={"short": False})
    agent.configure(profile="lakon")
    run_turn(agent, "сообщение")
    store.save("a1", agent.snapshot())

    snap = store.load("a1")
    assert snap["profile_id"] == "lakon" and snap["layers"]["short"] is False
    back = Agent.from_snapshot(snap, client=FakeClient(), store=store, longterm_path=lt)
    back.bind("a1", store)
    assert back.profile_id == "lakon" and back.layers["short"] is False
    assert len(back.history) == 2 and back.covered == 2
    td.cleanup()
    restore_dir(old)


def test_snapshot_tolerates_junk():
    bad = Agent.from_snapshot({
        "name": "Битый",
        "layers": {"short": "да", "profile": 1, "longterm": False, "extra": True},
        "profile_id": 42,
        "covered": -3,
        "history": [
            {"role": "user", "content": "привет"},
            {"role": "system", "content": "мусор"},
            "строка",
        ],
        "totals": {"chat": {"requests": 2}, "memory_calls": "x"},
    })
    assert bad.layers == {"short": True, "profile": True, "longterm": False}
    assert bad.profile_id == "" and bad.covered == 0
    assert len(bad.history) == 1
    assert bad.totals["chat"]["requests"] == 2 and bad.totals["memory_calls"]["requests"] == 0


def test_memory_parsing():
    parsed = parse_extraction(
        "пролог мусорный\n"
        "ДОЛГОСРОЧНОЕ:\n"
        "Профиль:\n- стек: Python\n"
        "Решения | база: SQLite\n"
        "свободная: строка\n"
    )
    assert parsed["longterm"]["Профиль"] == [["стек", "Python"]]
    # «ключ: значение» без «Секция |» продолжает текущую секцию
    assert parsed["longterm"]["Решения"] == [["база", "SQLite"], ["свободная", "строка"]]

    assert parse_extraction("нет вообще заголовков, просто текст") is None
    assert parse_extraction("") == {"longterm": {}}
    assert parse_extraction("ДОЛГОСРОЧНОЕ:") == {"longterm": {}}

    capped = cap_pairs([["k" * 300, "v" * 300]] * 3)
    assert all(len(k) <= 200 and len(v) <= 200 for k, v in capped)

    est = breakdown("система", "долгосрочная", "профиль", [], "запрос")
    assert est["longterm"] > 0 and est["profile"] > 0


def test_longterm_file_tolerance():
    td, _store, lt, old, _pd = make_world()
    lt.write_text("## Профиль\n- имя: Толя\nпросто текст без ключа\n## Чужое\n- x: y\n", encoding="utf-8")
    data = read_longterm(lt)
    assert data["sections"]["Профиль"] == [["имя", "Толя"]]
    assert data["sections"]["Чужое"] == [["x", "y"]]  # неизвестные секции сохраняются
    assert data["has_content"] is True

    missing = read_longterm(Path(td.name) / "нет.md")
    assert missing["content"] == "" and missing["has_content"] is False
    assert list(missing["sections"]) == list(LONGTERM_SECTIONS)
    td.cleanup()
    restore_dir(old)


def main():
    test_profile_store_roundtrip()
    test_profile_parse_caps()
    test_profile_injection_and_toggle()
    test_missing_profile_degrades()
    test_pipeline_order_and_commit()
    test_pipeline_rollback()
    test_extraction_and_covered()
    test_extractor_dedup_vs_profile()
    test_extractor_failure_and_retry()
    test_restart_roundtrip()
    test_snapshot_tolerates_junk()
    test_memory_parsing()
    test_longterm_file_tolerance()
    print("OK: все офлайн-проверки персонализации дня 12 прошли")


if __name__ == "__main__":
    main()

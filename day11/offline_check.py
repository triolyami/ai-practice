"""Offline check of day11 memory layers with a fake LLM client (no network)."""
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent import Agent, DEFAULT_LAYERS  # noqa: E402
from memory import (  # noqa: E402
    LONGTERM_SECTIONS,
    cap_pairs,
    normalize_working,
    parse_memory,
    read_longterm,
    working_text,
    write_longterm,
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
    def __init__(self, extractor_reply=""):
        self.calls = []
        self.n = 0
        self.extractor_reply = extractor_reply

    def create(self, messages=None, stream=False, extra_body=None, **kwargs):
        self.n += 1
        self.calls.append({"messages": messages, "stream": stream})
        est = sum(len(str(m.get("content", ""))) for m in messages) // 4 + 5
        usage = FakeUsage(est, 7)
        if stream:
            return FakeStream(f"ОТВЕТ-{self.n}", usage)
        reply = self.extractor_reply(self.calls[-1]) if callable(self.extractor_reply) else self.extractor_reply
        return FakeResp(reply or "", FakeUsage(est, 3))


class FakeClient:
    def __init__(self, extractor_reply=""):
        self.chat = types.SimpleNamespace(completions=FakeCompletions(extractor_reply))


EXTRACT_OK = (
    "ЦЕЛЬ: запустить сайт кофейни\n"
    "ПЛАН:\n"
    "- собрать ТЗ\n"
    "- сверстать\n"
    "ФАКТЫ:\n"
    "дедлайн: конец месяца\n"
    "бюджет: 300 тыс\n"
    "ДОЛГОСРОЧНОЕ:\n"
    "Профиль | стек: Python и FastAPI\n"
    "Знания | стиль ответов: лаконичный\n"
)


def make_world():
    td = tempfile.TemporaryDirectory()
    store = ChatStore(Path(td.name) / "chat.db")
    lt = Path(td.name) / "longterm.md"
    return td, store, lt


def make_agent(store, lt, sid, extractor_reply="", **kw):
    fc = FakeClient(extractor_reply)
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


def ws_state(store, wsid):
    row = store.load_workspace(wsid)
    return (row or {}).get("state"), (row or {}).get("covered") or {}


def test_extraction_lands():
    td, store, lt = make_world()
    agent, fc = make_agent(store, lt, "a1", extractor_reply=EXTRACT_OK)
    events = run_turn(agent, "задача: сайт кофейни, я пишу на Python")

    mem = memories(events)
    assert len(mem) == 1 and mem[0]["covered"] == 2, mem
    state, covered = ws_state(store, "a1")  # приватная область = session_id
    assert state["goal"] == "запустить сайт кофейни"
    assert state["plan"] == ["собрать ТЗ", "сверстать"]
    assert ["дедлайн", "конец месяца"] in state["facts"]
    assert covered == {"a1": 2}

    data = read_longterm(lt)
    assert data["sections"]["Профиль"] == [["стек", "Python и FastAPI"]]
    assert data["sections"]["Знания"] == [["стиль ответов", "лаконичный"]]
    assert len(mem[0]["longterm_added"]) == 2

    call = fc.chat.completions.calls[-1]
    assert not call["stream"]
    assert "редактор памяти" in call["messages"][0]["content"]
    assert "сайт кофейни" in call["messages"][1]["content"]

    meta = next(e for e in events if e["event"] == "done")["meta"]
    assert meta["layers"] == DEFAULT_LAYERS and meta["totals"]["chat"]["requests"] == 1
    assert mem[0]["totals"]["memory_calls"]["requests"] == 1
    td.cleanup()


def test_layers_toggle():
    td, store, lt = make_world()
    write_longterm(lt, {"Профиль": [["имя", "Толя"]]})
    store.save_workspace("w1", "Общее", {"goal": "g", "plan": [], "facts": [["k", "v"]]}, {})
    fc = FakeClient()
    agent = Agent(client=fc, layers={"working": True, "longterm": True}, longterm_path=lt)
    agent.bind("s9", store)
    agent.workspace_id = "w1"
    agent.history = [{"role": "user", "content": "старое"}, {"role": "assistant", "content": "ответ"}]

    messages, lt_text, wk_text, tail = agent._request("ПРОВЕРКА")
    assert lt_text and wk_text and len(tail) == 2
    assert any("ДОЛГОСРОЧНАЯ ПАМЯТЬ" in m["content"] for m in messages)
    assert any("РАБОЧАЯ ПАМЯТЬ" in m["content"] for m in messages)

    agent.layers = {"short": False, "working": False, "longterm": True}
    messages, lt_text, wk_text, tail = agent._request("ПРОВЕРКА")
    assert tail == [] and wk_text == "" and lt_text
    assert not any(m["role"] != "system" and m["content"] != "ПРОВЕРКА" for m in messages[1:-1])

    agent.layers = {"short": True, "working": False, "longterm": False}
    messages, lt_text, wk_text, tail = agent._request("ПРОВЕРКА")
    assert lt_text == "" and wk_text == "" and len(tail) == 2

    est = breakdown(agent.system_prompt, lt_text, wk_text, tail, "x")
    assert est["longterm"] == 0 and est["working"] == 0 and est["history"] > 0
    td.cleanup()


def test_shared_workspace():
    td, store, lt = make_world()
    a, _fca = make_agent(store, lt, "a1", extractor_reply=EXTRACT_OK)
    a.configure(workspace="Проект")
    assert a.workspace_id == "ws-проект"
    run_turn(a, "первое сообщение о задаче")
    state, covered = ws_state(store, "ws-проект")
    assert state["goal"] == "запустить сайт кофейни"
    assert covered == {"a1": 2}

    b, _fcb = make_agent(store, lt, "b1", extractor_reply="")
    b.configure(workspace="проект")  # регистр не важен — слаг тот же
    assert b.workspace_id == a.workspace_id
    state, covered = ws_state(store, "ws-проект")
    assert covered["b1"] == 0  # при входе в область история считается непокрытой

    messages, _lt, wk_text, _tail = b._request("что по задаче?")
    assert "дедлайн: конец месяца" in wk_text
    assert any("РАБОЧАЯ ПАМЯТЬ" in m["content"] for m in messages)

    run_turn(b, "сообщение из второго чата")
    _state, covered = ws_state(store, "ws-проект")
    assert covered["b1"] == 2 and covered["a1"] == 2

    # чат в другой области рабочей памяти не видит
    c, _fcc = make_agent(store, lt, "c1", extractor_reply="")
    _m, _l, wk_text_c, _t = c._request("привет")
    assert wk_text_c == ""
    td.cleanup()


def test_extractor_failure_and_retry():
    td, store, lt = make_world()
    agent, fc = make_agent(store, lt, "a1", extractor_reply="сплошной мусор без секций")
    events = run_turn(agent, "сообщение раз")
    assert any(e["event"] == "notice" for e in events)
    _state, covered = ws_state(store, "a1")
    assert covered.get("a1", 0) == 0  # состояние не тронуто, ход не засчитан
    assert agent.totals["memory_calls"]["requests"] == 0  # неудача не оплачена

    fc.chat.completions.extractor_reply = EXTRACT_OK
    events = run_turn(agent, "сообщение два")
    mem = memories(events)
    assert len(mem) == 1 and mem[0]["covered"] == 4  # бэклог 4 сообщ. < чанка 12 — догнал одним вызовом
    state, covered = ws_state(store, "a1")
    assert covered["a1"] == 4 and state["goal"] == "запустить сайт кофейни"
    assert agent.totals["memory_calls"]["requests"] == 1
    td.cleanup()


def test_promote_and_reset():
    td, store, lt = make_world()
    agent, _fc = make_agent(store, lt, "a1")
    agent.configure(workspace="Задача")
    store.save_workspace(agent.workspace_id, "Задача", {"goal": "", "plan": [], "facts": [["дедлайн", "пятница"]]}, {"a1": 2})

    assert agent.promote("дедлайн") is True
    state, _covered = ws_state(store, agent.workspace_id)
    assert state["facts"] == []
    data = read_longterm(lt)
    assert data["sections"]["Знания"] == [["дедлайн", "пятница"]]
    assert agent.promote("нет такого") is False

    agent.history = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]
    agent.reset()
    assert agent.history == [] and agent.totals["chat"]["requests"] == 0
    _state, covered = ws_state(store, agent.workspace_id)
    assert "a1" not in covered  # сброс чистит только запись этого чата
    data = read_longterm(lt)
    assert data["sections"]["Знания"] == [["дедлайн", "пятница"]]  # долговременная жива
    td.cleanup()


def test_restart_roundtrip():
    td, store, lt = make_world()
    agent, _fc = make_agent(store, lt, "a1", extractor_reply=EXTRACT_OK, layers={"short": False})
    agent.configure(workspace="Проект")
    run_turn(agent, "сообщение")
    store.save("a1", agent.snapshot())

    snap = store.load("a1")
    assert snap["workspace_id"] == "ws-проект" and snap["layers"]["short"] is False
    back = Agent.from_snapshot(snap, client=FakeClient(), store=store, longterm_path=lt)
    back.bind("a1", store)
    assert back.workspace_id == "ws-проект" and back.layers["short"] is False
    assert len(back.history) == 2
    state, covered = ws_state(store, "ws-проект")
    assert state["goal"] == "запустить сайт кофейни" and covered["a1"] == 2
    td.cleanup()


def test_workspace_delete():
    td, store, lt = make_world()
    agent, _fc = make_agent(store, lt, "a1", extractor_reply=EXTRACT_OK)
    agent.configure(workspace="Проект")
    run_turn(agent, "сообщение")
    store.save("a1", agent.snapshot())
    sids = store.delete_workspace("ws-проект")
    assert sids == ["a1"]
    assert store.load_workspace("ws-проект") is None
    snap = store.load("a1")
    assert snap["workspace_id"] == "a1"  # чат вернулся к личной области
    td.cleanup()


def test_snapshot_tolerates_junk():
    bad = Agent.from_snapshot({
        "name": "Битый",
        "layers": {"short": "да", "working": 1, "longterm": False, "extra": True},
        "workspace_id": 42,
        "history": [
            {"role": "user", "content": "привет"},
            {"role": "system", "content": "мусор"},
            "строка",
        ],
        "totals": {"chat": {"requests": 2}, "memory_calls": "x"},
    })
    assert bad.layers == {"short": True, "working": True, "longterm": False}
    assert bad.workspace_id == ""
    assert len(bad.history) == 1
    assert bad.totals["chat"]["requests"] == 2 and bad.totals["memory_calls"]["requests"] == 0

    assert normalize_working({"goal": 5, "plan": "не список", "facts": [42, ["к"], ["а", "б"]]}) == {
        "goal": "", "plan": [], "facts": [["а", "б"]],
    }
    assert working_text({"goal": "", "plan": [], "facts": []}) == ""


def test_memory_parsing():
    parsed = parse_memory(
        "пролог мусорный\n"
        "ЦЕЛЬ: собрать ТЗ\n"
        "ПЛАН:\n"
        "- шаг один\n* шаг два\n"
        "ФАКТЫ:\n"
        "- ключ: значение\n• бюджет: 3 млн\nбез двоеточия\n: пустой ключ\n"
        "ДОЛГОСРОЧНОЕ:\n"
        "Профиль:\n- стек: Python\n"
        "Решения | база: SQLite\n"
        "свободная: строка\n"
    )
    assert parsed["goal"] == "собрать ТЗ"
    assert parsed["plan"] == ["шаг один", "шаг два"]
    assert parsed["facts"] == [["ключ", "значение"], ["бюджет", "3 млн"]]
    assert parsed["longterm"]["Профиль"] == [["стек", "Python"]]
    assert parsed["longterm"]["Решения"] == [["база", "SQLite"], ["свободная", "строка"]]

    assert parse_memory("нет вообще заголовков, просто текст") is None
    assert parse_memory("") == {"goal": "", "plan": [], "facts": [], "longterm": {}}
    # строчное ключевое слово с текстом — это данные, а не заголовок
    p2 = parse_memory("ФАКТЫ:\nцель: запустить сайт\n")
    assert p2["facts"] == [["цель", "запустить сайт"]] and p2["goal"] == ""

    capped = cap_pairs([["k" * 300, "v" * 300]] * 3)
    assert all(len(k) <= 200 and len(v) <= 200 for k, v in capped)

    est = breakdown("система", "долгосрочная", "рабочая", [], "запрос")
    assert est["longterm"] > 0 and est["working"] > 0


def test_longterm_file_tolerance():
    td, _store, lt = make_world()
    lt.write_text("## Профиль\n- имя: Толя\nпросто текст без ключа\n## Чужое\n- x: y\n", encoding="utf-8")
    data = read_longterm(lt)
    assert data["sections"]["Профиль"] == [["имя", "Толя"]]
    assert data["sections"]["Чужое"] == [["x", "y"]]  # неизвестные секции сохраняются
    assert data["has_content"] is True

    missing = read_longterm(Path(td.name) / "нет.md")
    assert missing["content"] == "" and missing["has_content"] is False
    assert list(missing["sections"]) == list(LONGTERM_SECTIONS)
    td.cleanup()


def main():
    test_extraction_lands()
    test_layers_toggle()
    test_shared_workspace()
    test_extractor_failure_and_retry()
    test_promote_and_reset()
    test_restart_roundtrip()
    test_workspace_delete()
    test_snapshot_tolerates_junk()
    test_memory_parsing()
    test_longterm_file_tolerance()
    print("OK: все офлайн-проверки слоёв памяти дня 11 прошли")


if __name__ == "__main__":
    main()

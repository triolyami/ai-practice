"""Offline check of day10 context strategies with a fake LLM client (no network)."""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent import _clamp_window, Agent  # noqa: E402
from facts import cap_pairs, parse_facts  # noqa: E402
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
    def __init__(self):
        self.calls = []
        self.n = 0
        self.facts_reply = None

    def create(self, messages=None, stream=False, extra_body=None, **kwargs):
        self.n += 1
        self.calls.append({"messages": messages, "stream": stream})
        est = sum(len(str(m.get("content", ""))) for m in messages) // 4 + 5
        usage = FakeUsage(est, 7)
        if stream:
            return FakeStream(f"ОТВЕТ-{self.n}", usage)
        if self.facts_reply is not None:
            return FakeResp(self.facts_reply, usage)
        return FakeResp(f"цель: собрать ТЗ v{self.n}\nбюджет: {self.n} млн", usage)


class FakeClient:
    def __init__(self):
        self.chat = types.SimpleNamespace(completions=FakeCompletions())


def run_turn(agent, text):
    events = list(agent.send_stream(text))
    kinds = [e["event"] for e in events]
    assert "done" in kinds, kinds
    return events


def dones(events):
    return next(e for e in events if e["event"] == "done")


def facts_of(events):
    return [e for e in events if e["event"] == "facts"]


def test_window():
    fc = FakeClient()
    a = Agent(name="Тест", client=fc, strategy="window", window_size=4)
    for i in range(1, 6):
        events = run_turn(a, f"вопрос {i}")
        assert facts_of(events) == []
    assert len(a.history) == 10
    messages, extra, tail, outside = a._request("ПРОВЕРКА")
    assert len(messages) == 1 + 4 + 1, messages
    assert [m["content"] for m in tail] == [m["content"] for m in a.history[-4:]]
    assert outside == 6 and extra == ""

    meta = dones(events)["meta"]
    assert meta["strategy"] == "window" and meta["outside"] == 4  # на момент запроса было 8 сообщений
    assert meta["tokens"]["extra"] == 0 and meta["tokens"]["history"] > 0
    assert meta["totals"]["window"]["requests"] == 5
    assert meta["totals"]["facts_calls"]["requests"] == 0
    assert meta["totals"]["facts"]["requests"] == 0
    assert meta["totals"]["branches"]["requests"] == 0

    pv = a.context_preview()
    assert pv["strategy"] == "window" and pv["outside"] == 6 and pv["verbatim"] == 4
    assert pv["extra"] == 0 and pv["history"] > 0

    assert _clamp_window(999) == 50 and _clamp_window(1) == 2 and _clamp_window("x") == 10
    for bad in ({"window_size": 51}, {"window_size": 1}, {"strategy": "magic"}):
        try:
            a.configure(**bad)
            raise AssertionError(f"ожидали ValueError на {bad}")
        except ValueError:
            pass


def test_facts():
    fc = FakeClient()
    b = Agent(name="Факт", client=fc, strategy="facts", window_size=4)

    events = run_turn(b, "задача: ТЗ")
    got = facts_of(events)
    assert len(got) == 1 and got[0]["covered"] == 2, got
    assert got[0]["facts"]["pairs"] == [["цель", "собрать ТЗ v2"], ["бюджет", "2 млн"]]
    call = fc.chat.completions.calls[-1]
    assert not call["stream"]
    assert call["messages"][0]["content"].startswith("Ты — редактор памяти")
    assert "задача: ТЗ" in call["messages"][1]["content"]
    assert "Текущие факты:" not in call["messages"][1]["content"]
    meta = dones(events)["meta"]
    assert meta["strategy"] == "facts"
    assert meta["totals"]["facts_calls"]["requests"] == 0  # снимок до обновления фактов
    assert got[0]["totals"]["facts_calls"]["requests"] == 1

    events = run_turn(b, "бюджет 3 млн")
    got = facts_of(events)
    assert len(got) == 1 and got[0]["covered"] == 4
    call = fc.chat.completions.calls[-1]
    assert "Текущие факты:" in call["messages"][1]["content"]
    assert "цель: собрать ТЗ v2" in call["messages"][1]["content"]
    assert dones(events)["meta"]["outside"] == 2  # на момент ответа покрыто 2 сообщения

    messages, extra, tail, outside = b._request("ПРОВЕРКА")
    assert messages[1]["role"] == "system" and "Важные факты диалога" in messages[1]["content"]
    assert len(messages) == 2 + 4 + 1
    assert ":" in extra and outside == 4 and len(tail) == 4
    pv = b.context_preview()
    assert pv["extra"] > 0 and pv["outside"] == 4 and pv["verbatim"] == 4

    fc.chat.completions.facts_reply = "тут нет ключей и значений"
    events = run_turn(b, "ещё вопрос")
    assert any(e["event"] == "notice" for e in events)
    assert b.facts_state["covered"] == 4  # состояние не тронуто
    assert b.totals["facts_calls"]["requests"] == 2  # неудачный вызов не оплачен

    fc.chat.completions.facts_reply = None
    events = run_turn(b, "ещё вопрос")
    assert b.facts_state["covered"] == 8  # ретрай догнал накопившийся хвост одним вызовом
    assert b.totals["facts_calls"]["requests"] == 3

    fc.chat.completions.facts_reply = ""
    events = run_turn(b, "пусто")
    got = facts_of(events)
    assert len(got) == 1 and got[0]["count"] == 0
    assert b.facts_state["facts"] == []
    messages, extra, _tail, _outside = b._request("ПРОВЕРКА")
    assert len(messages) == 1 + 4 + 1 and extra == ""  # фактов нет — блока в запросе нет

    snap = b.snapshot()
    b2 = Agent.from_snapshot(snap, client=FakeClient())
    assert b2.facts_state == b.facts_state
    assert b2.strategy == "facts" and b2.window_size == 4
    assert b2.totals["facts_calls"] == b.totals["facts_calls"]
    assert len(b2.token_log) == len(b.token_log)
    assert b2.context_preview() == b.context_preview()

    b.reset()
    assert b.history == [] and b.facts_state == {"facts": [], "covered": 0}
    assert b.totals["facts"]["requests"] == 0 and b.totals["facts_calls"]["requests"] == 0
    assert b.token_log == []


def test_strategy_switch():
    fc = FakeClient()
    c = Agent(client=fc, strategy="window", window_size=3)
    for i in range(5):
        run_turn(c, f"q{i}")
    assert c.totals["window"]["requests"] == 5

    c.configure(strategy="facts")
    events = run_turn(c, "q5")
    got = [e["covered"] for e in facts_of(events)]
    assert got == [12], got  # бэклог 12 сообщений догнан одним вызовом (FACTS_CHUNK=12)
    messages, _extra, tail, outside = c._request("x")
    assert outside == 12 and len(tail) == 3

    c.configure(strategy="branches")
    events = run_turn(c, "q6")
    assert facts_of(events) == []
    messages, _extra, tail, outside = c._request("x")
    assert outside == 0 and len(tail) == len(c.history) == 14
    assert c.totals["branches"]["requests"] == 1


def test_branches():
    fc = FakeClient()
    d = Agent(client=fc, strategy="branches")
    for i in range(3):
        run_turn(d, f"q{i}")
    messages, extra, tail, outside = d._request("x")
    assert len(messages) == 1 + 6 + 1 and len(tail) == 6 and outside == 0 and extra == ""
    pv = d.context_preview()
    assert pv["verbatim"] == 6 and pv["outside"] == 0 and pv["extra"] == 0


def test_fork():
    fc = FakeClient()
    p = Agent(client=fc, strategy="facts", window_size=3)
    for i in range(6):
        run_turn(p, f"q{i}")
    assert p.facts_state["covered"] == 12
    spent = p.totals["facts"]["requests"]

    child = p.fork(6)
    assert len(child.history) == 6
    assert [m["content"] for m in child.history] == [m["content"] for m in p.history[:6]]
    assert child.facts_state["covered"] == 6  # pointer обрезан под укороченную историю
    assert child.strategy == "facts" and child.window_size == 3
    assert len(p.history) == 12 and p.facts_state["covered"] == 12
    assert child.totals["facts"]["requests"] == 0  # ветка считает свой расход с нуля
    assert p.totals["facts"]["requests"] == spent

    child.parent_id = "sess-parent"
    child.fork_len = 6
    back = Agent.from_snapshot(child.snapshot(), client=FakeClient())
    assert back.parent_id == "sess-parent" and back.fork_len == 6

    junk = Agent.from_snapshot({"name": "x", "fork_len": "6", "parent_id": 42})
    assert junk.fork_len is None and junk.parent_id is None

    events = run_turn(child, "продолжаем")
    assert dones(events)["meta"]["turns"] == 4


def test_snapshot_tolerates_junk():
    bad = Agent.from_snapshot({
        "name": "Битый",
        "strategy": "magic",
        "window_size": "чуть",
        "facts_state": {"facts": [42, ["только ключ"], ["а", "б"], "мусор"], "covered": "x"},
        "history": [
            {"role": "user", "content": "привет"},
            {"role": "assistant", "content": "ответ"},
            {"role": "system", "content": "мусор"},
        ],
    })
    assert bad.strategy == "window" and bad.window_size == 10
    assert bad.facts_state["facts"] == [["а", "б"]]
    assert bad.facts_state["covered"] == 0
    assert len(bad.history) == 2


def test_facts_parsing():
    text = "\n".join(
        ["- цель: ТЗ", "• бюджет: 3 млн", "без двоеточия", ": пустой ключ", "ключ: ", ""]
        + [f"факт{n}: значение{n}" for n in range(20)]
    )
    pairs = parse_facts(text)
    assert pairs[0] == ["цель", "ТЗ"] and pairs[1] == ["бюджет", "3 млн"]
    assert "без двоеточия" not in str(pairs)
    assert len(pairs) == 15  # FACTS_MAX_PAIRS

    long = [["k" * 300, "v" * 300]] * 3
    capped = cap_pairs(long)
    assert all(len(k) <= 200 and len(v) <= 200 for k, v in capped)

    assert breakdown("система", "ключ: значение", [], "запрос")["extra"] > 0
    assert breakdown("система", None, [], "запрос")["extra"] == 0


def main():
    test_window()
    test_facts()
    test_strategy_switch()
    test_branches()
    test_fork()
    test_snapshot_tolerates_junk()
    test_facts_parsing()
    print("OK: все офлайн-проверки стратегий дня 10 прошли")


if __name__ == "__main__":
    main()

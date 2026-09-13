"""Offline check of day9 compression logic with a fake LLM client (no network)."""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent import RECENT_KEEP, SUMMARY_EVERY, Agent  # noqa: E402

SUMMARY_MARK = "СЖАТО"


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

    def create(self, messages=None, stream=False, extra_body=None, **kwargs):
        self.n += 1
        self.calls.append({"messages": messages, "stream": stream})
        text = f"{SUMMARY_MARK}-{self.n}"
        est = sum(len(str(m.get("content", ""))) for m in messages) // 4 + 5
        usage = FakeUsage(est, 7)
        if stream:
            return FakeStream(text, usage)
        return FakeResp(text, usage)


class FakeClient:
    def __init__(self):
        self.chat = types.SimpleNamespace(completions=FakeCompletions())


def run_turn(agent, text):
    events = list(agent.send_stream(text))
    kinds = [e["event"] for e in events]
    assert "done" in kinds, kinds
    return events


def summaries_of(events):
    return [e for e in events if e["event"] == "summary"]


def main():
    fc = FakeClient()
    agent = Agent(name="Тест", client=fc, compression="rolling")

    for i in range(1, 10):
        assert summaries_of(run_turn(agent, f"вопрос {i}")) == []
    # ход 10: history=20 -> 20-0-10=10 >= 10 -> первая компрессия
    first = summaries_of(run_turn(agent, "вопрос 10"))
    assert len(first) == 1 and first[0]["covered"] == SUMMARY_EVERY, first
    assert agent.comp_state["rolling"]["covered"] == 10
    call = fc.chat.completions.calls[-1]
    assert call["messages"][0]["content"].startswith("Ты — редактор")
    assert "вопрос 1" in call["messages"][1]["content"]

    # запрос хода 11: system + сводка + хвост 10 + user
    messages, _summary, tail, covered = agent._request("ПРОВЕРКА")
    assert covered == 10 and len(tail) == 10
    assert messages[1]["role"] == "system" and "Сводка более ранней части" in messages[1]["content"]
    assert len(messages) == 2 + 10 + 1

    for i in range(11, 15):
        assert summaries_of(run_turn(agent, f"вопрос {i}")) == []
    # ход 15: history=30 -> 30-10-10=10 >= 10 -> вторая компрессия со слиянием
    events = run_turn(agent, "вопрос 15")
    second = summaries_of(events)
    assert len(second) == 1 and second[0]["covered"] == 20, second
    merge_call = next(
        c for c in reversed(fc.chat.completions.calls)
        if not c["stream"] and "Предыдущая сводка диалога:" in c["messages"][1]["content"]
    )
    assert f"{SUMMARY_MARK}-1" in merge_call["messages"][1]["content"]

    # метаданные хода: mode, tokens.summary, бакеты totals
    meta = next(e for e in events if e["event"] == "done")["meta"]
    assert meta["mode"] == "rolling" and meta["summarized"] == 10
    assert meta["tokens"]["summary"] > 0 and meta["tokens"]["history"] > 0
    assert meta["totals"]["rolling"]["requests"] == 15
    assert meta["totals"]["summary_calls"]["requests"] == 1  # снимок на момент ответа
    assert second[0]["totals"]["summary_calls"]["requests"] == 2  # уже после сжатия
    assert meta["totals"]["off"]["requests"] == 0
    assert meta["totals"]["rolling"]["cost_usd"] > 0
    assert agent.totals["summary_calls"]["requests"] == 2

    # превью: сжатые + дословные покрывают всю историю, хвост >= RECENT_KEEP
    pv = agent.context_preview()
    assert pv["summarized"] + pv["verbatim"] == len(agent.history)
    assert pv["verbatim"] >= RECENT_KEEP and pv["summary"] > 0
    assert pv["summarized"] == 20

    # off: в запросе нет сводки, идёт полная история
    agent.configure(compression="off")
    messages, _summary, tail, covered = agent._request("ПРОВЕРКА")
    assert covered == 0 and len(tail) == len(agent.history)
    assert len(messages) == 1 + len(agent.history) + 1
    events = run_turn(agent, "вопрос 16")
    assert summaries_of(events) == []
    assert agent.totals["off"]["requests"] == 1
    assert agent.comp_state["rolling"]["covered"] == 20  # в off не сжимает

    # переключение на chunks: догоняет бэклог чанками по 10
    agent.configure(compression="chunks")
    events = run_turn(agent, "вопрос 17")
    # history=34: covered 0->10->20, хвост 14
    got = [s["covered"] for s in summaries_of(events)]
    assert got == [10, 20], got
    assert len(agent.comp_state["chunks"]["chunks"]) == 2
    pv = agent.context_preview()
    assert pv["summarized"] == 20 and pv["verbatim"] == len(agent.history) - 20
    messages, _summary, _tail, _covered = agent._request("ПРОВЕРКА")
    assert "по периодам" in messages[1]["content"] and "Период 2" in messages[1]["content"]

    # снапшот -> восстановление
    snap = agent.snapshot()
    agent2 = Agent.from_snapshot(snap, client=FakeClient())
    assert agent2.comp_state == agent.comp_state, (agent2.comp_state, agent.comp_state)
    assert agent2.totals["summary_calls"] == agent.totals["summary_calls"]
    assert len(agent2.token_log) == len(agent.token_log)
    assert agent2.context_preview() == agent.context_preview()
    messages2, _s, _t, covered2 = agent2._request("запрос")
    assert covered2 == 20 and messages2[1]["role"] == "system"

    # повреждённый снапшот не роняет загрузку
    bad = Agent.from_snapshot({
        "name": "Битый", "compression": "chunks",
        "comp_state": {"rolling": {"summary": 42, "covered": "x"}, "chunks": {"chunks": [1, "ок"], "covered": 999}},
        "history": [
            {"role": "user", "content": "привет"},
            {"role": "assistant", "content": "ответ"},
            {"role": "system", "content": "мусор"},
        ],
    })
    assert bad.comp_state["chunks"]["chunks"] == ["ок"]
    assert bad.comp_state["chunks"]["covered"] == 0  # clamp: len-RECENT_KEEP < 0 -> 0
    assert bad.comp_state["rolling"]["summary"] is None
    assert bad.totals["rolling"]["requests"] == 0

    # сброс очищает всё
    agent.reset()
    assert agent.history == [] and agent.comp_state["rolling"]["summary"] is None
    assert agent.totals["rolling"]["requests"] == 0

    print("OK: все офлайн-проверки сжатия прошли")


if __name__ == "__main__":
    main()

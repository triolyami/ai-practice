"""Offline check of day17: stripped agent + tool loop + MCP hub, fake clients, no network."""
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent import Agent  # noqa: E402
from mcp import Client  # noqa: E402
from mcp_hub import MCPHub, make_client  # noqa: E402
from server import parse_config  # noqa: E402
from storage import ChatStore  # noqa: E402
from tokens import breakdown  # noqa: E402
from tools_server import app as tools_app  # noqa: E402


class FakeUsage:
    def __init__(self, prompt, completion):
        self.prompt_tokens = prompt
        self.completion_tokens = completion


class FakeStream:
    """reply: str | {"text": str|None, "tool_calls": [{id,name,arguments}]}"""

    def __init__(self, reply, usage):
        chunks = []
        finish = "stop"
        if isinstance(reply, dict):
            for i, tc in enumerate(reply.get("tool_calls") or []):
                args = tc.get("arguments", "")
                half = max(1, len(args) // 2)
                for j, frag in enumerate((args[:half], args[half:])):
                    chunks.append(types.SimpleNamespace(
                        choices=[types.SimpleNamespace(
                            delta=types.SimpleNamespace(
                                content=None,
                                tool_calls=[types.SimpleNamespace(
                                    index=i,
                                    id=tc.get("id") if j == 0 else None,
                                    function=types.SimpleNamespace(
                                        name=tc.get("name") if j == 0 else None,
                                        arguments=frag,
                                    ),
                                )],
                            ),
                            finish_reason=None,
                        )],
                        usage=None,
                    ))
            if reply.get("tool_calls"):
                finish = "tool_calls"
            text = reply.get("text") or ""
        else:
            text = reply
        chunks += [
            types.SimpleNamespace(
                choices=[types.SimpleNamespace(
                    delta=types.SimpleNamespace(content=t, tool_calls=None),
                    finish_reason=None,
                )],
                usage=None,
            )
            for t in text
        ]
        chunks.append(types.SimpleNamespace(
            choices=[types.SimpleNamespace(
                delta=types.SimpleNamespace(content=None, tool_calls=None),
                finish_reason=finish,
            )],
            usage=usage,
        ))
        self._chunks = chunks

    def __iter__(self):
        return iter(self._chunks)

    def close(self):
        pass


class FakeCompletions:
    """Записывает вызовы; replies — список ответов по порядку (stream-вызовы)."""

    def __init__(self, replies=None, fail_at=None):
        self.calls = []
        self.n = 0
        self.replies = list(replies) if replies else []
        self.fail_at = fail_at

    def create(self, messages=None, stream=False, extra_body=None, **kwargs):
        self.n += 1
        self.calls.append({"messages": [dict(m) for m in messages], "stream": stream, "params": kwargs})
        if self.fail_at == self.n:
            raise RuntimeError("модель упала (тест)")
        est = sum(len(str(m.get("content", ""))) for m in messages) // 4 + 5
        usage = FakeUsage(est, 7)
        if stream:
            reply = self.replies.pop(0) if self.replies else f"ОТВЕТ-{self.n}"
            return FakeStream(reply, usage)
        raise AssertionError("день 17 всегда стримит")


class FakeClient:
    def __init__(self, replies=None, fail_at=None):
        self.chat = types.SimpleNamespace(completions=FakeCompletions(replies, fail_at))


def make_agent(store, sid, replies=None, fail_at=None, **kw):
    fc = FakeClient(replies, fail_at=fail_at)
    agent = Agent(name="Тест", client=fc, **kw)
    agent.bind(sid, store)
    return agent, fc


def run_turn(agent, text):
    events = list(agent.send_stream(text))
    kinds = [e["event"] for e in events]
    assert "done" in kinds, kinds
    return events


def done_meta(events):
    return next(e for e in events if e["event"] == "done")["meta"]


def test_request_composition():
    with tempfile.TemporaryDirectory() as td:
        store = ChatStore(Path(td) / "chat.db")
        agent, fc = make_agent(store, "s1")
        agent.history = [{"role": "user", "content": "старое"}, {"role": "assistant", "content": "ответ"}]
        run_turn(agent, "ПРОВЕРКА")

        msgs = fc.chat.completions.calls[-1]["messages"]
        # состав дня 16: system-промпт + вся история + новый user — и ничего больше
        assert msgs[0]["role"] == "system" and "Тест" in msgs[0]["content"]
        assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
        assert msgs[-2]["content"] == "ответ" and msgs[-1] == {"role": "user", "content": "ПРОВЕРКА"}


def test_meta_and_totals():
    with tempfile.TemporaryDirectory() as td:
        store = ChatStore(Path(td) / "chat.db")
        agent, _fc = make_agent(store, "s1", replies=["первый", "второй"])
        meta = done_meta(run_turn(agent, "раз"))
        assert meta["prompt_tokens"] and meta["completion_tokens"] == 7
        assert meta["cost_usd"] is not None and meta["latency_ms"] is not None
        assert "invariant" not in meta and "violations" not in meta
        assert "invariants" not in meta["tokens"]
        assert meta["turns"] == 1 and meta["totals"]["chat"]["requests"] == 1

        meta2 = done_meta(run_turn(agent, "два"))
        assert meta2["turns"] == 2
        assert agent.totals["chat"]["requests"] == 2
        assert len(agent.token_log) == 2
        assert "invariants_est" not in agent.token_log[-1]


def test_layers_off_drops_history():
    with tempfile.TemporaryDirectory() as td:
        store = ChatStore(Path(td) / "chat.db")
        agent, fc = make_agent(store, "s1", layers={"short": False})
        agent.history = [{"role": "user", "content": "старое"}, {"role": "assistant", "content": "ответ"}]
        run_turn(agent, "ПРОВЕРКА")
        msgs = fc.chat.completions.calls[-1]["messages"]
        assert [m["role"] for m in msgs] == ["system", "user"]


def test_error_event_on_model_failure():
    with tempfile.TemporaryDirectory() as td:
        store = ChatStore(Path(td) / "chat.db")
        agent, _fc = make_agent(store, "s1", fail_at=1)
        events = list(agent.send_stream("привет"))
        assert [e["event"] for e in events] == ["error"]
        assert agent.history == [] and agent.totals["chat"]["requests"] == 0


def test_snapshot_roundtrip():
    with tempfile.TemporaryDirectory() as td:
        store = ChatStore(Path(td) / "chat.db")
        agent, _fc = make_agent(store, "s1", layers={"short": False})
        run_turn(agent, "сообщение")
        store.save("s1", agent.snapshot())

        snap = store.load("s1")
        assert "invariant_id" not in snap and "enforce" not in snap
        back = Agent.from_snapshot(snap, client=FakeClient(), store=store)
        back.bind("s1", store)
        assert back.layers["short"] is False and len(back.history) == 2
        assert back.totals["chat"]["requests"] == 1


def test_snapshot_tolerates_junk():
    bad = Agent.from_snapshot({
        "name": "Битый",
        "layers": {"short": "да", "extra": True},
        "invariant_id": 42,          # старые поля из баз дня 14 — игнорируются
        "enforce": "жёсткий",
        "history": [
            {"role": "user", "content": "привет"},
            {"role": "system", "content": "мусор"},
            "строка",
        ],
        "totals": {"chat": {"requests": 2}},
    })
    assert bad.layers == {"short": True}
    assert len(bad.history) == 1
    assert bad.totals["chat"]["requests"] == 2


def test_breakdown_shape():
    est = breakdown("система", [{"role": "user", "content": "х"}, {"role": "assistant", "content": "у"}], "запрос")
    assert set(est) == {"system", "history", "request", "total"}
    assert est["system"] > 0 and est["history"] > 0 and est["request"] > 0
    assert est["total"] >= est["system"] + est["history"] + est["request"]
    prev = Agent(name="Тест", client=FakeClient())
    assert "invariants" not in prev.context_preview()


def test_parse_config_legacy_hints():
    for legacy in ("profile", "invariant", "enforce"):
        out, err = parse_config({legacy: "x"})
        assert out is None and legacy in err, legacy
    out, err = parse_config({"name": "А", "model": "glm-4.6", "layers": {"short": False}})
    assert err is None and out == {"name": "А", "model": "glm-4.6", "layers": {"short": False}}
    out, err = parse_config({"model": "нет-такой"})
    assert out is None and "Неизвестная модель" in err


def _tool_spec(name):
    return {"type": "function", "function": {"name": name, "parameters": {"type": "object"}}}


TOOLS = [_tool_spec("tracker__issue_list"), _tool_spec("py-tools__add")]


def _tool_reply(name, arguments, id="call_1"):
    return {"tool_calls": [{"id": id, "name": name, "arguments": arguments}]}


def test_tool_call_two_hop():
    """tool_calls → tool_call/tool_result события → tool-сообщения → ответ."""
    with tempfile.TemporaryDirectory() as td:
        store = ChatStore(Path(td) / "chat.db")
        seen = []

        def fake_runtime(name, args):
            seen.append((name, args))
            return "Задачи (2): #3, #5", False

        agent, fc = make_agent(
            store, "s1",
            replies=[_tool_reply("tracker__issue_list", '{"status": "open"}'), "открытые: #3 и #5"],
            tools=TOOLS, tool_call=fake_runtime,
        )
        events = run_turn(agent, "какие задачи открыты?")
        kinds = [e["event"] for e in events]
        assert kinds == ["tool_call", "tool_result", "delta"] + \
            ["delta"] * (len("открытые: #3 и #5") - 1) + ["done"], kinds
        assert seen == [("tracker__issue_list", {"status": "open"})]

        second = fc.chat.completions.calls[1]
        assert second["params"].get("tools") == TOOLS
        msgs = second["messages"]
        assert msgs[-2]["role"] == "assistant"
        assert msgs[-2]["tool_calls"][0]["function"]["name"] == "tracker__issue_list"
        assert msgs[-2]["tool_calls"][0]["id"] == "call_1"
        assert msgs[-1] == {
            "role": "tool", "tool_call_id": "call_1", "content": "Задачи (2): #3, #5",
        }

        meta = done_meta(events)
        trace = meta["tool_calls"]
        assert len(trace) == 1
        assert trace[0]["name"] == "tracker__issue_list"
        assert trace[0]["server"] == "tracker" and trace[0]["tool"] == "issue_list"
        assert trace[0]["arguments"] == {"status": "open"}
        assert trace[0]["ok"] is True and "Задачи" in trace[0]["preview"]
        assert meta["tool_rounds"] == 1
        # usage суммируется по двум хопам, не только по последнему
        def _est(call):
            return sum(len(str(m.get("content", ""))) for m in call["messages"]) // 4 + 5
        assert meta["prompt_tokens"] == sum(_est(c) for c in fc.chat.completions.calls)
        assert meta["totals"]["chat"]["requests"] == 2

        # в сохранённой истории только user/assistant; трасса — в meta
        assert [m["role"] for m in agent.history] == ["user", "assistant"]
        assert agent.history[-1]["meta"]["tool_calls"] == trace
        store.save("s1", agent.snapshot())
        snap = store.load("s1")
        assert [m["role"] for m in snap["history"]] == ["user", "assistant"]
        assert snap["history"][-1]["meta"]["tool_calls"][0]["name"] == "tracker__issue_list"
        fc2 = FakeClient()
        back = Agent.from_snapshot(snap, client=fc2, store=store,
                                   tools=TOOLS, tool_call=fake_runtime)
        assert back.history[-1]["meta"]["tool_calls"][0]["ok"] is True
        # следующий запрос — чистый user/assistant, без tool-ролей
        run_turn(back, "и что дальше?")
        roles = [m["role"] for m in fc2.chat.completions.calls[-1]["messages"]]
        assert set(roles) <= {"system", "user", "assistant"}, roles


def test_tool_error_is_data():
    """is_error / битый JSON / исключение в рантайме → tool-сообщение с «Ошибка:»."""
    with tempfile.TemporaryDirectory() as td:
        store = ChatStore(Path(td) / "chat.db")

        def flaky(name, args):
            if name == "tracker__issue_list":
                return "Error executing tool: API 404", True
            raise RuntimeError("сервер умер")

        agent, fc = make_agent(
            store, "s1",
            replies=[
                {"tool_calls": [
                    {"id": "c1", "name": "tracker__issue_list", "arguments": "{битый"},
                    {"id": "c2", "name": "py-tools__add", "arguments": '{"a":1,"b":2}'},
                ]},
                "понял, отвечаю без инструментов",
            ],
            tools=TOOLS, tool_call=flaky,
        )
        events = run_turn(agent, "проверь")
        kinds = [e["event"] for e in events]
        assert kinds.count("tool_call") == 2 and kinds.count("tool_result") == 2
        results = [e for e in events if e["event"] == "tool_result"]
        assert all(not r["ok"] for r in results)
        msgs = fc.chat.completions.calls[1]["messages"]
        tool_msgs = [m for m in msgs if m["role"] == "tool"]
        assert len(tool_msgs) == 2
        assert "невалидный JSON" in tool_msgs[0]["content"]
        assert "сервер умер" in tool_msgs[1]["content"]
        meta = done_meta(events)
        assert [t["ok"] for t in meta["tool_calls"]] == [False, False]


def test_tool_loop_cap():
    """Вечные tool_calls: после MAX_TOOL_ROUNDS — финальный хоп без tools."""
    from agent import MAX_TOOL_ROUNDS
    with tempfile.TemporaryDirectory() as td:
        store = ChatStore(Path(td) / "chat.db")
        replies = [_tool_reply("py-tools__add", '{"a":1,"b":1}', id=f"c{i}")
                   for i in range(MAX_TOOL_ROUNDS)]
        replies.append("стоп-ответ")
        agent, fc = make_agent(store, "s1", replies=replies,
                               tools=TOOLS, tool_call=lambda n, a: ("2", False))
        events = run_turn(agent, "считай вечно")
        assert done_meta(events)["tool_rounds"] == MAX_TOOL_ROUNDS
        calls = fc.chat.completions.calls
        assert len(calls) == MAX_TOOL_ROUNDS + 1
        assert all(c["params"].get("tools") == TOOLS for c in calls[:-1])
        assert "tools" not in calls[-1]["params"]
        assert [e["event"] for e in events].count("tool_call") == MAX_TOOL_ROUNDS


def test_tools_disabled_single_hop():
    with tempfile.TemporaryDirectory() as td:
        store = ChatStore(Path(td) / "chat.db")
        agent, fc = make_agent(store, "s1", replies=["просто ответ"],
                               tools=TOOLS, tool_call=lambda n, a: ("x", False),
                               tools_enabled=False)
        meta = done_meta(run_turn(agent, "вопрос"))
        assert "tool_calls" not in meta
        assert len(fc.chat.completions.calls) == 1
        assert "tools" not in fc.chat.completions.calls[0]["params"]


def test_tools_enabled_flag_roundtrip():
    with tempfile.TemporaryDirectory() as td:
        store = ChatStore(Path(td) / "chat.db")
        agent, _fc = make_agent(store, "s1")
        assert agent.tools_enabled is True
        agent.configure(tools_enabled=False)
        assert agent.tools_enabled is False
        store.save("s1", agent.snapshot())
        snap = store.load("s1")
        assert snap["tools_enabled"] is False
        back = Agent.from_snapshot(snap, client=FakeClient())
        assert back.tools_enabled is False
        # старые снапшоты без ключа → включено
        assert Agent.from_snapshot({"name": "x"}, client=FakeClient()).tools_enabled is True


def test_parse_config_tools():
    out, err = parse_config({"tools": False})
    assert err is None and out == {"tools": False}
    out, err = parse_config({"tools": "да"})
    assert out is None and "tools" in err


def test_mcp_hub_inprocess():
    """Хаб через in-process Client(MCPServer): без подпроцессов, сети и node."""
    def factory(spec):
        if spec["transport"] == "inprocess":
            return Client(tools_app)
        return make_client(spec)  # «telepathy» упадёт с ValueError → строка error

    hub = MCPHub(
        registry=[
            {"id": "py-inproc", "transport": "inprocess"},
            {"id": "broken", "transport": "telepathy"},
        ],
        client_factory=factory,
    )
    rows = hub.start(timeout=15)
    by_id = {r["id"]: r for r in rows}

    ok = by_id["py-inproc"]
    assert ok["status"] == "ok" and ok["protocol_version"]
    assert ok["server_info"] == {"name": "py-tools", "version": "0.1.0"}
    names = [t["name"] for t in ok["tools"]]
    assert names == ["server_time", "add", "echo", "notes_list", "notes_add"]
    assert all(t["description"] and "input_schema" in t for t in ok["tools"])

    bad = by_id["broken"]
    assert bad["status"] == "error" and "транспорт" in bad["error"]

    res = hub.call_tool("py-inproc", "add", {"a": 2, "b": 3})
    assert res["is_error"] is False and res["content"][0]["text"] == "5.0"
    assert res["structured_content"] == {"result": 5.0}
    res = hub.call_tool("py-inproc", "notes_add", {"text": "проверка"})
    assert res["is_error"] is False
    res = hub.call_tool("py-inproc", "notes_list", {})
    assert res["is_error"] is False and "проверка" in res["content"][0]["text"]

    # ошибка инструмента — is_error в ответе, сервер и хаб остаются живы
    res = hub.call_tool("py-inproc", "add", {"a": "не-число"})
    assert res["is_error"] is True and res["content"]
    assert hub.servers()[0]["status"] == "ok"

    # неизвестные server/tool — исключения для маппинга в 404/400 в server.py
    try:
        hub.call_tool("нет-такого", "add", {})
        raise AssertionError("нужен KeyError")
    except KeyError:
        pass
    try:
        hub.call_tool("py-inproc", "нет-такого", {})
        raise AssertionError("нужен LookupError")
    except LookupError:
        pass
    # у сломанной записи список инструментов пуст — LookupError раньше проверки статуса
    try:
        hub.call_tool("broken", "add", {"a": 1, "b": 2})
        raise AssertionError("нужен LookupError")
    except LookupError:
        pass
    assert hub.tools("нет-такого") is None
    assert [t["name"] for t in hub.tools("py-inproc")] == names


def main():
    test_request_composition()
    test_meta_and_totals()
    test_layers_off_drops_history()
    test_error_event_on_model_failure()
    test_snapshot_roundtrip()
    test_snapshot_tolerates_junk()
    test_breakdown_shape()
    test_parse_config_legacy_hints()
    test_tool_call_two_hop()
    test_tool_error_is_data()
    test_tool_loop_cap()
    test_tools_disabled_single_hop()
    test_tools_enabled_flag_roundtrip()
    test_parse_config_tools()
    test_mcp_hub_inprocess()
    print("OK: все офлайн-проверки дня 17 прошли")


if __name__ == "__main__":
    main()

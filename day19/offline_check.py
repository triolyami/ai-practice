"""Offline check of day19: agent + tool loop + MCP hub + pipeline, fake clients, no network."""
import hashlib
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import server  # noqa: E402
from agent import Agent  # noqa: E402
from mcp import Client  # noqa: E402
from mcp_hub import MCPHub, make_client  # noqa: E402
from server import parse_config  # noqa: E402
from storage import ChatStore  # noqa: E402
from tokens import breakdown  # noqa: E402
import pipeline_server  # noqa: E402
from pipeline_server import app as pipeline_app  # noqa: E402


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
        raise AssertionError("день 18 всегда стримит")


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


TOOLS = [_tool_spec("pipeline__search"), _tool_spec("pipeline__save_to_file")]


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
            replies=[_tool_reply("pipeline__search", '{"query": "mcp"}'), "открытые: #3 и #5"],
            tools=TOOLS, tool_call=fake_runtime,
        )
        events = run_turn(agent, "какие задачи открыты?")
        kinds = [e["event"] for e in events]
        assert kinds == ["tool_call", "tool_result", "delta"] + \
            ["delta"] * (len("открытые: #3 и #5") - 1) + ["done"], kinds
        assert seen == [("pipeline__search", {"query": "mcp"})]

        second = fc.chat.completions.calls[1]
        assert second["params"].get("tools") == TOOLS
        msgs = second["messages"]
        assert msgs[-2]["role"] == "assistant"
        assert msgs[-2]["tool_calls"][0]["function"]["name"] == "pipeline__search"
        assert msgs[-2]["tool_calls"][0]["id"] == "call_1"
        assert msgs[-1] == {
            "role": "tool", "tool_call_id": "call_1", "content": "Задачи (2): #3, #5",
        }

        meta = done_meta(events)
        trace = meta["tool_calls"]
        assert len(trace) == 1
        assert trace[0]["name"] == "pipeline__search"
        assert trace[0]["server"] == "pipeline" and trace[0]["tool"] == "search"
        assert trace[0]["arguments"] == {"query": "mcp"}
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
        assert snap["history"][-1]["meta"]["tool_calls"][0]["name"] == "pipeline__search"
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
            if name == "pipeline__search":
                return "Error executing tool: API 404", True
            raise RuntimeError("сервер умер")

        agent, fc = make_agent(
            store, "s1",
            replies=[
                {"tool_calls": [
                    {"id": "c1", "name": "pipeline__search", "arguments": "{битый"},
                    {"id": "c2", "name": "pipeline__save_to_file", "arguments": '{"name":"x","text":"y"}'},
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
        replies = [_tool_reply("pipeline__search", '{"query":"x"}', id=f"c{i}")
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
    """Хаб через in-process Client(MCPServer): без подпроцессов и сети."""
    def factory(spec):
        if spec["transport"] == "inprocess":
            return Client(pipeline_app)
        return make_client(spec)  # «telepathy» упадёт с ValueError → строка error

    hub = MCPHub(
        registry=[
            {"id": "pipe-inproc", "transport": "inprocess"},
            {"id": "broken", "transport": "telepathy"},
        ],
        client_factory=factory,
    )
    rows = hub.start(timeout=15)
    by_id = {r["id"]: r for r in rows}

    ok = by_id["pipe-inproc"]
    assert ok["status"] == "ok" and ok["protocol_version"]
    assert ok["server_info"] == {"name": "pipeline", "version": "0.1.0"}
    names = [t["name"] for t in ok["tools"]]
    assert names == ["search", "summarize", "save_to_file", "run_pipeline"]
    assert all(t["description"] and "input_schema" in t for t in ok["tools"])

    bad = by_id["broken"]
    assert bad["status"] == "error" and "транспорт" in bad["error"]

    res = hub.call_tool("pipe-inproc", "search", {"query": "композиция MCP"})
    assert res["is_error"] is False and "mcp_protocol.txt" in res["content"][0]["text"]

    # ошибка инструмента — is_error в ответе, сервер и хаб остаются живы
    res = hub.call_tool("pipe-inproc", "search", {})
    assert res["is_error"] is True and res["content"]
    assert hub.servers()[0]["status"] == "ok"

    # неизвестные server/tool — исключения для маппинга в 404/400 в server.py
    try:
        hub.call_tool("нет-такого", "search", {})
        raise AssertionError("нужен KeyError")
    except KeyError:
        pass
    try:
        hub.call_tool("pipe-inproc", "нет-такого", {})
        raise AssertionError("нужен LookupError")
    except LookupError:
        pass
    # у сломанной записи список инструментов пуст — LookupError раньше проверки статуса
    try:
        hub.call_tool("broken", "search", {"query": "x"})
        raise AssertionError("нужен LookupError")
    except LookupError:
        pass
    assert hub.tools("нет-такого") is None
    assert [t["name"] for t in hub.tools("pipe-inproc")] == names


def test_pipeline_tools_inprocess():
    """Инструменты pipeline через in-process хаб: search бьётся по корпусу,
    save_to_file санитизирует имя, run_pipeline — один вызов без хопов."""
    def factory(spec):
        if spec["transport"] == "inprocess":
            return Client(pipeline_app)
        return make_client(spec)

    with tempfile.TemporaryDirectory() as td:
        # out/ уводим в tmp — не мусорим в рабочем каталоге; summarize — в
        # экстрактивный режим, чтобы проверка не ходила в сеть за ключом из .env
        real_out = pipeline_server.OUT_DIR
        real_client = pipeline_server._client
        pipeline_server.OUT_DIR = Path(td) / "out"
        pipeline_server._client = False
        try:
            hub = MCPHub(
                registry=[{"id": "pipeline", "transport": "inprocess"}],
                client_factory=factory,
            )
            rows = hub.start(timeout=15)
            assert rows[0]["status"] == "ok"
            names = [t["name"] for t in rows[0]["tools"]]
            assert names == ["search", "summarize", "save_to_file", "run_pipeline"], names

            res = hub.call_tool("pipeline", "search", {"query": "композиция MCP"})
            assert res["is_error"] is False
            found = res["content"][0]["text"]
            assert "mcp_protocol.txt" in found and "MCP" in found
            res = hub.call_tool("pipeline", "search", {"query": "неттакоговзапросе"})
            assert "ничего не найдено" in res["content"][0]["text"]

            res = hub.call_tool("pipeline", "save_to_file",
                                {"name": "../../etc/evil", "text": "x"})
            path = res["content"][0]["text"]
            assert "evil.txt" in path and ".." not in path
            assert (Path(td) / "out" / "evil.txt").read_text() == "x"

            res = hub.call_tool("pipeline", "run_pipeline", {"query": "тулколлинг"})
            out = res["content"][0]["text"]
            assert res["is_error"] is False
            assert "этап 1" in out and "этап 2" in out and "этап 3" in out
            assert (Path(td) / "out" / "pipeline-composite.txt").exists()
        finally:
            pipeline_server.OUT_DIR = real_out
            pipeline_server._client = real_client


def test_summarize_extractive_fallback():
    """Без клиента summarize работает экстрактивно — пайплайн жив офлайн."""
    real = pipeline_server._client
    pipeline_server._client = False  # «ключа нет» — _llm_client → None
    try:
        text = "Первое предложение. Второе предложение. Третье предложение."
        digest, mode = pipeline_server._summarize(text)
        assert mode == "extractive" and digest == text
        long_text = ("Длинная фраза с деталями. " * 60).strip()
        digest, mode = pipeline_server._summarize(long_text)
        assert mode == "extractive"
        assert len(digest) <= pipeline_server.SUMMARIZE_BUDGET
        assert digest.endswith((".", "!", "?")) or " " not in digest[-10:]
    finally:
        pipeline_server._client = real


def test_iter_pipeline_exact_and_stop():
    """Кодовая дорожка: порядок этапов, дословный пайпинг, verdict exact;
    ошибка этапа 1 обрывает цепочку до stage 2."""
    calls = []

    def runtime(qualified, args):
        calls.append((qualified, dict(args)))
        if qualified == "pipeline__search":
            return "НАЙДЕНО-ТЕКСТ", False
        if qualified == "pipeline__summarize":
            return "ДАЙДЖЕСТ", False
        return "сохранено: out/x.txt (9 байт)", False

    events = list(server.iter_pipeline("тест", None, runtime))
    stages = [e for e in events if e["event"] == "stage"]
    done = events[-1]
    assert [s["tool"] for s in stages] == ["search", "summarize", "save_to_file"]
    # пайпинг дословный: вход следующего этапа == выход предыдущего
    assert stages[1]["input"]["text"] == "НАЙДЕНО-ТЕКСТ"
    assert stages[2]["input"]["text"] == "ДАЙДЖЕСТ"
    assert stages[1]["hop_exact"] is True and stages[2]["hop_exact"] is True
    assert done["ok"] is True and done["verdict"] == "exact"
    assert stages[2]["input"]["name"] == "тест"  # имя из запроса

    # имя передали явно — уходит как есть
    calls.clear()
    list(server.iter_pipeline("тест", "my-file", runtime))
    assert calls[2][1]["name"] == "my-file"

    # ошибка на этапе 1: summarize не вызывается вовсе
    def boom(qualified, args):
        if qualified == "pipeline__summarize":
            return "Ошибка: сервер умер", True
        return "ok", False

    events = list(server.iter_pipeline("тест", None, boom))
    assert [e["tool"] for e in events if e["event"] == "stage"] == ["search", "summarize"]
    done = events[-1]
    assert done["ok"] is False and done["failed_stage"] == 1 and done["tool"] == "summarize"


def test_tool_trace_hop_exact():
    """hop_exact в meta.tool_calls: вход вызова совпал/разошёлся с полным
    результатом предыдущего — по sha256, без хранения текста целиком."""
    with tempfile.TemporaryDirectory() as td:
        store = ChatStore(Path(td) / "chat.db")

        def runtime(name, args):
            if "search" in name:
                return "НАЙДЕНО-ТЕКСТ", False
            if "summarize" in name:
                return "ДАЙДЖЕСТ", False
            return "сохранено", False

        agent, _fc = make_agent(
            store, "s1",
            replies=[
                _tool_reply("pipeline__search", '{"query": "mcp"}', id="c1"),
                _tool_reply("pipeline__summarize", '{"text": "НАЙДЕНО-ТЕКСТ"}', id="c2"),
                _tool_reply("pipeline__save_to_file",
                            '{"name": "d", "text": "ДАЙДЖЕСТ"}', id="c3"),
                "готово",
            ],
            tools=[_tool_spec("pipeline__search"), _tool_spec("pipeline__summarize"),
                   _tool_spec("pipeline__save_to_file")],
            tool_call=runtime,
        )
        meta = done_meta(run_turn(agent, "собери пайплайн"))
        trace = meta["tool_calls"]
        assert [c["hop_exact"] for c in trace] == [None, True, True]
        assert trace[0]["result_len"] == len("НАЙДЕНО-ТЕКСТ")
        assert trace[0]["result_sha256"] == hashlib.sha256(
            "НАЙДЕНО-ТЕКСТ".encode("utf-8")).hexdigest()

        # модель переписала данные между хопами → differs
        agent2, _fc2 = make_agent(
            store, "s2",
            replies=[
                _tool_reply("pipeline__search", '{"query": "mcp"}', id="c1"),
                _tool_reply("pipeline__summarize", '{"text": "ПЕРЕПИСАНО"}', id="c2"),
                "готово",
            ],
            tools=[_tool_spec("pipeline__search"), _tool_spec("pipeline__summarize")],
            tool_call=runtime,
        )
        meta2 = done_meta(run_turn(agent2, "собери"))
        assert meta2["tool_calls"][1]["hop_exact"] is False
        # вызов без text-аргумента после первого — hop не применим
        agent3, _fc3 = make_agent(
            store, "s3",
            replies=[
                _tool_reply("pipeline__search", '{"query": "mcp"}', id="c1"),
                _tool_reply("pipeline__run_pipeline", '{"query": "x"}', id="c2"),
                "ок",
            ],
            tools=[_tool_spec("pipeline__search"), _tool_spec("pipeline__run_pipeline")],
            tool_call=runtime,
        )
        meta3 = done_meta(run_turn(agent3, "го"))
        assert meta3["tool_calls"][1]["hop_exact"] is None


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
    test_pipeline_tools_inprocess()
    test_summarize_extractive_fallback()
    test_iter_pipeline_exact_and_stop()
    test_tool_trace_hop_exact()
    print("OK: все офлайн-проверки дня 19 прошли")


if __name__ == "__main__":
    main()

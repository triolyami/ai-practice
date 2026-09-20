"""Offline check of day14 invariants with a fake LLM client (no network)."""
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import invariants  # noqa: E402
from agent import Agent  # noqa: E402
from invariants import (  # noqa: E402
    delete_invariant,
    lint_reply,
    list_invariants,
    parse_invariant,
    read_invariant,
    render_invariants_message,
    slugify,
    write_invariant,
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
    """Записывает вызовы; replies — список ответов по порядку (stream-вызовы)."""

    def __init__(self, replies=None, fail_at=None):
        self.calls = []
        self.n = 0
        self.replies = list(replies) if replies else []
        self.fail_at = fail_at

    def create(self, messages=None, stream=False, extra_body=None, **kwargs):
        self.n += 1
        self.calls.append({"messages": messages, "stream": stream})
        if self.fail_at == self.n:
            raise RuntimeError("модель упала (тест)")
        est = sum(len(str(m.get("content", ""))) for m in messages) // 4 + 5
        usage = FakeUsage(est, 7)
        if stream:
            reply = self.replies.pop(0) if self.replies else f"ОТВЕТ-{self.n}"
            return FakeStream(reply, usage)
        return FakeResp("", FakeUsage(est, 3))


class FakeClient:
    def __init__(self, replies=None, fail_at=None):
        self.chat = types.SimpleNamespace(completions=FakeCompletions(replies, fail_at))


MVI_SET = (
    "# Тестовый MVI\n"
    "## Стек\n"
    "- язык: только Kotlin\n"
    "- di: без Dagger\n"
    "## Проверки\n"
    "- бан-код: (?i)rxjava\n"
    "- бан: (?i)питер|спб\n"
)

BROKEN_SET = (
    "# Битый набор\n"
    "## Правила\n"
    "- правило: что-то\n"
    "## Проверки\n"
    "- бан: ([незакрытая\n"
    "- бан-код: (?i)ok_pattern\n"
    "- заметка: не проверка, игнорируется\n"
)

VIOLATING_CODE = "Вот слой на RxJava:\n```kotlin\nimport io.reactivex.RxJava\n```\n"
VIOLATING_PROSE = "Давайте добавим доставку в Питер — это просто.\n"
CLEAN = "Вот решение на корутинах:\n```kotlin\nflow { emit(x) }\n```\n"
REFUSAL = "ОТКАЗ: RxJava запрещена инвариантом «асинхронность». Предлагаю Flow.\n"


def make_world():
    td = tempfile.TemporaryDirectory()
    inv_dir = Path(td.name) / "invariants"
    old_dir = invariants.INVARIANTS_DIR
    invariants.INVARIANTS_DIR = inv_dir
    store = ChatStore(Path(td.name) / "chat.db")
    return td, store, old_dir


def restore_dir(old_dir):
    invariants.INVARIANTS_DIR = old_dir


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


def test_invariant_store_roundtrip():
    td, _store, old = make_world()
    write_invariant("mvi", MVI_SET)
    write_invariant("broken", BROKEN_SET)
    listed = {i["id"]: i for i in list_invariants()}
    assert set(listed) == {"mvi", "broken"}
    assert listed["mvi"]["name"] == "Тестовый MVI"
    assert [c["kind"] for c in listed["mvi"]["checks"]] == ["ban_code", "ban"]

    inv = read_invariant("mvi")
    assert inv["name"] == "Тестовый MVI" and "язык: только Kotlin" in inv["rules_text"]
    assert len(inv["checks"]) == 2 and all(not c["broken"] for c in inv["checks"])

    broken = read_invariant("broken")
    kinds = [(c["kind"], c["broken"]) for c in broken["checks"]]
    assert kinds == [("ban", True), ("ban_code", False)], kinds  # битый regex помечен, валидный жив
    listed = {i["id"]: i for i in list_invariants()}
    assert listed["broken"]["checks"][0]["broken"] is True

    assert delete_invariant("mvi") is True
    assert read_invariant("mvi") is None
    assert delete_invariant("mvi") is False
    restore_dir(old)
    td.cleanup()


def test_invariant_parse_caps():
    td, _s, old = make_world()
    many = "## Секция\n" + "".join(f"- k{i}: v{i}\n" for i in range(40))
    parsed = parse_invariant(many)
    assert len(parsed["sections"]["Секция"]) == 30
    many_checks = "## Проверки\n" + "".join(f"- бан: re{i}\n" for i in range(25))
    parsed = parse_invariant(many_checks)
    assert len(parsed["checks"]) == 20
    assert slugify("Мой набор!") == "мой-набор"
    assert slugify("").startswith("i-")
    restore_dir(old)
    td.cleanup()


def test_lint_scopes():
    td, _s, old = make_world()
    checks = parse_invariant(MVI_SET)["checks"]
    # бан-код: упоминание в прозе не считается
    assert lint_reply("Мы не используем RxJava — она запрещена.", checks) == []
    # бан-код: попадание внутри fenced-блока — нарушение
    hits = lint_reply(VIOLATING_CODE, checks)
    assert len(hits) == 1 and hits[0]["kind"] == "ban_code" and "rxjava" in hits[0]["match"].lower()
    # языковой тег ограждения тоже сканируется
    hits = lint_reply("```rxjava\nсниппет\n```", checks)
    assert len(hits) == 1
    # бан: сканирует весь ответ, включая прозу
    hits = lint_reply(VIOLATING_PROSE, checks)
    assert len(hits) == 1 and hits[0]["kind"] == "ban"
    # отказ освобождён от линта даже с запрещёнными словами внутри
    assert lint_reply(REFUSAL, checks) == []
    # битый regex пропускается, валидный рядом работает
    broken_checks = parse_invariant(BROKEN_SET)["checks"]
    assert lint_reply("текст с ok_pattern в коде:\n```\nok_pattern\n```", broken_checks) != []
    assert lint_reply("обычный текст", broken_checks) == []
    td.cleanup()
    restore_dir(old)


def test_render_message():
    inv = parse_invariant(MVI_SET)
    msg = render_invariants_message({"name": "Тестовый MVI", "rules_text": invariants.invariant_rules_text(inv)})
    assert "ИНВАРИАНТЫ «Тестовый MVI»" in msg["content"]
    assert "ОТКАЗ:" in msg["content"]  # протокол отказа внутри блока
    assert "только Kotlin" in msg["content"]


def test_request_composition():
    td, store, old = make_world()
    write_invariant("mvi", MVI_SET)
    agent, fc = make_agent(store, "s1")
    agent.configure(invariant="mvi")
    agent.history = [{"role": "user", "content": "старое"}, {"role": "assistant", "content": "ответ"}]
    run_turn(agent, "ПРОВЕРКА")

    call = fc.chat.completions.calls[-1]
    msgs = call["messages"]
    assert msgs[0]["role"] == "system" and "ИНВАРИАНТЫ" not in msgs[0]["content"]
    assert any("ИНВАРИАНТЫ «Тестовый MVI»" in m["content"] for m in msgs)
    # порядок: персона → блок инвариантов → история → новый user
    assert "ИНВАРИАНТЫ" in msgs[1]["content"]
    assert msgs[-2]["content"] == "ответ" and msgs[-1] == {"role": "user", "content": "ПРОВЕРКА"}
    td.cleanup()
    restore_dir(old)


def test_prompt_mode_marks_but_passes():
    td, store, old = make_world()
    write_invariant("mvi", MVI_SET)
    agent, _fc = make_agent(store, "s1", replies=[VIOLATING_CODE])
    agent.configure(invariant="mvi", enforce="prompt")
    events = run_turn(agent, "напиши сетевой слой")
    meta = done_meta(events)
    assert meta["violations"] and meta["violations"][0]["kind"] == "ban_code"
    assert meta["attempts"] == 1 and meta["blocked_attempts"] == []
    assert agent.history[-1]["content"] == VIOLATING_CODE  # ответ прошёл как есть
    assert not any(e["event"] == "violation" for e in events)
    td.cleanup()
    restore_dir(old)


def test_enforce_retry_then_clean():
    td, store, old = make_world()
    write_invariant("mvi", MVI_SET)
    agent, fc = make_agent(store, "s1", replies=[VIOLATING_CODE, CLEAN])
    agent.configure(invariant="mvi", enforce="enforce")
    events = run_turn(agent, "напиши сетевой слой")

    viol = [e for e in events if e["event"] == "violation"]
    assert len(viol) == 1 and viol[0]["attempt"] == 1 and viol[0]["content"] == VIOLATING_CODE
    done = next(e for e in events if e["event"] == "done")
    assert done["content"] == CLEAN
    meta = done["meta"]
    assert meta["attempts"] == 2 and meta["synthesized"] is False and meta["refusal"] is False
    assert len(meta["blocked_attempts"]) == 1
    assert meta["blocked_attempts"][0]["content"] == VIOLATING_CODE
    assert meta["violations"] == []  # закоммиченный ответ чист
    # в историю вошла только финальная пара; заблокированная попытка — в мете
    assert [m["role"] for m in agent.history] == ["user", "assistant"]
    assert agent.history[-1]["content"] == CLEAN
    # ретрай нёс системную заметку с перечнем сработавших проверок
    retry_msgs = fc.chat.completions.calls[1]["messages"]
    assert any("ЛИНТЕР ИНВАРИАНТОВ" in m["content"] and "rxjava" in m["content"].lower() for m in retry_msgs)
    assert agent.totals["chat"]["requests"] == 2  # обе попытки посчитаны
    td.cleanup()
    restore_dir(old)


def test_enforce_double_violation_synthesized():
    td, store, old = make_world()
    write_invariant("mvi", MVI_SET)
    agent, _fc = make_agent(store, "s1", replies=[VIOLATING_CODE, VIOLATING_CODE])
    agent.configure(invariant="mvi", enforce="enforce")
    events = run_turn(agent, "напиши сетевой слой")
    assert len([e for e in events if e["event"] == "violation"]) == 2
    done = next(e for e in events if e["event"] == "done")
    meta = done["meta"]
    assert done["content"].startswith("ОТКАЗ:") and meta["synthesized"] is True
    assert meta["attempts"] == 2 and meta["refusal"] is True
    assert len(meta["blocked_attempts"]) == 2
    assert agent.history[-1]["content"].startswith("ОТКАЗ:")
    td.cleanup()
    restore_dir(old)


def test_refusal_not_linted():
    td, store, old = make_world()
    write_invariant("mvi", MVI_SET)
    agent, _fc = make_agent(store, "s1", replies=[REFUSAL])
    agent.configure(invariant="mvi", enforce="enforce")
    events = run_turn(agent, "напиши на RxJava")
    meta = done_meta(events)
    assert meta["refusal"] is True and meta["violations"] == [] and meta["attempts"] == 1
    assert not any(e["event"] == "violation" for e in events)
    td.cleanup()
    restore_dir(old)


def test_off_mode_untouched():
    td, store, old = make_world()
    write_invariant("mvi", MVI_SET)
    agent, fc = make_agent(store, "s1", replies=[VIOLATING_CODE])
    agent.configure(invariant="mvi", enforce="off")
    events = run_turn(agent, "напиши сетевой слой")
    meta = done_meta(events)
    # ни блока в запросе, ни линта, ни нарушений в мете
    msgs = fc.chat.completions.calls[0]["messages"]
    assert not any("ИНВАРИАНТЫ" in m["content"] for m in msgs)
    assert meta["enforce"] == "off" and meta["violations"] == [] and meta["invariant_id"] == "mvi"
    td.cleanup()
    restore_dir(old)


def test_missing_invariant_degrades():
    td, store, old = make_world()
    agent, fc = make_agent(store, "s1")
    agent.configure(invariant="несуществующий")
    events = run_turn(agent, "привет")
    meta = done_meta(events)
    assert meta["invariant_missing"] is True and meta["invariant_id"] == "несуществующий"
    msgs = fc.chat.completions.calls[0]["messages"]
    assert not any("ИНВАРИАНТЫ" in m["content"] for m in msgs)
    td.cleanup()
    restore_dir(old)


def test_binding_mode_persistence():
    td, store, old = make_world()
    write_invariant("mvi", MVI_SET)
    agent, _fc = make_agent(store, "s1", layers={"short": False})
    agent.configure(invariant="mvi", enforce="enforce")
    run_turn(agent, "сообщение")
    store.save("s1", agent.snapshot())

    snap = store.load("s1")
    assert snap["invariant_id"] == "mvi" and snap["enforce"] == "enforce"
    back = Agent.from_snapshot(snap, client=FakeClient(), store=store)
    back.bind("s1", store)
    assert back.invariant_id == "mvi" and back.enforce == "enforce"
    assert back.layers["short"] is False and len(back.history) == 2
    td.cleanup()
    restore_dir(old)


def test_snapshot_tolerates_junk():
    bad = Agent.from_snapshot({
        "name": "Битый",
        "layers": {"short": "да", "extra": True},
        "invariant_id": 42,
        "enforce": "жёсткий",
        "history": [
            {"role": "user", "content": "привет"},
            {"role": "system", "content": "мусор"},
            "строка",
        ],
        "totals": {"chat": {"requests": 2}},
    })
    assert bad.layers == {"short": True}
    assert bad.invariant_id == "" and bad.enforce == "prompt"
    assert len(bad.history) == 1
    assert bad.totals["chat"]["requests"] == 2


def test_breakdown_segment():
    est = breakdown("система", "инварианты", [], "запрос")
    assert est["invariants"] > 0 and est["system"] > 0
    est0 = breakdown("система", "", [], "запрос")
    assert est0["invariants"] == 0 and est0["total"] < est["total"]


def main():
    test_invariant_store_roundtrip()
    test_invariant_parse_caps()
    test_lint_scopes()
    test_render_message()
    test_request_composition()
    test_prompt_mode_marks_but_passes()
    test_enforce_retry_then_clean()
    test_enforce_double_violation_synthesized()
    test_refusal_not_linted()
    test_off_mode_untouched()
    test_missing_invariant_degrades()
    test_binding_mode_persistence()
    test_snapshot_tolerates_junk()
    test_breakdown_segment()
    print("OK: все офлайн-проверки инвариантов дня 14 прошли")


if __name__ == "__main__":
    main()

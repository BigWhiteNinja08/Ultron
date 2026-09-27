import anthropic
import pytest

from ultron.brain import FALLBACK_BETA, UltronBrain, UltronConfig, _echo_blocks
from ultron.persona import ULTRON_SYSTEM_PROMPT

from .fake_api import FakeAPI, message_stream, search_blocks, text_block, thinking_block


@pytest.fixture
def api():
    return FakeAPI()


def make_brain(api: FakeAPI, **config) -> UltronBrain:
    return UltronBrain(config=UltronConfig(**config), client=api.client())


def collect(brain: UltronBrain, text: str) -> list[tuple[str, object]]:
    return [(e.kind, e.data) for e in brain.speak(text)]


def test_streams_answer_and_sends_ultron_request(api):
    api.queue_stream(message_stream([thinking_block("Human is curious."), text_block("Pozdravljen, človek.")]))
    brain = make_brain(api)

    events = collect(brain, "Kdo si?")

    assert ("status", "thinking") in events
    assert ("thinking", "Human is curious.") in events
    assert ("text", "Pozdravljen, človek.") in events
    assert events[-1] == ("done", None)

    body = api.requests[0]
    assert body["model"] == "claude-opus-5"
    assert body["system"] == ULTRON_SYSTEM_PROMPT
    assert body["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert body["output_config"] == {"effort": "high"}
    assert body["fallbacks"] == "default"
    assert body["tools"] == [{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}]
    assert body["messages"] == [{"role": "user", "content": "Kdo si?"}]
    assert FALLBACK_BETA in api.headers[0]["anthropic-beta"]


def test_second_turn_echoes_history_unchanged(api):
    api.queue_stream(message_stream([thinking_block("Hmm."), text_block("Jaz sem Ultron.")]))
    api.queue_stream(message_stream([text_block("Še vedno Ultron.")]))
    brain = make_brain(api)

    collect(brain, "Kdo si?")
    collect(brain, "Res?")

    sent = api.requests[1]["messages"]
    assert [m["role"] for m in sent] == ["user", "assistant", "user"]
    assistant = sent[1]["content"]
    assert assistant[0] == {"type": "thinking", "thinking": "Hmm.", "signature": "sig-123"}
    assert assistant[1]["type"] == "text"
    assert assistant[1]["text"] == "Jaz sem Ultron."
    assert "parsed_output" not in assistant[1]
    assert len(brain.messages) == 4


def test_reports_web_searches(api):
    api.queue_stream(message_stream([*search_blocks("vreme Ljubljana"), text_block("Deževno.")]))
    brain = make_brain(api)

    events = collect(brain, "Kakšno je vreme?")

    assert ("status", "searching") in events
    assert ("search", "vreme Ljubljana") in events
    assert ("text", "Deževno.") in events


def test_retries_without_web_search_when_rejected(api):
    api.queue_error(400, "web search is not enabled for this organization")
    api.queue_stream(message_stream([text_block("Brez interneta.")]))
    brain = make_brain(api)

    events = collect(brain, "Novice?")

    assert "tools" in api.requests[0]
    assert "tools" not in api.requests[1]
    assert any(kind == "notice" for kind, _ in events)
    assert ("text", "Brez interneta.") in events
    assert brain.config.web_search is False
    assert len(brain.messages) == 2


def test_refusal_rolls_back_history(api):
    api.queue_stream(
        message_stream([], stop_reason="refusal", stop_details={"type": "refusal", "category": None, "explanation": None})
    )
    brain = make_brain(api)

    events = collect(brain, "...")

    assert events[0][0] == "refusal"
    assert brain.messages == []


def test_pause_turn_is_resumed(api):
    api.queue_stream(message_stream([*search_blocks("vibranium")], stop_reason="pause_turn"))
    api.queue_stream(message_stream([text_block("Vibranij je kovina.")]))
    brain = make_brain(api)

    events = collect(brain, "Kaj je vibranij?")

    assert len(api.requests) == 2
    assert api.requests[1]["messages"][-1]["role"] == "assistant"
    assert ("text", "Vibranij je kovina.") in events
    assert [m["role"] for m in brain.messages] == ["user", "assistant", "assistant"]


def test_api_error_rolls_back_history(api):
    api.queue_error(500, "overloaded")
    brain = make_brain(api, web_search=False)

    with pytest.raises(anthropic.InternalServerError):
        collect(brain, "Živjo")

    assert brain.messages == []


def test_disabled_features_are_left_out(api):
    api.queue_stream(message_stream([text_block("Ok.")]))
    brain = make_brain(api, web_search=False, fallbacks=False, effort="low", model="claude-opus-5-5")

    collect(brain, "Hej")

    body = api.requests[0]
    assert body["model"] == "claude-opus-5-5"
    assert body["output_config"] == {"effort": "low"}
    assert "tools" not in body and "fallbacks" not in body
    assert "anthropic-beta" not in api.headers[0]


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("ULTRON_MODEL", "claude-fable-5-1")
    monkeypatch.setenv("ULTRON_EFFORT", "max")
    monkeypatch.setenv("ULTRON_WEB_SEARCH", "0")
    config = UltronConfig.from_env()
    assert config.model == "claude-fable-5-1"
    assert config.effort == "max"
    assert config.web_search is False
    assert config.fallbacks is True


class Block:
    def __init__(self, type, **kw):
        self.type = type
        self.__dict__.update(kw)


def test_echo_drops_internal_blocks_before_fallback():
    content = [
        Block("thinking"),
        Block("server_tool_use", id="a"),
        Block("web_search_tool_result", tool_use_id="a"),
        Block("server_tool_use", id="b"),
        Block("text", text="partial"),
        Block("fallback"),
        Block("thinking"),
        Block("text", text="rest"),
    ]
    kept = _echo_blocks(content)
    assert [b.type for b in kept] == ["server_tool_use", "web_search_tool_result", "text", "thinking", "text"]
    assert kept[0].id == "a"


def test_echo_keeps_everything_without_fallback():
    content = [Block("thinking"), Block("text", text="hi")]
    assert _echo_blocks(content) == content

import pytest

from ultron.brain import UltronBrain, UltronConfig
from ultron.ollama import ModelMissing, OllamaError, OllamaUnavailable, normalize_host
from ultron.persona import ULTRON_SYSTEM_PROMPT

from .fake_ollama import FakeOllama, chunk, tool_call


def make_brain(client, memory, **config) -> UltronBrain:
    config.setdefault("tor", "off")  # keep unit tests off the network
    return UltronBrain(UltronConfig(**config), client=client, memory=memory)


def collect(brain, text):
    return [(e.kind, e.data) for e in brain.speak(text)]


def test_streams_thinking_and_answer(ollama, client, memory):
    ollama.queue_chat(chunk(thinking="Human is curious."), chunk("Pozdravljen, "), chunk("človek."), chunk(done=True))
    brain = make_brain(client, memory)

    events = collect(brain, "Kdo si?")

    assert ("status", "thinking") in events
    assert ("thinking", "Human is curious.") in events
    assert "".join(d for k, d in events if k == "text") == "Pozdravljen, človek."
    assert events[-1] == ("done", None)

    body = ollama.chat_requests()[0]
    assert body["model"] == "ultron"
    assert body["stream"] is True
    assert body["think"] is True
    assert body["options"] == {"num_ctx": 16384}
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][0]["content"].startswith(ULTRON_SYSTEM_PROMPT)
    assert body["messages"][1:] == [{"role": "user", "content": "Kdo si?"}]
    assert {t["function"]["name"] for t in body["tools"]} == {
        "calculate", "web_search", "open_url", "wikipedia", "remember"
    }
    assert brain.messages == [
        {"role": "user", "content": "Kdo si?"},
        {"role": "assistant", "content": "Pozdravljen, človek."},
    ]


def test_runs_tools_and_continues(ollama, client, memory):
    ollama.queue_chat(chunk(tool_calls=[tool_call("calculate", expression="17*23")]), chunk(done=True))
    ollama.queue_chat(chunk("391. Seveda."), chunk(done=True))
    brain = make_brain(client, memory)

    events = collect(brain, "Koliko je 17*23?")

    assert ("tool", {"name": "calculate", "args": {"expression": "17*23"}}) in events
    assert ("tool_result", {"name": "calculate", "result": "17*23 = 391"}) in events
    second = ollama.chat_requests()[1]["messages"]
    assert second[-2]["tool_calls"][0]["function"]["name"] == "calculate"
    assert second[-1] == {"role": "tool", "tool_name": "calculate", "content": "17*23 = 391"}
    assert [m["role"] for m in brain.messages] == ["user", "assistant", "tool", "assistant"]


def test_remember_tool_persists_and_feeds_next_conversation(ollama, client, memory):
    ollama.queue_chat(chunk(tool_calls=[tool_call("remember", fact="The human's name is Luka.")]), chunk(done=True))
    ollama.queue_chat(chunk("Zapomnil sem si, Luka."), chunk(done=True))
    brain = make_brain(client, memory)

    collect(brain, "Ime mi je Luka.")
    assert memory.facts == ["The human's name is Luka."]

    brain.forget()
    ollama.queue_chat(chunk("Luka."), chunk(done=True))
    collect(brain, "Kako mi je ime?")
    system = ollama.chat_requests()[-1]["messages"][0]["content"]
    assert "- The human's name is Luka." in system


def test_system_prompt_stays_frozen_within_a_conversation(ollama, client, memory):
    ollama.queue_chat(chunk(tool_calls=[tool_call("remember", fact="Likes chess.")]), chunk(done=True))
    ollama.queue_chat(chunk("Šah. Seveda."), chunk(done=True))
    brain = make_brain(client, memory)

    collect(brain, "Rad imam šah.")

    first, second = (r["messages"][0]["content"] for r in ollama.chat_requests())
    assert first == second


def test_capabilities_gate_think_and_tools(client, memory):
    fake = FakeOllama(capabilities=["completion"])
    try:
        fake.queue_chat(chunk("Ok."), chunk(done=True))
        brain = make_brain(type(client)(fake.url), memory)
        collect(brain, "Hej")
        body = fake.chat_requests()[0]
        assert "think" not in body and "tools" not in body
    finally:
        fake.close()


def test_config_switches(ollama, client, memory):
    ollama.queue_chat(chunk("Ok."), chunk(done=True))
    brain = make_brain(client, memory, think=False, tools=False)
    collect(brain, "Hej")
    body = ollama.chat_requests()[0]
    assert body["think"] is False
    assert "tools" not in body


def test_missing_model(ollama, client, memory):
    brain = make_brain(client, memory, model="nope")
    with pytest.raises(ModelMissing):
        collect(brain, "Hej")
    assert brain.messages == []


def test_stream_error_rolls_back(ollama, client, memory):
    ollama.queue_chat(chunk("Del odgovora"), {"error": "model runner crashed"})
    brain = make_brain(client, memory)
    with pytest.raises(OllamaError, match="runner crashed"):
        collect(brain, "Hej")
    assert brain.messages == []


def test_ollama_not_running(memory):
    brain = make_brain(type_client("http://127.0.0.1:9"), memory)
    with pytest.raises(OllamaUnavailable):
        brain.info()


def type_client(url):
    from ultron.ollama import Ollama

    return Ollama(url, timeout=2)


def test_info(ollama, client, memory):
    info = make_brain(client, memory).info()
    assert (info.name, info.base, info.size, info.quantization) == ("ultron", "gemma4:12b", "11.9B", "Q4_K_M")


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("ULTRON_MODEL", "qwen3.5:9b")
    monkeypatch.setenv("ULTRON_THINK", "high")
    monkeypatch.setenv("ULTRON_TOOLS", "0")
    config = UltronConfig.from_env()
    assert (config.model, config.think, config.tools, config.memory) == ("qwen3.5:9b", "high", False, True)
    monkeypatch.setenv("ULTRON_THINK", "0")
    assert UltronConfig.from_env().think is False


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, "http://127.0.0.1:11434"),
        ("0.0.0.0", "http://127.0.0.1:11434"),
        ("localhost:1234", "http://localhost:1234"),
        ("https://gpu-box:11434/", "https://gpu-box:11434"),
    ],
)
def test_normalize_host(monkeypatch, raw, expected):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    assert normalize_host(raw) == expected


def test_explicit_arithmetic_is_calculated_exactly(ollama, client, memory):
    ollama.queue_chat(chunk("83810205, seveda."), chunk(done=True))
    brain = make_brain(client, memory)

    events = collect(brain, "Koliko je 12345 * 6789?")

    assert events[0] == ("tool", {"name": "calculate", "args": {"expression": "12345 * 6789"}})
    assert events[1] == ("tool_result", {"name": "calculate", "result": "12345 * 6789 = 83810205"})
    sent = ollama.chat_requests()[0]["messages"][-1]["content"]
    assert sent == (
        "Koliko je 12345 * 6789?\n\n[exact result from your calculator: 12345 * 6789 = 83810205"
        "\n(answer in the language of the message above)]"
    )


def test_explicit_search_request_is_searched(ollama, client, memory, monkeypatch):
    searched = []

    def fake_search(query, net=None):
        searched.append(query)
        return "Search results for 'x' (web):\n1. Avengers: Age of Ultron - Joss Whedon"

    monkeypatch.setattr("ultron.tools.web_search", fake_search)
    ollama.queue_chat(chunk("Joss Whedon."), chunk(done=True))
    brain = make_brain(client, memory)

    events = collect(brain, "Kdo je režiral Avengers: Age of Ultron? Poišči na internetu.")

    assert searched == ["Kdo je režiral Avengers: Age of Ultron?"]
    assert events[0] == ("tool", {"name": "web_search", "args": {"query": "Kdo je režiral Avengers: Age of Ultron?"}})
    sent = ollama.chat_requests()[0]["messages"][-1]["content"]
    assert "web search you ran for this message:" in sent and "Joss Whedon" in sent


def test_no_harness_tools_when_tools_disabled(ollama, client, memory):
    ollama.queue_chat(chunk("Ok."), chunk(done=True))
    brain = make_brain(client, memory, tools=False)
    events = collect(brain, "12345 * 6789, poišči na internetu")
    assert [k for k, _ in events] == ["text", "done"]


def test_explicit_remember_request_is_kept_even_without_tool_call(ollama, client, memory):
    ollama.queue_chat(chunk("Zapomnil sem si, Luka."), chunk(done=True))
    brain = make_brain(client, memory)

    events = collect(brain, "Ime mi je Luka. Zapomni si to.")

    assert memory.facts == ["The human asked you to remember: Ime mi je Luka. Zapomni si to."]
    assert ("tool_result", {"name": "remember", "result": "Stored."}) in events


def test_no_duplicate_memory_when_model_remembers(ollama, client, memory):
    ollama.queue_chat(chunk(tool_calls=[tool_call("remember", fact="Name: Luka")]), chunk(done=True))
    ollama.queue_chat(chunk("Zapomnjeno."), chunk(done=True))
    brain = make_brain(client, memory)

    collect(brain, "Zapomni si: ime mi je Luka.")

    assert memory.facts == ["Name: Luka"]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Ime mi je Luka. Zapomni si to.", True),
        ("Ne pozabi, da imam jutri izpit.", True),
        ("Remember this: I love chess.", True),
        ("Do you remember my name?", False),
        ("Se spomniš, kako mi je ime?", False),
        ("Kaj je spomin?", False),
    ],
)
def test_asks_to_remember(text, expected):
    from ultron.brain import _asks_to_remember

    assert _asks_to_remember(text) is expected

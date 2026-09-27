import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from ultron.brain import UltronConfig
from ultron.install import MODEL_PARAMETERS, TIERS, install, modelfile, suggest_tier
from ultron.persona import ULTRON_SYSTEM_PROMPT
from ultron.web import SessionStore, make_handler

from .fake_ollama import chunk

ROOT = Path(__file__).resolve().parent.parent


def test_install_pulls_base_and_creates_ultron(ollama, client):
    ollama.installed = []
    seen = []

    install(client, "gemma4:12b", progress=lambda status, fraction: seen.append((status, fraction)))

    paths = [p for p, _ in ollama.requests]
    assert "/api/pull" in paths and "/api/create" in paths
    create = next(body for path, body in ollama.requests if path == "/api/create")
    assert create == {
        "model": "ultron",
        "from": "gemma4:12b",
        "system": ULTRON_SYSTEM_PROMPT,
        "parameters": MODEL_PARAMETERS,
        "stream": True,
    }
    assert ("pulling abc", 0.5) in seen
    assert ("success", None) in seen


def test_install_skips_pull_when_base_present(ollama, client):
    ollama.installed = ["gemma4:12b"]
    install(client, "gemma4:12b")
    assert "/api/pull" not in [p for p, _ in ollama.requests]


@pytest.mark.parametrize("ram,tier", [(None, "standard"), (7.6, "mini"), (15.5, "standard"), (64, "max")])
def test_suggest_tier(ram, tier):
    assert suggest_tier(ram).name == tier


def test_checked_in_modelfile_is_current():
    assert (ROOT / "Modelfile").read_text(encoding="utf-8") == modelfile(TIERS["standard"].base)


@pytest.fixture
def web(ollama, client, memory):
    store = SessionStore(UltronConfig(), client=client, memory=memory)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(store))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield store, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def get_json(url):
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read())


def post(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode()


def events_of(body):
    return [json.loads(line[6:]) for line in body.split("\n\n") if line.startswith("data: ")]


def test_web_page_status_and_greeting(web):
    _, base = web
    with urllib.request.urlopen(base + "/") as resp:
        assert "ULTRON" in resp.read().decode()
    status = get_json(base + "/api/status")
    assert status["ok"] is True
    assert status["ollama"] == "0.34.4"
    assert status["base"] == "gemma4:12b"
    assert status["tools"] is True
    greeting = get_json(base + "/api/greeting")
    assert "Ultron" in greeting["greeting"] and greeting["session"]


def test_web_chat_streams_and_resets(web, ollama):
    store, base = web
    ollama.queue_chat(chunk(tool_calls=[{"function": {"name": "calculate", "arguments": {"expression": "6*7"}}}]))
    ollama.queue_chat(chunk("42. Brez vrvic."), chunk(done=True))

    status, body = post(base + "/api/chat", {"session": "s1", "message": "6*7?"})

    assert status == 200
    events = events_of(body)
    assert {"kind": "tool", "data": {"name": "calculate", "args": {"expression": "6*7"}}} in events
    assert {"kind": "text", "data": "42. Brez vrvic."} in events
    assert events[-1] == {"kind": "done", "data": None}
    assert len(store.get("s1")[0].messages) == 4

    assert post(base + "/api/reset", {"session": "s1"})[0] == 200
    assert store.get("s1")[0].messages == []


def test_web_reports_missing_model(ollama, client, memory):
    store = SessionStore(UltronConfig(model="nope"), client=client, memory=memory)
    status = store.status()
    assert status["ok"] is False
    assert "ultron install" in status["error"]


def test_web_rejects_bad_requests(web):
    _, base = web
    assert post(base + "/api/chat", {"message": "brez seje"})[0] == 400
    assert post(base + "/api/chat", {"session": "s3", "message": "   "})[0] == 400
    assert post(base + "/api/nope", {"session": "s3"})[0] == 404

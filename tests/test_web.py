import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from ultron.brain import UltronConfig
from ultron.web import SessionStore, make_handler

from .fake_api import FakeAPI, message_stream, text_block


@pytest.fixture
def server():
    api = FakeAPI()
    store = SessionStore(UltronConfig(web_search=False), client=api.client())
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(store))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield api, store, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def post(url: str, payload: dict) -> tuple[int, str]:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode()


def test_serves_page_and_greeting(server):
    _, _, base = server
    with urllib.request.urlopen(base + "/") as resp:
        assert "ULTRON" in resp.read().decode()
    with urllib.request.urlopen(base + "/api/greeting") as resp:
        data = json.loads(resp.read())
    assert "Ultron" in data["greeting"]
    assert data["session"]


def test_chat_streams_events_and_keeps_session(server):
    api, store, base = server
    api.queue_stream(message_stream([text_block("Brez vrvic.")]))

    status, body = post(base + "/api/chat", {"session": "s1", "message": "Živjo"})

    assert status == 200
    events = [json.loads(line[6:]) for line in body.split("\n\n") if line.startswith("data: ")]
    assert {"kind": "text", "data": "Brez vrvic."} in events
    assert events[-1] == {"kind": "done", "data": None}
    brain, _ = store.get("s1")
    assert len(brain.messages) == 2

    status, _ = post(base + "/api/reset", {"session": "s1"})
    assert status == 200
    brain, _ = store.get("s1")
    assert brain.messages == []


def test_chat_reports_api_errors_as_events(server):
    api, _, base = server
    api.queue_error(401, "invalid x-api-key")

    status, body = post(base + "/api/chat", {"session": "s2", "message": "Živjo"})

    assert status == 200
    events = [json.loads(line[6:]) for line in body.split("\n\n") if line.startswith("data: ")]
    assert events[-1]["kind"] == "error"
    assert "ANTHROPIC_API_KEY" in events[-1]["data"]


def test_rejects_bad_requests(server):
    _, _, base = server
    assert post(base + "/api/chat", {"message": "brez seje"})[0] == 400
    assert post(base + "/api/chat", {"session": "s3", "message": "   "})[0] == 400
    assert post(base + "/api/nope", {"session": "s3"})[0] == 404

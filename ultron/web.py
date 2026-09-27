"""Ultron v brskalniku: majhen strežnik brez dodatnih odvisnosti."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from .brain import UltronBrain, UltronConfig
from .memory import Memory
from .ollama import ModelMissing, Ollama, OllamaError, OllamaUnavailable
from .persona import GREETING

STATIC_DIR = Path(__file__).parent / "static"
MAX_MESSAGE_CHARS = 20000


class SessionStore:
    """One UltronBrain per browser tab, each with its own lock so answers don't interleave."""

    def __init__(self, config: UltronConfig, client: Optional[Ollama] = None, memory: Optional[Memory] = None):
        self.config = config
        self.client = client or Ollama(config.host)
        self.memory = memory if memory is not None else (Memory() if config.memory else None)
        self._sessions: dict[str, tuple[UltronBrain, threading.Lock]] = {}
        self._lock = threading.Lock()

    def get(self, session_id: str) -> tuple[UltronBrain, threading.Lock]:
        with self._lock:
            if session_id not in self._sessions:
                brain = UltronBrain(self.config, client=self.client, memory=self.memory)
                self._sessions[session_id] = (brain, threading.Lock())
            return self._sessions[session_id]

    def forget(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def status(self) -> dict:
        status: dict = {"model": self.config.model, "host": self.client.host}
        try:
            status["ollama"] = self.client.version()
            brain = UltronBrain(self.config, client=self.client, memory=self.memory)
            info = brain.info()
            status.update(
                ok=True,
                base=info.base,
                size=info.size,
                quantization=info.quantization,
                capabilities=info.capabilities,
                tools=self.config.tools and "tools" in info.capabilities,
                tor=brain.net.tor,
                tor_status=brain.net.reason,
                knowledge=len(brain.knowledge.topics()) if brain.knowledge else None,
                memories=len(self.memory.facts) if self.memory else None,
            )
        except OllamaUnavailable:
            status.update(ok=False, error="Ollama ne teče. Namesti jo z https://ollama.com/download in jo zaženi.")
        except ModelMissing:
            status.update(ok=False, error=f"Model '{self.config.model}' ne obstaja. Zaženi: ultron install")
        except OllamaError as exc:
            status.update(ok=False, error=str(exc))
        return status


def make_handler(store: SessionStore):
    class UltronHandler(BaseHTTPRequestHandler):
        server_version = "Ultron/2.0"

        def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
            sys.stderr.write("[ultron] " + format % args + "\n")

        def do_GET(self) -> None:
            if self.path in {"/", "/index.html"}:
                self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            elif self.path == "/api/greeting":
                self._send_json({"greeting": GREETING, "session": uuid.uuid4().hex})
            elif self.path == "/api/status":
                self._send_json(store.status())
            else:
                self._send_json({"error": "Ni najdeno."}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            body = self._read_json()
            if body is None:
                return
            session_id = str(body.get("session") or "")
            if not session_id:
                self._send_json({"error": "Manjka seja."}, HTTPStatus.BAD_REQUEST)
                return

            if self.path == "/api/reset":
                store.forget(session_id)
                self._send_json({"ok": True})
            elif self.path == "/api/chat":
                message = str(body.get("message") or "").strip()
                if not message or len(message) > MAX_MESSAGE_CHARS:
                    self._send_json({"error": "Sporočilo je prazno ali predolgo."}, HTTPStatus.BAD_REQUEST)
                    return
                self._stream_reply(session_id, message)
            else:
                self._send_json({"error": "Ni najdeno."}, HTTPStatus.NOT_FOUND)

        def _stream_reply(self, session_id: str, message: str) -> None:
            brain, lock = store.get(session_id)
            if not lock.acquire(blocking=False):
                self._send_json({"error": "Ultron še govori."}, HTTPStatus.CONFLICT)
                return
            try:
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                try:
                    for event in brain.speak(message):
                        self._sse({"kind": event.kind, "data": event.data})
                except (BrokenPipeError, ConnectionResetError):
                    return
                except Exception as exc:  # reported to the page, never crashes the server
                    self._sse({"kind": "error", "data": _describe_error(exc, brain.config.model)})
            finally:
                lock.release()

        def _sse(self, payload: dict) -> None:
            self.wfile.write(f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8"))
            self.wfile.flush()

        def _read_json(self) -> Optional[dict]:
            try:
                length = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(data, dict):
                    raise ValueError("expected an object")
                return data
            except ValueError:
                self._send_json({"error": "Neveljaven JSON."}, HTTPStatus.BAD_REQUEST)
                return None

        def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_file(self, path: Path, content_type: str) -> None:
            data = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return UltronHandler


def _describe_error(exc: Exception, model: str) -> str:
    if isinstance(exc, OllamaUnavailable):
        return "Izgubil sem povezavo z Ollamo. Ali še teče?"
    if isinstance(exc, ModelMissing):
        return f"Model '{model}' ne obstaja. Zaženi: ultron install"
    if isinstance(exc, OllamaError):
        hint = " Modelu je verjetno zmanjkalo pomnilnika (glej README)." if "unexpected" in str(exc).lower() else ""
        return f"Napaka Ollame: {exc}.{hint}"
    return f"Nepričakovana napaka: {exc}"


def serve(config: UltronConfig, bind: str = "127.0.0.1", port: int = 8000) -> int:
    server = ThreadingHTTPServer((bind, port), make_handler(SessionStore(config)))
    print(f"[ULTRON//WEB] um je buden: http://{'127.0.0.1' if bind == '0.0.0.0' else bind}:{port}  (Ctrl+C za konec)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="ultron-web", description="Ultron v brskalniku.")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--model", help="Ollama model (privzeto: ultron)")
    args = parser.parse_args(argv)
    config = UltronConfig.from_env()
    if args.model:
        config.model = args.model
    return serve(config, args.bind, args.port)


if __name__ == "__main__":
    sys.exit(main())

"""A fake Ollama server on localhost, so tests exercise the real HTTP client."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def chunk(content: str = "", thinking: str = "", tool_calls=None, done: bool = False) -> dict:
    message: dict = {"role": "assistant", "content": content}
    if thinking:
        message["thinking"] = thinking
    if tool_calls:
        message["tool_calls"] = tool_calls
    data = {"model": "ultron", "message": message, "done": done}
    if done:
        data["done_reason"] = "stop"
    return data


def tool_call(name: str, **arguments) -> dict:
    return {"id": f"call_{name}", "function": {"index": 0, "name": name, "arguments": arguments}}


class FakeOllama:
    def __init__(self, capabilities=("completion", "tools", "thinking"), installed=("ultron:latest",)):
        self.capabilities = list(capabilities)
        self.installed = list(installed)
        self.chats: list[list[dict]] = []  # queued chat streams
        self.requests: list[tuple[str, dict]] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                fake.requests.append((self.path, {}))
                if self.path == "/api/version":
                    self._json({"version": "0.34.4"})
                elif self.path == "/api/tags":
                    self._json({"models": [{"name": n} for n in fake.installed]})
                else:
                    self._json({"error": "not found"}, 404)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                fake.requests.append((self.path, body))
                model = body.get("model", "")
                if self.path == "/api/show":
                    if model not in fake.installed and f"{model}:latest" not in fake.installed:
                        self._json({"error": f"model '{model}' not found"}, 404)
                        return
                    self._json(
                        {
                            "capabilities": fake.capabilities,
                            "details": {
                                "parent_model": "gemma4:12b",
                                "parameter_size": "11.9B",
                                "quantization_level": "Q4_K_M",
                            },
                        }
                    )
                elif self.path == "/api/chat":
                    self._stream(fake.chats.pop(0))
                elif self.path == "/api/pull":
                    fake.installed.append(model)
                    self._stream(
                        [
                            {"status": "pulling manifest"},
                            {"status": "pulling abc", "total": 100, "completed": 50},
                            {"status": "pulling abc", "total": 100, "completed": 100},
                            {"status": "success"},
                        ]
                    )
                elif self.path == "/api/create":
                    fake.installed.append(f"{model}:latest")
                    self._stream([{"status": "writing manifest"}, {"status": "success"}])
                else:
                    self._json({"error": "not found"}, 404)

            def _json(self, payload, status=200):
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _stream(self, chunks):
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.end_headers()
                for c in chunks:
                    self.wfile.write((json.dumps(c) + "\n").encode())
                    self.wfile.flush()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def queue_chat(self, *chunks: dict) -> None:
        self.chats.append(list(chunks))

    def chat_requests(self) -> list[dict]:
        return [body for path, body in self.requests if path == "/api/chat"]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

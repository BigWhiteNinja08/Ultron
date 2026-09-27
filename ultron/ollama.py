"""Minimal Ollama client (standard library only) - the engine that runs Ultron's mind locally."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Iterator, Optional

DEFAULT_HOST = "http://127.0.0.1:11434"


class OllamaError(RuntimeError):
    """Ollama answered with an error."""


class OllamaUnavailable(OllamaError):
    """Ollama is not running or cannot be reached."""


class ModelMissing(OllamaError):
    """The requested model is not installed in Ollama."""


def normalize_host(host: Optional[str]) -> str:
    host = (host or os.environ.get("OLLAMA_HOST") or DEFAULT_HOST).strip().rstrip("/")
    if "://" not in host:
        host = "http://" + host
    scheme, rest = host.split("://", 1)
    if ":" not in rest.split("/")[0]:
        rest = rest + ":11434"
    # A server listening on every interface is still reached through loopback.
    rest = rest.replace("0.0.0.0", "127.0.0.1", 1)
    return f"{scheme}://{rest}"


class Ollama:
    def __init__(self, host: Optional[str] = None, timeout: float = 900):
        self.host = normalize_host(host)
        self.timeout = timeout
        # Talk to Ollama directly, even when a system HTTP proxy is configured.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _open(self, path: str, payload: Optional[dict], method: str):
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            self.host + path, data=data, method=method, headers={"Content-Type": "application/json"}
        )
        try:
            return self._opener.open(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            message = _error_message(exc)
            if exc.code == 404 and "not found" in message.lower():
                raise ModelMissing(message) from exc
            raise OllamaError(message) from exc
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            raise OllamaUnavailable(f"Ollama ni dosegljiva na {self.host} ({exc})") from exc

    def _json(self, path: str, payload: Optional[dict] = None, method: str = "POST") -> dict:
        with self._open(path, payload, method) as response:
            return json.loads(response.read() or b"{}")

    def _stream(self, path: str, payload: dict) -> Iterator[dict]:
        with self._open(path, {**payload, "stream": True}, "POST") as response:
            for line in response:
                if not line.strip():
                    continue
                chunk = json.loads(line)
                if "error" in chunk:
                    raise OllamaError(chunk["error"])
                yield chunk

    def version(self) -> str:
        return self._json("/api/version", method="GET").get("version", "?")

    def models(self) -> list[str]:
        return [m["name"] for m in self._json("/api/tags", method="GET").get("models", [])]

    def show(self, model: str) -> dict:
        return self._json("/api/show", {"model": model})

    def pull(self, model: str) -> Iterator[dict]:
        return self._stream("/api/pull", {"model": model})

    def create(self, model: str, base: str, system: str, parameters: dict) -> Iterator[dict]:
        return self._stream("/api/create", {"model": model, "from": base, "system": system, "parameters": parameters})

    def chat(
        self,
        model: str,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        think=None,
        options: Optional[dict] = None,
    ) -> Iterator[dict]:
        payload: dict = {"model": model, "messages": messages}
        if tools:
            payload["tools"] = tools
        if think is not None:
            payload["think"] = think
        if options:
            payload["options"] = options
        return self._stream("/api/chat", payload)


def _error_message(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read()
        return json.loads(body).get("error") or body.decode(errors="replace")
    except Exception:
        return f"HTTP {exc.code}"

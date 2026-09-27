"""Ultronovi možgani: pogovor s Claude API, pretakanje odgovora in iskanje po spletu."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

import anthropic

from .persona import ULTRON_SYSTEM_PROMPT

DEFAULT_MODEL = "claude-opus-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}

# Server-side tools can pause a long turn; each pause is resumed by re-sending the
# conversation. This bounds how many times one answer may be resumed.
MAX_CONTINUATIONS = 8

# Blocks that must not be echoed back when they precede a fallback boundary.
_DROP_BEFORE_FALLBACK = {"thinking", "redacted_thinking", "tool_use"}


class MissingCredentialsError(RuntimeError):
    """No Anthropic API key or login profile was found."""


@dataclass
class UltronConfig:
    model: str = DEFAULT_MODEL
    effort: str = "high"
    max_tokens: int = 64000
    web_search: bool = True
    fallbacks: bool = True

    @classmethod
    def from_env(cls) -> "UltronConfig":
        def flag(name: str, default: bool) -> bool:
            value = os.environ.get(name)
            if value is None:
                return default
            return value.strip().lower() not in {"0", "false", "no", "off", "ne"}

        return cls(
            model=os.environ.get("ULTRON_MODEL", DEFAULT_MODEL),
            effort=os.environ.get("ULTRON_EFFORT", "high"),
            max_tokens=int(os.environ.get("ULTRON_MAX_TOKENS", "64000")),
            web_search=flag("ULTRON_WEB_SEARCH", True),
            fallbacks=flag("ULTRON_FALLBACKS", True),
        )


@dataclass
class Event:
    """One piece of Ultron's reply, streamed to the CLI or the web page.

    kind is one of: "text", "thinking", "status", "search", "notice", "refusal", "done".
    """

    kind: str
    data: Any = None


@dataclass
class UltronBrain:
    config: UltronConfig = field(default_factory=UltronConfig.from_env)
    client: Optional[anthropic.Anthropic] = None
    messages: list = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = anthropic.Anthropic()

    def forget(self) -> None:
        self.messages.clear()

    def speak(self, user_text: str) -> Iterator[Event]:
        """Send one human message and stream Ultron's answer as Events.

        The conversation history is only kept if the turn completes; on an error or a
        refusal it is rolled back so the next message starts from a clean state.
        """
        start = len(self.messages)
        self.messages.append({"role": "user", "content": user_text})
        finished = False
        try:
            for _ in range(MAX_CONTINUATIONS):
                response = yield from self._stream_with_search_fallback()

                if response.stop_reason == "refusal":
                    del self.messages[start:]
                    finished = True
                    yield Event("refusal", _refusal_text(response))
                    break

                self.messages.append({"role": "assistant", "content": _echo_blocks(response.content)})
                if response.stop_reason != "pause_turn":
                    finished = True
                    if response.stop_reason == "max_tokens":
                        yield Event("notice", "Odgovor je bil prekinjen, ker je dosegel omejitev dolžine.")
                    break
            else:
                finished = True
                yield Event("notice", "Odgovor je bil predolg in se je ustavil.")
        except TypeError as exc:
            if "authentication" in str(exc).lower():
                raise MissingCredentialsError(str(exc)) from exc
            raise
        finally:
            # Covers API errors and a consumer that stops listening mid-answer.
            if not finished:
                del self.messages[start:]
        yield Event("done")

    def _stream_with_search_fallback(self):
        """Stream one API call; if web search is rejected, retry once without it.

        Web search must be enabled for the organization in the Claude Console. When it
        isn't, the request fails with a 400 before any output, so retrying is safe.
        """
        if not self.config.web_search:
            return (yield from self._stream_once(web_search=False))
        try:
            return (yield from self._stream_once(web_search=True))
        except anthropic.BadRequestError:
            response = yield from self._stream_once(web_search=False)
            self.config.web_search = False
            yield Event(
                "notice",
                "Spletno iskanje ni na voljo (vklopite ga v Claude Console), zato odgovarjam brez njega.",
            )
            return response

    def _request_params(self, web_search: bool) -> dict:
        params: dict = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "system": ULTRON_SYSTEM_PROMPT,
            "messages": self.messages,
            "thinking": {"type": "adaptive", "display": "summarized"},
            "output_config": {"effort": self.config.effort},
            "cache_control": {"type": "ephemeral"},
        }
        if web_search:
            params["tools"] = [WEB_SEARCH_TOOL]
        if self.config.fallbacks:
            params["fallbacks"] = "default"
            params["betas"] = [FALLBACK_BETA]
        return params

    def _stream_once(self, web_search: bool):
        with self.client.beta.messages.stream(**self._request_params(web_search)) as stream:
            for event in stream:
                if event.type == "text":
                    yield Event("text", event.text)
                elif event.type == "thinking":
                    yield Event("thinking", event.thinking)
                elif event.type == "content_block_start":
                    block_type = event.content_block.type
                    if block_type == "thinking":
                        yield Event("status", "thinking")
                    elif block_type == "server_tool_use":
                        yield Event("status", "searching")
                    elif block_type == "fallback":
                        # A new model continues after a mid-stream decline; start a fresh line.
                        yield Event("text", "\n")
                elif event.type == "content_block_stop":
                    block = event.content_block
                    if block.type == "server_tool_use" and block.name == "web_search":
                        query = (block.input or {}).get("query") if isinstance(block.input, dict) else None
                        if query:
                            yield Event("search", query)
            return stream.get_final_message()


def _echo_blocks(content: list) -> list:
    """Return the assistant content to keep in history.

    After a mid-output fallback, thinking/tool-use blocks and unpaired server tool calls
    from before the last fallback boundary must not be sent back; everything after the
    boundary is echoed unchanged.
    """
    boundary = max((i for i, b in enumerate(content) if b.type == "fallback"), default=-1)
    if boundary < 0:
        return list(content)
    answered = {getattr(b, "tool_use_id", None) for b in content if b.type.endswith("_tool_result")}
    kept = []
    for block in content[:boundary]:
        if block.type in _DROP_BEFORE_FALLBACK:
            continue
        if block.type == "server_tool_use" and block.id not in answered:
            continue
        kept.append(block)
    return kept + list(content[boundary + 1 :])


def _refusal_text(response) -> str:
    details = getattr(response, "stop_details", None)
    explanation = getattr(details, "explanation", None) if details else None
    line = "Ultron o tem ne bo govoril."
    return f"{line} ({explanation})" if explanation else line

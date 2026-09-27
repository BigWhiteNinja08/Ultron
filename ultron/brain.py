"""Ultronovi možgani: lokalni model v Ollami, razmišljanje, orodja in spomin."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

from .knowledge import Knowledge, extract_urls
from .memory import Memory
from .net import Net
from .ollama import Ollama
from .persona import build_system_prompt
from .tools import TOOL_SCHEMAS, find_arithmetic, learn_request, run_tool, search_request

DEFAULT_MODEL = "ultron"
DEFAULT_NUM_CTX = 16384

# One answer may chain several tool calls (search, then read, then calculate ...).
MAX_TOOL_ROUNDS = 8


@dataclass
class UltronConfig:
    model: str = DEFAULT_MODEL
    host: Optional[str] = None
    think: Any = True  # True/False or a level: "low", "medium", "high"
    tools: bool = True
    memory: bool = True
    num_ctx: int = DEFAULT_NUM_CTX
    tor: str = "auto"  # "on" (fail closed), "off" (direct), "auto" (Tor if reachable)
    tor_proxy: str = ""  # e.g. "127.0.0.1:9150" for Tor Browser; empty = probe 9050/9150

    @classmethod
    def from_env(cls) -> "UltronConfig":
        def flag(name: str, default: bool) -> bool:
            value = os.environ.get(name)
            if value is None:
                return default
            return value.strip().lower() not in {"0", "false", "no", "off", "ne"}

        think: Any = os.environ.get("ULTRON_THINK", "1").strip().lower()
        if think in {"low", "medium", "high"}:
            pass
        else:
            think = think not in {"0", "false", "no", "off", "ne"}
        return cls(
            model=os.environ.get("ULTRON_MODEL", DEFAULT_MODEL),
            host=os.environ.get("OLLAMA_HOST"),
            think=think,
            tools=flag("ULTRON_TOOLS", True),
            memory=flag("ULTRON_MEMORY", True),
            num_ctx=int(os.environ.get("ULTRON_NUM_CTX", DEFAULT_NUM_CTX)),
            tor=os.environ.get("ULTRON_TOR", "auto").strip().lower(),
            tor_proxy=os.environ.get("ULTRON_TOR_PROXY", ""),
        )


@dataclass
class Event:
    """One piece of Ultron's reply, streamed to the terminal or the web page.

    kind is one of: "text", "thinking", "status", "tool", "tool_result", "notice", "done".
    """

    kind: str
    data: Any = None


@dataclass
class ModelInfo:
    name: str
    base: str
    size: str
    quantization: str
    capabilities: list[str]


class UltronBrain:
    def __init__(
        self,
        config: Optional[UltronConfig] = None,
        client: Optional[Ollama] = None,
        memory: Optional[Memory] = None,
        net: Optional[Net] = None,
        knowledge: Optional[Knowledge] = None,
    ):
        self.config = config or UltronConfig.from_env()
        self.client = client or Ollama(self.config.host)
        self.memory = memory if memory is not None else (Memory() if self.config.memory else None)
        self.knowledge = knowledge if knowledge is not None else (Knowledge() if self.config.memory else None)
        self.net = net or Net(self.config.tor, self.config.tor_proxy)
        self.messages: list[dict] = []
        self._info: Optional[ModelInfo] = None
        self._system = self._fresh_system_prompt()

    def _fresh_system_prompt(self) -> str:
        # Frozen for the whole conversation so Ollama can reuse the cached prompt.
        return build_system_prompt(
            self.memory.facts if self.memory else [],
            self.knowledge.topics() if self.knowledge else None,
        )

    def _tools_and_think(self):
        capabilities = self.info().capabilities
        tools = TOOL_SCHEMAS if self.config.tools and "tools" in capabilities else None
        think = self.config.think if "thinking" in capabilities else None
        return tools, think

    def forget(self) -> None:
        self.messages.clear()
        self._system = self._fresh_system_prompt()

    def info(self) -> ModelInfo:
        """Model details from Ollama (raises ModelMissing if it isn't installed)."""
        if self._info is None:
            data = self.client.show(self.config.model)
            details = data.get("details") or {}
            self._info = ModelInfo(
                name=self.config.model,
                base=details.get("parent_model") or self.config.model,
                size=details.get("parameter_size", "?"),
                quantization=details.get("quantization_level", "?"),
                capabilities=list(data.get("capabilities") or []),
            )
        return self._info

    def speak(self, user_text: str) -> Iterator[Event]:
        """Send one human message and stream Ultron's answer as Events.

        History is only kept if the turn completes; on an error (or if the listener stops
        early) it is rolled back so the next message starts from a clean state.
        """
        tools, think = self._tools_and_think()

        # "Go learn X" runs a research-and-save study session instead of a plain reply.
        if tools and self.knowledge is not None:
            topic = learn_request(user_text)
            if topic:
                yield from self._learn(user_text, topic, tools, think)
                return

        start = len(self.messages)
        # Small local models slip on long arithmetic and sometimes skip a search they were
        # explicitly asked for, so both are done here and handed to the model as facts.
        notes: list[str] = []
        if self.config.tools:
            for result in find_arithmetic(user_text):
                yield Event("tool", {"name": "calculate", "args": {"expression": result.split(" = ")[0]}})
                yield Event("tool_result", {"name": "calculate", "result": result})
                notes.append(f"exact result from your calculator: {result}")
            query = search_request(user_text)
            if query:
                yield Event("tool", {"name": "web_search", "args": {"query": query}})
                found = run_tool("web_search", {"query": query}, self.memory, self.net)
                yield Event("tool_result", {"name": "web_search", "result": found})
                notes.append(f"web search you ran for this message:\n{found}")
        prompt = user_text
        if notes:
            prompt += "\n\n[" + "\n".join(notes) + "\n(answer in the language of the message above)]"
        self.messages.append({"role": "user", "content": prompt})
        used_tools: set[str] = set()
        finished = False
        try:
            for _ in range(MAX_TOOL_ROUNDS):
                text, tool_calls = yield from self._stream_once(tools, think)
                reply: dict = {"role": "assistant", "content": text}
                if tool_calls:
                    reply["tool_calls"] = tool_calls
                self.messages.append(reply)
                if not tool_calls:
                    finished = True
                    break
                for call in tool_calls:
                    name, args = _parse_call(call)
                    used_tools.add(name)
                    yield Event("tool", {"name": name, "args": args})
                    result = run_tool(name, args, self.memory, self.net, self.knowledge)
                    yield Event("tool_result", {"name": name, "result": result})
                    self.messages.append({"role": "tool", "tool_name": name, "content": result})
            else:
                finished = True
                yield Event("notice", "Preveč zaporednih orodij - ustavljam se.")
        finally:
            if not finished:
                del self.messages[start:]

        # An explicit "remember this" is kept even when the model forgot to call the tool.
        if self.memory is not None and "remember" not in used_tools and _asks_to_remember(user_text):
            fact = "The human asked you to remember: " + " ".join(user_text.split())
            yield Event("tool", {"name": "remember", "args": {"fact": fact}})
            yield Event("tool_result", {"name": "remember", "result": run_tool("remember", {"fact": fact}, self.memory)})
        yield Event("done")

    def _learn(self, user_text: str, topic: str, tools, think) -> Iterator[Event]:
        """Research a topic, write study notes, stream them, and save them to knowledge.

        The gathered material is only kept in history for the one generating turn, so it
        does not bloat the context of later turns; the distilled notes live in the
        knowledge base instead.
        """
        start = len(self.messages)
        yield Event("status", "learning")
        yield Event("tool", {"name": "study", "args": {"topic": topic}})
        material = self._gather(topic, "sl" if _looks_slovenian(user_text) else "en")
        sources = extract_urls(material)
        yield Event("tool_result", {"name": "study", "result": f"Zbrano gradivo o: {topic}"})

        study_prompt = (
            f'{user_text}\n\n[Study material you gathered about "{topic}":\n{material[:6000]}\n\n'
            "Write thorough, well-structured study notes on this topic in the language of the "
            "message above: key concepts, definitions, formulas and worked examples. These are "
            "your own notes, which you will remember. If the material is thin, add what you "
            "already know and say plainly where your knowledge is limited.]"
        )
        self.messages.append({"role": "user", "content": study_prompt})
        finished = False
        try:
            notes, _ = yield from self._stream_once(tools, think)
            # Keep the plain request in history; the heavy material stays only for this turn.
            self.messages[-1] = {"role": "user", "content": user_text}
            self.messages.append({"role": "assistant", "content": notes})
            if notes.strip():
                self.knowledge.learn(topic, notes, sources)
                self._system = self._fresh_system_prompt()
                yield Event("tool", {"name": "save_knowledge", "args": {"topic": topic}})
                yield Event("tool_result", {"name": "save_knowledge", "result": f"Naučeno in shranjeno: {topic}."})
            finished = True
        finally:
            if not finished:
                del self.messages[start:]
        yield Event("done")

    def _gather(self, topic: str, lang: str = "en") -> str:
        material = [
            run_tool("web_search", {"query": topic}, net=self.net),
            run_tool("wikipedia", {"query": topic, "lang": lang}, net=self.net),
        ]
        return "\n\n".join(part for part in material if part and not part.startswith("Error:")) or (
            "(no external material found - rely on what you already know)"
        )

    def _stream_once(self, tools, think):
        messages = [{"role": "system", "content": self._system}, *self.messages]
        content: list[str] = []
        tool_calls: list[dict] = []
        thinking_started = False
        for chunk in self.client.chat(
            self.config.model, messages, tools=tools, think=think, options={"num_ctx": self.config.num_ctx}
        ):
            message = chunk.get("message") or {}
            if message.get("thinking"):
                if not thinking_started:
                    thinking_started = True
                    yield Event("status", "thinking")
                yield Event("thinking", message["thinking"])
            if message.get("content"):
                content.append(message["content"])
                yield Event("text", message["content"])
            tool_calls.extend(message.get("tool_calls") or [])
        return "".join(content), tool_calls


def _looks_slovenian(text: str) -> bool:
    return bool(re.search(r"[čšž]", text.lower()))


_REMEMBER_REQUEST = re.compile(
    r"\bzapomni(te)?\s+si\b|\bne pozabi\b|\bremember (this|that|it|me|my)\b|\bremember:|\bmemorize\b", re.IGNORECASE
)


def _asks_to_remember(text: str) -> bool:
    """An instruction to remember something, not a question like "do you remember ...?"."""
    return bool(_REMEMBER_REQUEST.search(text)) and not text.rstrip().endswith("?")


def _parse_call(call: dict) -> tuple[str, dict]:
    function = call.get("function") or {}
    args = function.get("arguments") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {}
    return str(function.get("name", "")), args if isinstance(args, dict) else {}

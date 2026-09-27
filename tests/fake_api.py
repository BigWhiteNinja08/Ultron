"""A fake Claude API served through the real SDK, so tests exercise actual streaming."""

from __future__ import annotations

import json

import anthropic
import httpx2


def sse(events: list[dict]) -> bytes:
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def message_stream(blocks: list[dict], stop_reason: str = "end_turn", stop_details: dict | None = None) -> bytes:
    """Build an SSE body. Each block is {"start": {...}, "deltas": [...]}."""
    events = [
        {
            "type": "message_start",
            "message": {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 0},
            },
        }
    ]
    for index, block in enumerate(blocks):
        events.append({"type": "content_block_start", "index": index, "content_block": block["start"]})
        for delta in block.get("deltas", []):
            events.append({"type": "content_block_delta", "index": index, "delta": delta})
        events.append({"type": "content_block_stop", "index": index})
    events.append(
        {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason, "stop_sequence": None, "stop_details": stop_details},
            "usage": {"output_tokens": 5},
        }
    )
    events.append({"type": "message_stop"})
    return sse(events)


def text_block(text: str) -> dict:
    return {"start": {"type": "text", "text": ""}, "deltas": [{"type": "text_delta", "text": text}]}


def thinking_block(summary: str) -> dict:
    return {
        "start": {"type": "thinking", "thinking": "", "signature": ""},
        "deltas": [
            {"type": "thinking_delta", "thinking": summary},
            {"type": "signature_delta", "signature": "sig-123"},
        ],
    }


def search_blocks(query: str) -> list[dict]:
    return [
        {
            "start": {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {}},
            "deltas": [{"type": "input_json_delta", "partial_json": json.dumps({"query": query})}],
        },
        {
            "start": {
                "type": "web_search_tool_result",
                "tool_use_id": "srvtoolu_1",
                "content": [
                    {
                        "type": "web_search_result",
                        "title": "Result",
                        "url": "https://example.com",
                        "encrypted_content": "abc",
                        "page_age": None,
                    }
                ],
            }
        },
    ]


class FakeAPI:
    """Replays queued responses and records every request body and header set."""

    def __init__(self):
        self.responses: list[httpx2.Response] = []
        self.requests: list[dict] = []
        self.headers: list[dict] = []

    def queue_stream(self, body: bytes) -> None:
        self.responses.append(httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body))

    def queue_error(self, status: int, message: str) -> None:
        payload = {"type": "error", "error": {"type": "invalid_request_error", "message": message}}
        self.responses.append(httpx2.Response(status, json=payload))

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(json.loads(request.content))
        self.headers.append(dict(request.headers))
        return self.responses.pop(0)

    def client(self) -> anthropic.Anthropic:
        return anthropic.Anthropic(
            api_key="test-key",
            max_retries=0,
            http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(self.handler)),
        )

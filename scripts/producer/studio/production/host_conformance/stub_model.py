"""Loopback stand-in for the Messages endpoint a host CLI calls.

It lets a probe measure host mechanics (session ids, interrupts, tool cleanup,
orphan behaviour, usage plumbing) with no provider call: it binds 127.0.0.1 only,
follows a fixed script and records every request it receives. It never proves
subscription identity or real-model behaviour.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@dataclass(frozen=True)
class StubScript:
    """What the stub answers: one Bash request for a main-loop turn, then text."""

    tool_input: dict | None = None
    text: str = "OK"
    usage: tuple[int, int] = (11, 7)


@dataclass
class StubLog:
    """Thread-safe record of requests the stub served."""

    rows: list[dict] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, row: dict) -> None:
        """Append one request summary with a wall-clock stamp."""
        with self.lock:
            self.rows.append({"at": round(time.time(), 3), **row})

    def snapshot(self) -> list[dict]:
        """Copy of all rows so far."""
        with self.lock:
            return list(self.rows)


def _has_tool_result(body: dict) -> bool:
    """Whether any user message after the newest assistant message carries a tool result.

    Hosts may append a separate reminder/attachment message after the tool
    result, so only looking at the final message would miss it.
    """
    messages = body.get("messages") or []
    roles = [m.get("role") for m in messages]
    start = len(roles) - roles[::-1].index("assistant") if "assistant" in roles else 0
    blocks = [b for m in messages[start:] if isinstance(m.get("content"), list) for b in m["content"]]
    return any(isinstance(b, dict) and b.get("type") == "tool_result" for b in blocks)


def _blocks(script: StubScript, body: dict) -> tuple[list[dict], str]:
    """Choose content blocks and stop reason for one request."""
    main_loop = bool(body.get("tools"))
    if main_loop and script.tool_input and not _has_tool_result(body):
        block = {"type": "tool_use", "id": f"toolu_stub_{int(time.time() * 1000)}",
                 "name": "Bash", "input": script.tool_input}
        return [block], "tool_use"
    text = "DONE" if _has_tool_result(body) else script.text
    return [{"type": "text", "text": text}], "end_turn"


def _message(script: StubScript, blocks: list[dict], stop: str) -> dict:
    """Complete non-streaming message body."""
    return {"id": f"msg_stub_{int(time.time() * 1000)}", "type": "message",
            "role": "assistant", "model": "loopback-stub", "content": blocks,
            "stop_reason": stop, "stop_sequence": None,
            "usage": {"input_tokens": script.usage[0], "output_tokens": script.usage[1],
                      "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}


def _sse_events(message: dict) -> list[tuple[str, dict]]:
    """Streaming event sequence equivalent to one complete message."""
    start = dict(message, content=[], stop_reason=None)
    start["usage"] = dict(message["usage"], output_tokens=1)
    events = [("message_start", {"type": "message_start", "message": start})]
    for index, block in enumerate(message["content"]):
        if block["type"] == "tool_use":
            opening = dict(block, input={})
            delta = {"type": "input_json_delta", "partial_json": json.dumps(block["input"])}
        else:
            opening = {"type": "text", "text": ""}
            delta = {"type": "text_delta", "text": block["text"]}
        events += [("content_block_start", {"type": "content_block_start", "index": index,
                                            "content_block": opening}),
                   ("content_block_delta", {"type": "content_block_delta", "index": index,
                                            "delta": delta}),
                   ("content_block_stop", {"type": "content_block_stop", "index": index})]
    events.append(("message_delta", {"type": "message_delta",
                                     "delta": {"stop_reason": message["stop_reason"],
                                               "stop_sequence": None},
                                     "usage": {"output_tokens": message["usage"]["output_tokens"]}}))
    events.append(("message_stop", {"type": "message_stop"}))
    return events


class _Handler(BaseHTTPRequestHandler):
    """Serve scripted Messages responses; everything else is a logged 404."""

    server_version = "loopback-stub/1"

    def log_message(self, *_args) -> None:
        """Silence the default stderr access log."""

    def _send_json(self, status: int, payload: dict) -> None:
        """Complete JSON response with an explicit length."""
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        """Unknown reads are recorded and refused."""
        self.server.stub_log.add({"method": "GET", "path": self.path})
        self._send_json(404, {"type": "error", "error": {"type": "not_found_error"}})

    def do_POST(self) -> None:
        """Answer /v1/messages per the script; record the request shape."""
        body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        row = {"method": "POST", "path": self.path, "stream": bool(body.get("stream")),
               "hasTools": bool(body.get("tools")), "afterToolResult": _has_tool_result(body)}
        self.server.stub_log.add(row)
        if self.path.split("?")[0].endswith("/count_tokens"):
            return self._send_json(200, {"input_tokens": self.server.script.usage[0]})
        if not self.path.split("?")[0].endswith("/v1/messages"):
            return self._send_json(404, {"type": "error", "error": {"type": "not_found_error"}})
        blocks, stop = _blocks(self.server.script, body)
        message = _message(self.server.script, blocks, stop)
        if not body.get("stream"):
            return self._send_json(200, message)
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        for name, event in _sse_events(message):
            self.wfile.write(f"event: {name}\ndata: {json.dumps(event)}\n\n".encode())
        self.wfile.flush()


class StubModel:
    """A running loopback stub bound to an ephemeral 127.0.0.1 port."""

    def __init__(self, script: StubScript) -> None:
        """Bind immediately; serve on a daemon thread after start()."""
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.server.daemon_threads = True
        self.server.script = script
        self.server.stub_log = StubLog()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        """Loopback URL a host CLI is pointed at."""
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def start(self) -> StubModel:
        """Begin serving; returns self for chaining."""
        self.thread.start()
        return self

    def requests(self) -> list[dict]:
        """Every request served so far."""
        return self.server.stub_log.snapshot()

    def stop(self) -> None:
        """Stop serving and release the port."""
        self.server.shutdown()
        self.server.server_close()

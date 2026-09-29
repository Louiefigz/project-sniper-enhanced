"""Minimal JSON-RPC client for a Codex app-server this probe launches over stdio.

The probe never connects to an app-server it did not start (the desktop app and
other sessions run their own). Requests and notifications are recorded with the
launch clock so interrupt and completion latencies are measurable.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from studio.production.host_conformance import claude_host
from studio.production.host_conformance.stream_child import Launch, StreamChild

# Plugins/apps are disabled so a probe thread starts no connector MCP servers.
APP_SERVER = ("app-server", "--listen", "stdio://", "-c", "mcp_servers={}",
              "--disable", "plugins", "--disable", "apps")
CLIENT_INFO = {"name": "sniper-host-conformance", "version": "1"}


def binary() -> str:
    """The installed codex CLI resolved on the clean PATH."""
    found = shutil.which("codex", path=claude_host.clean_env()["PATH"])
    if found is None:
        raise FileNotFoundError("codex CLI is not on the clean PATH")
    return found


def launch(exe: str, work: Path, raw_log: Path, extra: tuple[str, ...] = ()) -> Launch:
    """App-server launch shape with the clean environment; extra config after APP_SERVER."""
    return Launch((exe, *APP_SERVER, *extra), work, claude_host.clean_env(), raw_log)


def is_response(request_id: int):
    """Predicate for the response to one request id."""
    return lambda e: e.get("id") == request_id and "method" not in e


def is_note(method: str, **match: object):
    """Predicate for a notification whose params contain the given values."""
    def check(event: dict) -> bool:
        """Method equality plus the requested parameter values."""
        params = event.get("params") or {}
        return event.get("method") == method and all(params.get(k) == v for k, v in match.items())
    return check


class RpcClient:
    """Request/notify helpers bound to one launched app-server child."""

    def __init__(self, child: StreamChild) -> None:
        """Wrap a launched child; ids start at 1."""
        self.child = child
        self.last_id = 0

    def send_request(self, method: str, params: dict) -> tuple[int, float]:
        """Send without waiting; returns (id, send time)."""
        self.last_id += 1
        sent = self.child.send({"id": self.last_id, "method": method, "params": params})
        return self.last_id, sent

    def wait_response(self, request_id: int, timeout_s: float = 30) -> dict:
        """Response (result or error) with its receive time, or a timeout marker."""
        found = self.child.wait_event(is_response(request_id), timeout_s)
        if found is None:
            return {"timedOut": True}
        return {"at": found[0], "result": found[1].get("result"), "error": found[1].get("error")}

    def request(self, method: str, params: dict, timeout_s: float = 30) -> dict:
        """Send and wait for the response."""
        request_id, sent = self.send_request(method, params)
        return {"sentAt": sent, **self.wait_response(request_id, timeout_s)}

    def initialize(self) -> dict:
        """Protocol handshake: initialize request then initialized notification."""
        reply = self.request("initialize", {"clientInfo": CLIENT_INFO})
        self.child.send({"method": "initialized"})
        return reply

    def notes(self, method: str) -> list[tuple[float, dict]]:
        """Every notification of one method received so far."""
        return [(stamp, e) for stamp, e in self.child.snapshot() if e.get("method") == method]

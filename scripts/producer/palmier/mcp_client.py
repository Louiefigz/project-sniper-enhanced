#!/usr/bin/env python3
"""mcp_client — minimal HTTP JSON-RPC client for Palmier Pro's local MCP server.

Palmier Pro serves MCP at ``http://127.0.0.1:19789/mcp`` while the app is open
with a project. Responses arrive as SSE (``data:`` lines); the session id rides
the ``Mcp-Session-Id`` header. This is the productionized version of the
hand-driven e2e bridge that proved the integration (docs/PIPELINE.md).

No fallbacks: an MCP error, a dead server, or an unparseable result raises
``PalmierError`` with the server's words — the caller reports, never guesses.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Callable

DEFAULT_URL = "http://127.0.0.1:19789/mcp"
PROTOCOL_VERSION = "2025-06-18"


def emit(**fields) -> None:
    """Write one producer-style NDJSON event to stdout."""
    print(json.dumps(fields), flush=True)


class PalmierError(RuntimeError):
    """An MCP-level failure (transport, protocol, or tool error)."""


class PalmierWaiting(PalmierError):
    """A safe sync cannot start until the operator changes Palmier state."""


class PalmierClient:
    """One MCP session against a running Palmier Pro app."""

    def __init__(self, url: str = DEFAULT_URL, timeout_s: float = 180.0):
        self.url = url
        self.timeout_s = timeout_s
        self.session_id: str | None = None
        self._next_id = 0
        self._timeout_provider: Callable[[], float] | None = None

    def set_timeout_provider(
            self, provider: Callable[[], float] | None) -> None:
        """Refresh the timeout immediately before every protocol request."""
        self._timeout_provider = provider

    def _request_timeout(self) -> float:
        value = self._timeout_provider() \
            if self._timeout_provider is not None else self.timeout_s
        if value <= 0:
            raise PalmierError("Palmier MCP request deadline expired")
        return min(float(self.timeout_s), float(value))

    def handshake(self) -> None:
        """initialize → notifications/initialized. Raises if unreachable."""
        self._rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
            "clientInfo": {"name": "sniper-producer-push", "version": "1.0"},
        })
        self._rpc("notifications/initialized", {}, notification=True)

    def call(self, tool: str, arguments: dict | None = None) -> str:
        """tools/call → the result's concatenated text content.

        Raises ``PalmierError`` on a JSON-RPC error, an ``isError`` tool
        result, or an empty response.
        """
        resp = self._rpc("tools/call", {"name": tool,
                                        "arguments": arguments or {}})
        if resp is None:
            raise PalmierError(f"{tool}: no JSON-RPC response on the stream")
        if "error" in resp:
            raise PalmierError(f"{tool}: {json.dumps(resp['error'])[:500]}")
        result = resp.get("result", {})
        text = "".join(c.get("text", "") for c in result.get("content", [])
                       if c.get("type") == "text")
        if result.get("isError"):
            raise PalmierError(f"{tool}: tool error: {text[:500]}")
        return text

    def call_json(self, tool: str, arguments: dict | None = None):
        """``call`` + parse the text as JSON (Palmier results are JSON text)."""
        text = self.call(tool, arguments)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise PalmierError(
                f"{tool}: result is not JSON ({exc}): {text[:300]}") from exc

    def wait_media(self, media_ref: str, timeout_s: float = 300.0,
                   poll_s: float = 1.0) -> dict:
        """Poll get_media until ``media_ref`` finishes importing.

        Background imports (path/url) report ``generationStatus`` while
        unresolved; its absence means ready. ``failed`` or a timeout raises.
        """
        deadline = time.monotonic() + timeout_s
        while True:
            info = self.call_json("get_media", {"ids": [media_ref]})
            assets = info.get("assets", info if isinstance(info, list) else [])
            asset = next((a for a in assets if a.get("id") == media_ref),
                         assets[0] if len(assets) == 1 else None)
            if asset is None:
                raise PalmierError(f"get_media: {media_ref} not in library")
            status = asset.get("generationStatus")
            if status is None:
                return asset
            if status == "failed":
                raise PalmierError(f"import failed for {media_ref}")
            if time.monotonic() > deadline:
                raise PalmierError(
                    f"import timeout ({timeout_s}s) for {media_ref} "
                    f"(status {status})")
            time.sleep(poll_s)

    def close(self) -> None:
        """Terminate this MCP session with the protocol DELETE handshake."""
        session_id = self.session_id
        if session_id is None:
            return
        headers = {
            "Accept": "application/json, text/event-stream",
            "Mcp-Session-Id": session_id,
        }
        request = urllib.request.Request(
            self.url, headers=headers, method="DELETE")
        try:
            with urllib.request.urlopen(
                    request, timeout=self._request_timeout()) as response:
                if response.status not in {200, 202, 204}:
                    raise PalmierError(
                        f"Palmier MCP session DELETE returned {response.status}")
                response.read()
        except urllib.error.URLError as exc:
            raise PalmierError(
                f"Palmier MCP session {session_id} did not terminate: {exc}") from exc
        finally:
            self.session_id = None

    def _rpc(self, method: str, params: dict, notification: bool = False):
        body: dict = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notification:
            self._next_id += 1
            body["id"] = self._next_id
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(),
                                     headers=headers, method="POST")
        try:
            with urllib.request.urlopen(
                    req, timeout=self._request_timeout()) as r:
                if r.headers.get("Mcp-Session-Id"):
                    self.session_id = r.headers.get("Mcp-Session-Id")
                raw = r.read().decode()
        except urllib.error.URLError as exc:
            raise PalmierError(
                f"Palmier MCP unreachable at {self.url} ({exc}) — is the app "
                "open with a project?") from exc
        if notification:
            return None
        return self._parse_sse(raw)

    @staticmethod
    def _parse_sse(raw: str):
        """First JSON-RPC response object on an SSE stream (or raw JSON)."""
        for line in raw.splitlines():
            payload = line[5:].strip() if line.startswith("data:") else None
            if payload is None and line.strip().startswith("{"):
                payload = line.strip()   # non-SSE plain JSON body
            if not payload:
                continue
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and ("result" in obj or "error" in obj):
                return obj
        return None

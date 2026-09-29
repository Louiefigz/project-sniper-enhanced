"""Host conformance harness: stub model, WebSocket framing, evidence and launch shapes.

No host CLI is started and no provider is called; the stub binds loopback only.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from native_render_processes import ProcessIdentity
from studio.production.host_conformance import claude_host, death_probe, evidence, procs, ws_unix
from studio.production.host_conformance.codex_rpc import RpcClient, is_note
from studio.production.host_conformance.stream_child import EventLog
from studio.production.host_conformance.stub_model import (
    StubModel, StubScript, _blocks, _has_tool_result, _message, _sse_events)

SLEEP = {"command": "/bin/sleep 5", "description": "probe"}
# An empty proxy map: urlopen's macOS system-proxy lookup leaves two native threads in the test process,
# which a later single-thread measurement (test_native_proof_io) would inherit (X126).
LOOPBACK = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class StubModelTests(unittest.TestCase):
    """The loopback stub follows its script and records every request."""

    def test_tool_result_is_found_behind_a_trailing_reminder(self) -> None:
        body = {"messages": [{"role": "user", "content": "go"}, {"role": "assistant", "content": []},
                             {"role": "user", "content": [{"type": "tool_result"}]},
                             {"role": "user", "content": [{"type": "text", "text": "reminder"}]}]}
        self.assertTrue(_has_tool_result(body))

    def test_an_older_tool_result_does_not_count_for_a_new_prompt(self) -> None:
        body = {"messages": [{"role": "user", "content": [{"type": "tool_result"}]},
                             {"role": "assistant", "content": []}, {"role": "user", "content": "again"}]}
        self.assertFalse(_has_tool_result(body))

    def test_script_choices(self) -> None:
        script = StubScript(tool_input=SLEEP)
        blocks, stop = _blocks(script, {"tools": [{}], "messages": [{"role": "user", "content": "x"}]})
        self.assertEqual((blocks[0]["type"], blocks[0]["input"], stop), ("tool_use", SLEEP, "tool_use"))
        side, _ = _blocks(script, {"messages": [{"role": "user", "content": "x"}]})
        self.assertEqual(side, [{"type": "text", "text": "OK"}])

    def test_stream_events_rebuild_the_tool_input(self) -> None:
        script = StubScript(tool_input=SLEEP)
        blocks, stop = _blocks(script, {"tools": [{}], "messages": []})
        events = _sse_events(_message(script, blocks, stop))
        names = [name for name, _ in events]
        self.assertEqual(names[0], "message_start")
        self.assertEqual(names[-2:], ["message_delta", "message_stop"])
        partial = "".join(e["delta"].get("partial_json", "") for n, e in events if n == "content_block_delta")
        self.assertEqual(json.loads(partial), SLEEP)

    def test_loopback_roundtrip_and_log(self) -> None:
        stub = StubModel(StubScript()).start()
        try:
            request = urllib.request.Request(stub.base_url + "/v1/messages?beta=true",
                                             data=json.dumps({"stream": True, "messages": []}).encode())
            with LOOPBACK.open(request, timeout=5) as response:
                text = response.read().decode()
            with self.assertRaises(urllib.error.HTTPError) as refused:
                LOOPBACK.open(stub.base_url + "/v1/models", timeout=5)
            refused.exception.close()
        finally:
            stub.stop()
            stub.thread.join(timeout=5)
        self.assertFalse(stub.thread.is_alive())
        self.assertIn('"text": "OK"', text)
        self.assertTrue(stub.base_url.startswith("http://127.0.0.1:"))
        self.assertEqual([r["method"] for r in stub.requests()], ["POST", "GET"])


class WebSocketTests(unittest.TestCase):
    """Minimal RFC 6455 client framing and session behaviour."""

    def test_masked_frames_roundtrip_at_every_length_encoding(self) -> None:
        left, right = socket.socketpair()
        with left, right:
            for size in (5, 200, 70000):
                payload = os.urandom(size)
                sender = threading.Thread(target=left.sendall, args=(ws_unix._frame(ws_unix.TEXT, payload),))
                sender.start()
                self.assertEqual(ws_unix._read_frame(right), (ws_unix.TEXT, payload))
                sender.join()

    def test_session_handshake_ping_and_text(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="hc-"))
        self.addCleanup(shutil.rmtree, root, True)
        path = str(root / "s.sock")
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(path)
        server.listen(1)
        seen = {}
        thread = threading.Thread(target=_fake_server, args=(server, seen))
        thread.start()
        session = ws_unix.SocketSession(path, root / "raw.jsonl")
        found = session.wait_event(lambda e: e.get("method") == "hello", 5)
        session.send({"id": 1, "method": "ping-back"})
        thread.join(5)
        session.close_stdin()
        server.close()
        self.assertEqual(found[1]["params"], {"n": 1})
        self.assertEqual(seen["pong"], b"p")
        self.assertEqual(json.loads(seen["text"]), {"id": 1, "method": "ping-back"})


def _fake_server(server: socket.socket, seen: dict) -> None:
    """Accept one client: 101, a ping, a text frame; capture the pong and one client text."""
    conn, _ = server.accept()
    with conn:
        request = b""
        while b"\r\n\r\n" not in request:
            request += conn.recv(1)
        conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n\r\n")
        conn.sendall(bytes([0x80 | ws_unix.PING, 1]) + b"p")
        body = json.dumps({"method": "hello", "params": {"n": 1}}).encode()
        conn.sendall(bytes([0x80 | ws_unix.TEXT, len(body)]) + body)
        seen["pong"] = ws_unix._read_frame(conn)[1]
        seen["text"] = ws_unix._read_frame(conn)[1].decode()


class _EchoTransport(EventLog):
    """Transport double: every request is answered immediately with its id."""

    def reading(self) -> bool:
        """Always open."""
        return True

    def send(self, message: dict) -> float:
        """Echo a result for requests; notifications get no reply."""
        if "id" in message:
            self.record(json.dumps({"id": message["id"], "result": {"method": message["method"]}}))
        return self.elapsed()


class RpcAndEventTests(unittest.TestCase):
    """Request/response matching over any EventLog transport."""

    def test_requests_match_their_own_ids(self) -> None:
        client = RpcClient(_EchoTransport())
        first = client.request("a/one", {})
        second = client.request("b/two", {})
        self.assertEqual((first["result"], second["result"]), ({"method": "a/one"}, {"method": "b/two"}))
        self.assertEqual(client.last_id, 2)

    def test_note_predicate_and_raw_lines(self) -> None:
        log = _EchoTransport()
        log.record("not json\n")
        log.record(json.dumps({"method": "turn/completed", "params": {"threadId": "t"}}))
        self.assertEqual(log.snapshot()[0][1], {"_raw": "not json"})
        self.assertIsNotNone(log.wait_event(is_note("turn/completed", threadId="t"), 1))
        self.assertIsNone(log.wait_event(is_note("turn/completed", threadId="u"), 0.2))


class EvidenceAndLaunchTests(unittest.TestCase):
    """Neutral paths, refusal to record an environment, and exact launch shapes."""

    def test_paths_are_neutralized(self) -> None:
        scratch = Path(tempfile.gettempdir()) / "hc-scratch"
        neutral = evidence.Neutral(scratch)
        slug = "".join(c if c.isalnum() else "-" for c in str(scratch.resolve()))
        text = neutral.text(f"{scratch}/w {Path.home()}/x /p/{slug}-work {tempfile.gettempdir()}/y")
        self.assertNotIn(str(Path.home()), text)
        self.assertIn("<scratch>/w", text)
        self.assertIn("<scratch-slug>-work", text)

    def test_environment_is_never_written(self) -> None:
        with self.assertRaises(ValueError):
            evidence.write(Path(tempfile.gettempdir()) / "never.json", {"env": {}}, evidence.Neutral(Path("/x")))

    def test_prompt_precedes_the_variadic_tools_option(self) -> None:
        args = claude_host.argv("claude", claude_host.ClaudeTurn("s", prompt="Reply OK"))
        self.assertEqual(args[:3], ("claude", "-p", "Reply OK"))
        self.assertEqual(args[-2:], ("--tools", ""))
        streamed = claude_host.argv("claude", claude_host.ClaudeTurn("s", resume=True, tools=True))
        self.assertIn("--input-format", streamed)
        self.assertEqual(streamed[streamed.index("--resume") + 1], "s")

    def test_clean_env_drops_provider_and_host_session_variables(self) -> None:
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "x", "CLAUDE_CODE_SESSION_ID": "y"}):
            env = claude_host.clean_env()
        self.assertFalse([k for k in env if k.startswith(("ANTHROPIC", "CLAUDE", "OPENAI"))])
        with self.assertRaises(ValueError):
            claude_host.stub_env("https://api.example.com")


class ProcessAndDeathTests(unittest.TestCase):
    """Exact-identity descent and the delayed-restart observation clock."""

    def test_descendants_require_the_exact_root(self) -> None:
        rows = {10: (1, 10, "T0"), 11: (10, 11, "T1"), 12: (11, 11, "T2"), 20: (1, 20, "T3")}
        self.assertEqual(procs.descendants(ProcessIdentity(10, "T0", 10), rows), {11, 12})
        self.assertEqual(procs.descendants(ProcessIdentity(10, "other", 10), rows), set())

    def test_restart_runs_once_after_the_deadline(self) -> None:
        calls = []
        plan = death_probe.DeathPlan("x", Path("."), Path("."), 1, deadline_s=0.0, restart_s=0.0, observe_s=5)
        hooks = death_probe.DeathHooks(sample=dict, restart=lambda h: calls.append(h) or {"ok": 1})
        start = time.monotonic()
        observed = death_probe._observe(plan, hooks, {"child": None, "sleep": None})
        self.assertLess(time.monotonic() - start, 3)
        self.assertEqual(len(calls), 1)
        self.assertEqual(observed["restart"]["action"], {"ok": 1})
        self.assertIn("deadline", observed)


if __name__ == "__main__":
    unittest.main()

"""Codex app-server as a surviving host: a probe-owned unix-socket server outlives its client.

The observer starts its own `codex app-server --listen unix://PATH` (never the
operator's daemon or the desktop app's servers). A disposable coordinator
connects over WebSocket, starts a sleep turn and dies. At the delayed restart a
new client reattaches, reads the persisted turn, resumes the thread and sends
turn/interrupt; the probe then checks the terminal notification and whether the
sleep process was removed.
"""
from __future__ import annotations

import shutil
import signal
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from studio.production.host_conformance import claude_host, death_probe, procs
from studio.production.host_conformance.codex_probe import Probe
from studio.production.host_conformance.codex_rpc import RpcClient
from studio.production.host_conformance.stream_child import Launch, StreamChild
from studio.production.host_conformance.ws_unix import SocketSession

SERVER_FLAGS = ("--disable", "plugins", "--disable", "apps")
SLEEP_S = 93


@dataclass(frozen=True)
class SocketServer:
    """A probe-owned app-server listening on a short-path unix socket."""

    child: StreamChild
    path: str


def start_socket_server(probe: Probe) -> SocketServer:
    """Launch the server under TMPDIR (socket paths must fit SUN_LEN) and wait for the socket."""
    path = str(Path(tempfile.mkdtemp(prefix="sniper-hg-")) / "p.sock")
    argv = (probe.exe, "app-server", "--listen", f"unix://{path}", *SERVER_FLAGS)
    child = StreamChild(Launch(argv, probe.work, claude_host.clean_env(), probe.raw / "codex-socket-server.jsonl"))
    deadline = time.monotonic() + 15
    while not Path(path).exists() and time.monotonic() < deadline:
        time.sleep(0.2)
    if not Path(path).exists():
        raise RuntimeError(f"socket server did not listen: {child.stderr_tail(300)}")
    return SocketServer(child, path)


def stop_socket_server(server: SocketServer) -> int | None:
    """EOF, then TERM/KILL on the exact identity; remove the socket directory."""
    server.child.close_stdin()
    code = server.child.wait_exit(10)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if code is not None:
            break
        procs.signal_exact(server.child.identity, sig)
        code = server.child.wait_exit(5)
    shutil.rmtree(Path(server.path).parent, ignore_errors=True)
    return code


def _connect(probe: Probe, server: SocketServer, name: str) -> RpcClient:
    """New WebSocket client with the protocol handshake done."""
    client = RpcClient(SocketSession(server.path, probe.raw / f"{name}.jsonl"))
    client.initialize()
    return client


def _turns(reply: dict) -> list:
    """[turn id, status, item types] rows from a thread/read or thread/resume reply."""
    turns = ((reply.get("result") or {}).get("thread") or {}).get("turns") or []
    return [[t.get("id"), t.get("status"), [i.get("type") for i in t.get("items") or []]] for t in turns]


def reattach_and_interrupt(probe: Probe, server: SocketServer, handles: dict) -> dict:
    """Delayed restart: read, resume, interrupt, then confirm terminal state and cleanup."""
    client = _connect(probe, server, "codex-socket-reattach")
    thread = {"threadId": handles.get("threadId")}
    before = client.request("thread/read", {**thread, "includeTurns": True})
    resumed = client.request("thread/resume", thread, 60)
    sleep = procs.ProcessIdentity(**handles["sleep"]) if handles.get("sleep") else None
    alive_before = procs.alive(sleep)
    interrupt = client.request("turn/interrupt", {**thread, "turnId": handles.get("turnId")}, 30)
    done = client.child.wait_event(lambda e: e.get("method") == "turn/completed", 30)
    gone = procs.wait_gone(sleep, 15)
    after = client.request("thread/read", {**thread, "includeTurns": True})
    methods = [[s, e.get("method")] for s, e in client.child.snapshot() if e.get("method")][:40]
    client.child.close_stdin()
    return {"readBefore": _turns(before), "resumeError": resumed.get("error"),
            "resumeTurns": _turns(resumed), "sleepAliveBeforeInterrupt": alive_before,
            "interruptReply": interrupt,
            "turnCompleted": done and [done[0], done[1]["params"]["turn"].get("status")],
            "sleepGoneWithinS": gone, "readAfter": _turns(after), "notifications": methods}


def read_only(probe: Probe, server: SocketServer, handles: dict) -> dict:
    """Final replay read over a fresh client."""
    client = _connect(probe, server, "codex-socket-final")
    reply = client.request("thread/read", {"threadId": handles.get("threadId"), "includeTurns": True})
    client.child.close_stdin()
    return {"threadRead": _turns(reply), "error": reply.get("error")}


def socket_survival(probe: Probe) -> dict:
    """Whole scenario: own server, coordinator death, delayed reattach + interrupt, cleanup."""
    server = start_socket_server(probe)
    hooks = death_probe.DeathHooks(
        sample=dict, restart=lambda h: reattach_and_interrupt(probe, server, h),
        final=lambda h: read_only(probe, server, h),
        coordinator_args=("--sock", server.path, "--server-pid", str(server.child.proc.pid)),
        host=procs.as_dict(server.child.identity))
    try:
        record = death_probe.run(death_probe.DeathPlan("codex-socket", probe.work, probe.raw, SLEEP_S), hooks)
    finally:
        code = stop_socket_server(server)
    return {**record, "scenario": "codex-socket-coordinator-death", "serverArgv": list(server.child.launch.argv),
            "serverExit": code}

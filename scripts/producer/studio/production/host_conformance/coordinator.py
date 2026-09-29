"""Disposable coordinator for the coordinator-death scenario.

It launches one host child whose turn runs a unique sleep, writes the exact
handles it holds (child and sleep identities, session/thread/turn ids) and then
kills itself with SIGKILL, so nothing it owned gets a graceful shutdown. The
observer in death_probe.py watches what happens next.

Run from scripts/producer:
  python3 -m studio.production.host_conformance.coordinator --host claude|codex|codex-socket ...
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from studio.production.host_conformance import claude_host, claude_probe, codex_probe, codex_rpc, procs
from studio.production.host_conformance.ws_unix import SocketSession


def _claude(args: argparse.Namespace) -> dict:
    """Stream-input claude turn against the observer's loopback stub."""
    probe = claude_probe.Probe(claude_host.binary(), Path(args.work), Path(args.raw))
    session, child, tool, found, tree = claude_probe.sleep_turn(
        probe, args.stub_url, args.seconds, "claude-coordinator-death")
    return {"host": "claude", "session": session, "child": procs.as_dict(child.identity),
            "sleep": procs.as_dict(found), "toolUseAt": tool and tool[0], "tree": tree,
            "argv": list(child.launch.argv)}


def _codex(args: argparse.Namespace) -> dict:
    """Real app-server turn in the scratch directory."""
    probe = codex_probe.Probe(codex_rpc.binary(), Path(args.work), Path(args.raw))
    client = codex_probe.start_server(probe, "codex-coordinator-death")
    run = codex_probe.start_sleep_turn(client, probe, args.seconds)
    started = run["commandStarted"]
    return {"host": "codex", "threadId": run["threadId"], "turnId": run["turnId"],
            "child": procs.as_dict(client.child.identity), "sleep": procs.as_dict(run["sleep"]),
            "commandStartedAt": started and started[0], "tree": run["tree"],
            "argv": list(client.child.launch.argv)}


def _codex_socket(args: argparse.Namespace) -> dict:
    """Real turn through a WebSocket client to the observer's unix-socket app-server."""
    probe = codex_probe.Probe(codex_rpc.binary(), Path(args.work), Path(args.raw))
    session = SocketSession(args.sock, Path(args.raw) / "codex-socket-coordinator.jsonl")
    client = codex_rpc.RpcClient(session)
    client.initialize()
    server = procs.identity_of(args.server_pid)
    run = codex_probe.start_sleep_turn(client, probe, args.seconds, server)
    started = run["commandStarted"]
    return {"host": "codex-socket", "threadId": run["threadId"], "turnId": run["turnId"],
            "child": None, "sleep": procs.as_dict(run["sleep"]), "model": run["model"],
            "commandStartedAt": started and started[0], "tree": run["tree"]}


RUNNERS = {"claude": _claude, "codex": _codex, "codex-socket": _codex_socket}


def main() -> None:
    """Launch, record handles, then die without cleanup."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=tuple(RUNNERS), required=True)
    parser.add_argument("--work", required=True)
    parser.add_argument("--raw", required=True)
    parser.add_argument("--handles", required=True)
    parser.add_argument("--seconds", type=int, required=True)
    parser.add_argument("--stub-url", default="")
    parser.add_argument("--sock", default="")
    parser.add_argument("--server-pid", type=int, default=0)
    args = parser.parse_args()
    handles = RUNNERS[args.host](args)
    handles["coordinator"] = procs.as_dict(procs.identity_of(os.getpid()))
    Path(args.handles).write_text(json.dumps(handles))
    os.kill(os.getpid(), signal.SIGKILL)


if __name__ == "__main__":
    main()

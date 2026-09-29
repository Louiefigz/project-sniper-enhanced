"""Run host capability conformance scenarios and write one evidence file per scenario.

Maintainer qualification tooling for docs/producer/HOST_CAPABILITY_GATE.md. It
starts only its own host children in a scratch directory, never reads auth
files, never attaches to an existing session or app-server and never signals a
process it did not record. Claude scenarios other than claude-identity-no-key
use a loopback stub; Codex turn scenarios spend real subscription turns.

Run from scripts/producer:
  python3 -B -m studio.production.host_conformance.run_gate \\
      --work <scratch-dir> --out <evidence-dir> claude-session-binding codex-interrupt
"""
from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from studio.production.host_conformance import claude_host, claude_probe, codex_probe, codex_rpc
from studio.production.host_conformance import codex_socket_probe, death_probe, evidence
from studio.production.host_conformance.stub_model import StubModel

CLAUDE_SCENARIOS = ("claude-identity-no-key", "claude-session-binding", "claude-control-interrupt",
                    "claude-signal-sigint", "claude-signal-sigkill", "claude-coordinator-death",
                    "claude-resume-while-live")
CODEX_SCENARIOS = ("codex-identity", "codex-turn-duplicate", "codex-interrupt",
                   "codex-coordinator-death", "codex-socket-coordinator-death")
DEATH_SLEEP_S = {"claude": 67, "codex": 68}


def _claude(name: str, work: Path, raw: Path) -> dict:
    """Dispatch one Claude scenario."""
    probe = claude_probe.Probe(claude_host.binary(), work, raw)
    table = {"claude-identity-no-key": lambda: claude_probe.identity_without_key(probe),
             "claude-session-binding": lambda: claude_probe.session_binding(probe),
             "claude-control-interrupt": lambda: claude_probe.control_interrupt(probe),
             "claude-signal-sigint": lambda: claude_probe.signal_child(probe, signal.SIGINT, 304),
             "claude-signal-sigkill": lambda: claude_probe.signal_child(probe, signal.SIGKILL, 305),
             "claude-coordinator-death": lambda: _claude_death(work, raw),
             "claude-resume-while-live": lambda: claude_probe.resume_while_live(probe)}
    record = table[name]()
    record["hostVersion"] = claude_host.version(probe.exe)
    return record


def _claude_death(work: Path, raw: Path) -> dict:
    """Coordinator death against the loopback stub; the stub counts orphan model calls."""
    stub = StubModel(claude_probe.sleep_script(DEATH_SLEEP_S["claude"])).start()
    hooks = death_probe.DeathHooks(
        sample=lambda: {"stubRequests": len(stub.requests())},
        restart=lambda handles: {"transcript": claude_host.transcript(handles["session"])},
        coordinator_args=("--stub-url", stub.base_url))
    try:
        record = death_probe.run(death_probe.DeathPlan("claude", work, raw, DEATH_SLEEP_S["claude"]), hooks)
    finally:
        stub.stop()
    record["stubRequests"] = stub.requests()
    return record


def _codex_replay(probe: codex_probe.Probe, handles: dict) -> dict:
    """Read the thread's persisted turns from a fresh app-server this probe owns."""
    client = codex_probe.start_server(probe, "codex-death-replay")
    reply = client.request("thread/read", {"threadId": handles.get("threadId"), "includeTurns": True})
    code = codex_probe.stop_server(client)
    turns = ((reply.get("result") or {}).get("thread") or {}).get("turns") or []
    return {"threadRead": [[t.get("id"), t.get("status"), [i.get("type") for i in t.get("items") or []]]
                           for t in turns], "error": reply.get("error"), "replayServerExit": code}


def _codex(name: str, work: Path, raw: Path) -> dict:
    """Dispatch one Codex scenario."""
    probe = codex_probe.Probe(codex_rpc.binary(), work, raw)
    hooks = death_probe.DeathHooks(sample=dict, restart=lambda handles: _codex_replay(probe, handles))
    table = {"codex-identity": lambda: codex_probe.identity(probe),
             "codex-turn-duplicate": lambda: codex_probe.turn_and_duplicate(probe),
             "codex-interrupt": lambda: codex_probe.interrupt(probe),
             "codex-coordinator-death": lambda: death_probe.run(
                 death_probe.DeathPlan("codex", work, raw, DEATH_SLEEP_S["codex"]), hooks),
             "codex-socket-coordinator-death": lambda: codex_socket_probe.socket_survival(probe)}
    record = table[name]()
    record["hostVersion"] = claude_host.version(probe.exe)
    return record


def _cli(argv: list[str]) -> dict:
    """Run one read-only CLI status command in the clean environment."""
    done = subprocess.run(argv, capture_output=True, text=True, env=claude_host.clean_env(), timeout=60)
    return {"argv": argv, "exitCode": done.returncode, "stdout": done.stdout.strip()[:400],
            "stderr": done.stderr.strip()[:400]}


def host_status(_name: str, _work: Path, _raw: Path) -> dict:
    """Versions and sign-in status from each CLI's own status command; no model call, no auth file read."""
    claude, codex = claude_host.binary(), codex_rpc.binary()
    auth = _cli([claude, "auth", "status", "--json"])
    try:
        fields = json.loads(auth["stdout"])
    except ValueError:
        fields = {}
    auth["stdout"] = {k: fields.get(k) for k in ("loggedIn", "authMethod", "apiProvider") if k in fields}
    return {"scenario": "host-status", "modelCalls": 0, "claudeVersion": _cli([claude, "--version"]),
            "claudeAuthStatus": auth, "codexVersion": _cli([codex, "--version"]),
            "codexLoginStatus": _cli([codex, "login", "status"])}


def main() -> None:
    """Run the named scenarios in order and write their evidence records."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--work", required=True, help="scratch working directory for host children")
    parser.add_argument("--out", required=True, help="directory for scenario evidence JSON")
    parser.add_argument("scenarios", nargs="+", choices=("host-status",) + CLAUDE_SCENARIOS + CODEX_SCENARIOS)
    args = parser.parse_args()
    work, out = Path(args.work).resolve(), Path(args.out).resolve()
    raw = work.parent / "raw"
    work.mkdir(parents=True, exist_ok=True)
    neutral = evidence.Neutral(work.parent)
    for name in args.scenarios:
        runner = host_status if name == "host-status" else _claude if name in CLAUDE_SCENARIOS else _codex
        path = evidence.write(out / f"{name}.json", runner(name, work, raw), neutral)
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()

"""Coordinator death with restart deliberately delayed beyond a short deadline.

The observer starts coordinator.py, waits until it has written its handles and
killed itself, then samples the exact child and sleep identities once a second.
Nothing is done at the deadline: the question is what the host does on its own.
At the delayed restart the host-native replay surface is read; at the end every
identity this probe recorded is reconciled (terminated if still alive).
"""
from __future__ import annotations

import json
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from native_render_processes import ProcessIdentity
from studio.production.host_conformance import claude_host, procs

PRODUCER = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class DeathPlan:
    """Host, scratch paths, sleep length and the observation clock."""

    host: str
    work: Path
    raw: Path
    seconds: int
    deadline_s: float = 20.0
    restart_s: float = 45.0
    observe_s: float = 120.0


@dataclass(frozen=True)
class DeathHooks:
    """Host-specific extras for one death scenario.

    sample: cheap per-second reading. restart: what the delayed restart does with
    the recorded handles. final: read after reconciliation (defaults to restart).
    coordinator_args: extra coordinator flags. host: identity of a probe-owned host
    process that should be watched instead of the coordinator's own child.
    """

    sample: Callable[[], dict]
    restart: Callable[[dict], dict]
    final: Callable[[dict], dict] | None = None
    coordinator_args: tuple[str, ...] = ()
    host: dict | None = None


def _ident(row: dict | None) -> ProcessIdentity | None:
    """Identity from a handles row."""
    return None if not row else ProcessIdentity(**row)


def _start_coordinator(plan: DeathPlan, hooks: DeathHooks, handles_path: Path) -> subprocess.Popen:
    """Run the disposable coordinator as its own process with a clean environment."""
    argv = [sys.executable, "-B", "-m", "studio.production.host_conformance.coordinator",
            "--host", plan.host, "--work", str(plan.work), "--raw", str(plan.raw),
            "--handles", str(handles_path), "--seconds", str(plan.seconds)]
    argv += list(hooks.coordinator_args)
    env = {**claude_host.clean_env(), "PYTHONPATH": "."}
    log = open(plan.raw / f"{plan.host}-coordinator.log", "w")
    return subprocess.Popen(argv, cwd=PRODUCER, env=env, stdout=log, stderr=log)


def _await_death(coordinator: subprocess.Popen, handles_path: Path) -> tuple[dict, int | None]:
    """Handles written by the coordinator and its exit status (expected SIGKILL)."""
    try:
        code = coordinator.wait(timeout=240)
    except subprocess.TimeoutExpired:
        coordinator.kill()
        code = coordinator.wait()
    handles = json.loads(handles_path.read_text()) if handles_path.exists() else {}
    return handles, code


def _observe(plan: DeathPlan, hooks: DeathHooks, handles: dict) -> dict:
    """Sample liveness after death; record state changes, deadline and delayed restart."""
    child, sleep = _ident(handles.get("child")), _ident(handles.get("sleep"))
    start, changes, last, marks = time.monotonic(), [], None, {}
    while (elapsed := time.monotonic() - start) < plan.observe_s:
        state = {"childAlive": procs.alive(child), "sleepAlive": procs.alive(sleep), **hooks.sample()}
        if state != last:
            changes.append({"t": round(elapsed, 2), **state})
            last = state
        if elapsed >= plan.deadline_s and "deadline" not in marks:
            marks["deadline"] = {"t": round(elapsed, 2), **state}
        if elapsed >= plan.restart_s and "restart" not in marks:
            marks["restart"] = {"t": round(elapsed, 2), **state, "action": hooks.restart(handles)}
        if "restart" in marks and not state["childAlive"] and not state["sleepAlive"]:
            break
        time.sleep(1.0)
    return {"changes": changes, **marks}


def _reconcile(handles: dict, keys: tuple[str, ...]) -> dict:
    """Terminate any recorded identity still alive; report what the probe had to stop."""
    stopped = {}
    for key in keys:
        identity = _ident(handles.get(key))
        if not procs.alive(identity):
            continue
        procs.signal_exact(identity, signal.SIGTERM)
        gone = procs.wait_gone(identity, 5)
        if gone is None:
            procs.signal_exact(identity, signal.SIGKILL)
            gone = procs.wait_gone(identity, 5)
        stopped[key] = {"stoppedByProbe": True, "goneWithinS": gone}
    return stopped


def run(plan: DeathPlan, hooks: DeathHooks) -> dict:
    """Whole scenario: launch, death, observation, replay and reconciliation."""
    plan.raw.mkdir(parents=True, exist_ok=True)
    handles_path = plan.raw / f"{plan.host}-coordinator-handles.json"
    handles_path.unlink(missing_ok=True)
    coordinator = _start_coordinator(plan, hooks, handles_path)
    handles, code = _await_death(coordinator, handles_path)
    if hooks.host and handles:
        handles = {**handles, "client": handles.get("child"), "child": hooks.host}
    observed = _observe(plan, hooks, handles) if handles.get("child") else {}
    stopped = _reconcile(handles, ("sleep",) if hooks.host else ("sleep", "child"))
    return {"scenario": f"{plan.host}-coordinator-death", "plan": {
        "deadlineS": plan.deadline_s, "restartS": plan.restart_s, "observeS": plan.observe_s,
        "sleepSeconds": plan.seconds}, "coordinatorExit": code, "handles": handles,
        "afterDeath": observed, "reconciledByProbe": stopped,
        "finalReplay": (hooks.final or hooks.restart)(handles) if handles else None}

"""Claude Code CLI conformance scenarios. Each returns one evidence record.

Only `identity_without_key` reaches the real endpoint, with no credential in the
child environment. Every other scenario targets the loopback stub, so no model
or provider is called; those records prove host mechanics, never billing mode.
"""
from __future__ import annotations

import signal
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from studio.production.host_conformance import claude_host as ch
from studio.production.host_conformance import procs
from studio.production.host_conformance.stream_child import Launch, StreamChild
from studio.production.host_conformance.stub_model import StubModel, StubScript

OK_PROMPT = "Reply with the single word OK"
SLEEP_PROMPT = "Run `/bin/sleep {n}` with Bash in the foreground, then reply DONE"


@dataclass(frozen=True)
class Probe:
    """Resolved CLI, scratch working directory and raw-log directory."""

    exe: str
    work: Path
    raw: Path


def _launch(probe: Probe, turn: ch.ClaudeTurn, env: dict, name: str) -> StreamChild:
    """Start one print-mode child with its raw log under the probe's raw dir."""
    return StreamChild(Launch(ch.argv(probe.exe, turn), probe.work, env, probe.raw / f"{name}.jsonl"))


def _reap(child: StreamChild) -> int | None:
    """End a child this probe started: EOF, then TERM, then KILL on its exact identity."""
    child.close_stdin()
    code = child.wait_exit(10)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if code is not None:
            return code
        procs.signal_exact(child.identity, sig)
        code = child.wait_exit(5)
    return code


def _timeline(child: StreamChild, since: float = 0.0) -> list[list]:
    """Bounded (stamp, type, subtype) rows emitted at or after a time."""
    rows = [[stamp, e.get("type"), e.get("subtype")] for stamp, e in child.snapshot() if stamp >= since]
    return rows[:40]


def _handle(child: StreamChild) -> dict:
    """Exact launch handle: argv and pinned process identity."""
    return {"argv": list(child.launch.argv), "process": procs.as_dict(child.identity)}


def identity_without_key(probe: Probe) -> dict:
    """Real endpoint, clean environment: does the CLI find a subscription or fall back?"""
    session = str(uuid.uuid4())
    child = _launch(probe, ch.ClaudeTurn(session, prompt=OK_PROMPT), ch.clean_env(), "claude-identity-no-key")
    child.close_stdin()
    init = child.wait_event(ch.is_type("system", "init"), 60)
    result = child.wait_event(ch.is_type("result"), 90)
    code = _reap(child)
    assistant = [e for _, e in child.snapshot() if e.get("type") == "assistant"]
    return {"scenario": "claude-identity-no-key", "endpoint": "default (real)",
            "envKeys": sorted(ch.clean_env()), "handle": _handle(child),
            "init": ch.init_fields(init and init[1]), "result": ch.result_fields(result and result[1]),
            "assistantEvents": len(assistant), "exitCode": code,
            "stderrTail": child.stderr_tail(), "timeline": _timeline(child)}


def _stub_turn(probe: Probe, stub: StubModel, turn: ch.ClaudeTurn, name: str) -> dict:
    """One prompt-argument turn against the stub, with request accounting."""
    before = len(stub.requests())
    child = _launch(probe, turn, ch.stub_env(stub.base_url), name)
    child.close_stdin()
    init = child.wait_event(ch.is_type("system", "init"), 60)
    result = child.wait_event(ch.is_type("result"), 90)
    code = _reap(child)
    return {"handle": _handle(child), "init": ch.init_fields(init and init[1]),
            "result": ch.result_fields(result and result[1]), "exitCode": code,
            "stubRequests": stub.requests()[before:], "stderrTail": child.stderr_tail(),
            "timeline": _timeline(child)}


def session_binding(probe: Probe) -> dict:
    """Caller-supplied session id: first launch, duplicate launch, then resume attach."""
    session = str(uuid.uuid4())
    stub = StubModel(StubScript()).start()
    try:
        first = _stub_turn(probe, stub, ch.ClaudeTurn(session, prompt=OK_PROMPT), "claude-session-first")
        after_first = ch.transcript(session)
        duplicate = _stub_turn(probe, stub, ch.ClaudeTurn(session, prompt=OK_PROMPT), "claude-session-duplicate")
        resumed = _stub_turn(probe, stub, ch.ClaudeTurn(session, resume=True, prompt=OK_PROMPT),
                             "claude-session-resume")
    finally:
        stub.stop()
    return {"scenario": "claude-session-binding", "endpoint": "loopback stub",
            "envKeys": sorted(ch.stub_env(stub.base_url)), "session": session,
            "first": first, "transcriptAfterFirst": after_first, "duplicate": duplicate,
            "resume": resumed, "transcriptAfterResume": ch.transcript(session)}


def sleep_turn(probe: Probe, base_url: str, seconds: int, name: str) -> tuple:
    """Start a stream-input turn whose stub reply runs a unique sleep via Bash."""
    session = str(uuid.uuid4())
    child = _launch(probe, ch.ClaudeTurn(session, tools=True), ch.stub_env(base_url), name)
    child.send(ch.user_message(SLEEP_PROMPT.format(n=seconds)))
    tool = child.wait_event(ch.is_tool_use, 60)
    shapes = (("/bin/sleep", str(seconds)), ("sleep", str(seconds)))
    found = procs.find_descendant(procs.ArgvSearch(child.identity, shapes)) if tool else None
    tree = procs.tree(child.identity) if found else []
    return session, child, tool, found, tree


def sleep_script(seconds: int) -> StubScript:
    """Stub script whose first main-loop reply asks Bash to sleep."""
    return StubScript(tool_input={"command": f"/bin/sleep {seconds}",
                                  "description": "conformance probe sleep"})


def _settle_sleep(found) -> dict:
    """Record whether the host removed the sleep; remove it ourselves if not."""
    gone_after = procs.wait_gone(found, 15)
    leaked = found is not None and gone_after is None
    if leaked:
        procs.signal_exact(found, signal.SIGKILL)
    return {"identity": procs.as_dict(found), "goneWithinS": gone_after,
            "leakedAndKilledByProbe": leaked}


def control_interrupt(probe: Probe) -> dict:
    """Interrupt through the stdin control protocol while a Bash sleep runs."""
    stub = StubModel(sleep_script(301)).start()
    try:
        session, child, tool, found, tree = sleep_turn(probe, stub.base_url, 301, "claude-control-interrupt")
        time.sleep(2)
        wall, sent = time.time(), child.send(ch.interrupt_request("probe-interrupt-1"))
        ack = child.wait_event(lambda e: e.get("type") == "control_response", 15)
        result = child.wait_event(ch.is_type("result"), 30)
        sleep_state = _settle_sleep(found)
        alive_after_result = child.proc.poll() is None
        code = _reap(child)
    finally:
        stub.stop()
    return {"scenario": "claude-control-interrupt", "endpoint": "loopback stub",
            "session": session, "handle": _handle(child), "toolUseAt": tool and tool[0],
            "treeAtTool": tree, "interruptSentAt": sent, "ack": ack and [ack[0], ack[1]],
            "result": result and [result[0], ch.result_fields(result[1])],
            "sleep": sleep_state, "childAliveAfterResult": alive_after_result, "exitCode": code,
            "stubRequestsAfterInterrupt": [r for r in stub.requests() if r["at"] >= wall],
            "timelineAfterInterrupt": _timeline(child, sent), "transcript": ch.transcript(session)}


def signal_child(probe: Probe, sig: signal.Signals, seconds: int) -> dict:
    """Signal the CLI process itself while its Bash sleep runs."""
    stub = StubModel(sleep_script(seconds)).start()
    name = f"claude-signal-{sig.name.lower()}"
    try:
        session, child, tool, found, tree = sleep_turn(probe, stub.base_url, seconds, name)
        time.sleep(2)
        wall, sent = time.time(), child.elapsed()
        procs.signal_exact(child.identity, sig)
        code = child.wait_exit(20)
        sleep_state = _settle_sleep(found)
        code = code if code is not None else _reap(child)
    finally:
        stub.stop()
    return {"scenario": name, "endpoint": "loopback stub", "session": session,
            "handle": _handle(child), "toolUseAt": tool and tool[0], "treeAtTool": tree,
            "signalSentAt": sent, "exitCode": code, "sleep": sleep_state,
            "stubRequestsAfterSignal": [r for r in stub.requests() if r["at"] >= wall],
            "timelineAfterSignal": _timeline(child, sent), "transcript": ch.transcript(session)}


def resume_while_live(probe: Probe) -> dict:
    """A second process resumes a session whose first process is still mid-tool."""
    stub = StubModel(sleep_script(306)).start()
    try:
        session, child, tool, found, tree = sleep_turn(probe, stub.base_url, 306, "claude-resume-live-first")
        second = _stub_turn(probe, stub, ch.ClaudeTurn(session, resume=True, prompt=OK_PROMPT),
                            "claude-resume-live-second")
        first_alive, sleep_alive = child.proc.poll() is None, procs.alive(found)
        sent = child.send(ch.interrupt_request("probe-interrupt-2"))
        result = child.wait_event(ch.is_type("result"), 30)
        sleep_state = _settle_sleep(found)
        code = _reap(child)
    finally:
        stub.stop()
    return {"scenario": "claude-resume-while-live", "endpoint": "loopback stub", "session": session,
            "first": {"handle": _handle(child), "toolUseAt": tool and tool[0], "treeAtTool": tree,
                      "aliveAfterSecond": first_alive, "sleepAliveAfterSecond": sleep_alive,
                      "interruptSentAt": sent, "result": result and [result[0], ch.result_fields(result[1])],
                      "sleep": sleep_state, "exitCode": code},
            "second": second, "transcript": ch.transcript(session)}

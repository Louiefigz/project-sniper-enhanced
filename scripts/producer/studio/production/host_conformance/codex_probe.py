"""Codex app-server conformance scenarios. Each returns one evidence record.

`identity` makes no model call. `turn_and_duplicate` and `interrupt` each run
real subscription turns on a thread this probe created, in a scratch directory,
with tiny prompts. No existing thread or app-server is touched.
"""
from __future__ import annotations

import signal
import time
from dataclasses import dataclass
from pathlib import Path

from studio.production.host_conformance import codex_rpc as rpc_mod
from studio.production.host_conformance import procs
from studio.production.host_conformance.codex_rpc import RpcClient, is_note
from studio.production.host_conformance.stream_child import StreamChild

OK_PROMPT = "Reply with the single word OK"
SLEEP_PROMPT = "Run `sleep {n}` in the shell and wait for it to finish, then reply DONE"
PLACEHOLDER_KEY = "placeholder-not-a-key"


@dataclass(frozen=True)
class Probe:
    """Resolved CLI, scratch working directory and raw-log directory."""

    exe: str
    work: Path
    raw: Path


def start_server(probe: Probe, name: str, extra: tuple[str, ...] = ()) -> RpcClient:
    """Launch one app-server this probe owns and complete the handshake."""
    client = RpcClient(StreamChild(rpc_mod.launch(probe.exe, probe.work, probe.raw / f"{name}.jsonl", extra)))
    client.initialize()
    return client


def stop_server(client: RpcClient) -> int | None:
    """EOF first, then TERM/KILL on the exact identity this probe recorded."""
    client.child.close_stdin()
    code = client.child.wait_exit(15)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if code is not None:
            return code
        procs.signal_exact(client.child.identity, sig)
        code = client.child.wait_exit(5)
    return code


def default_model(client: RpcClient) -> str:
    """The installed CLI's own default model (the operator's configured model may need a newer CLI)."""
    reply = client.request("model/list", {})
    models = (reply.get("result") or {}).get("data") or []
    chosen = [m.get("id") for m in models if m.get("isDefault")]
    if not chosen:
        raise RuntimeError(f"model/list reported no default model: {reply.get('error')}")
    return chosen[0]


def thread_params(probe: Probe, model: str | None = None) -> dict:
    """Scratch-scoped thread: no approvals, workspace-write sandbox, persisted."""
    params = {"cwd": str(probe.work), "approvalPolicy": "never", "sandbox": "workspace-write"}
    return {**params, "model": model} if model else params


def turn_params(thread_id: str, text: str, client_id: str | None = None) -> dict:
    """Tiny text turn at low effort."""
    params = {"threadId": thread_id, "input": [{"type": "text", "text": text}], "effort": "low"}
    if client_id:
        params["clientUserMessageId"] = client_id
    return params


def _account(client: RpcClient) -> dict:
    """Account type and plan only; the email field is never recorded."""
    reply = client.request("account/read", {"refreshToken": False})
    account = (reply.get("result") or {}).get("account") or {}
    return {"type": account.get("type"), "planType": account.get("planType"),
            "requiresOpenaiAuth": (reply.get("result") or {}).get("requiresOpenaiAuth"),
            "error": reply.get("error")}


def _identity_variant(probe: Probe, name: str, extra: tuple[str, ...], key: bool) -> dict:
    """One app-server identity observation, optionally with a placeholder API key in env."""
    launch = rpc_mod.launch(probe.exe, probe.work, probe.raw / f"{name}.jsonl", extra)
    if key:
        launch = type(launch)(launch.argv, launch.cwd, {**launch.env, "OPENAI_API_KEY": PLACEHOLDER_KEY},
                              launch.raw_log)
    client = RpcClient(StreamChild(launch))
    client.initialize()
    account = _account(client)
    limits = client.request("account/rateLimits/read", {}).get("result") or {}
    code = stop_server(client)
    primary = (limits.get("rateLimits") or {})
    return {"argv": list(launch.argv), "envKeys": sorted(launch.env), "account": account,
            "rateLimits": {"primary": primary.get("primary"), "credits": primary.get("credits"),
                           "planType": primary.get("planType")}, "exitCode": code}


def identity(probe: Probe) -> dict:
    """Subscription identity with a clean env, with a placeholder key, and with a forced login method."""
    forced = ("-c", 'forced_login_method="chatgpt"')
    return {"scenario": "codex-identity", "modelCalls": 0,
            "clean": _identity_variant(probe, "codex-identity-clean", (), False),
            "placeholderKey": _identity_variant(probe, "codex-identity-key", (), True),
            "placeholderKeyForcedChatgpt": _identity_variant(probe, "codex-identity-forced", forced, True)}


def _turn_summary(client: RpcClient, turn_id: str) -> dict:
    """Started/completed notifications, usage and item kinds for one turn."""
    completed = [e for _, e in client.notes("turn/completed")
                 if ((e.get("params") or {}).get("turn") or {}).get("id") == turn_id]
    turn = completed[0]["params"]["turn"] if completed else {}
    usage = [[s, e["params"].get("tokenUsage")] for s, e in client.notes("thread/tokenUsage/updated")
             if e["params"].get("turnId") == turn_id]
    items = [e["params"]["item"].get("type") for _, e in client.notes("item/completed")
             if e["params"].get("turnId") == turn_id]
    return {"turnId": turn_id, "status": turn.get("status"), "durationMs": turn.get("durationMs"),
            "error": turn.get("error"), "usageUpdates": usage, "completedItemTypes": items}


def turn_and_duplicate(probe: Probe) -> dict:
    """Two turn/start calls with one clientUserMessageId, sent back to back on one thread."""
    client = start_server(probe, "codex-turn-duplicate")
    thread = client.request("thread/start", thread_params(probe, default_model(client)))
    thread_id = ((thread.get("result") or {}).get("thread") or {}).get("id")
    first_id, _ = client.send_request("turn/start", turn_params(thread_id, OK_PROMPT, "probe-msg-1"))
    second_id, _ = client.send_request("turn/start", turn_params(thread_id, OK_PROMPT, "probe-msg-1"))
    replies = [client.wait_response(first_id, 60), client.wait_response(second_id, 60)]
    turn_ids = [((r.get("result") or {}).get("turn") or {}).get("id") for r in replies]
    for turn_id in {t for t in turn_ids if t}:
        client.child.wait_event(lambda e, t=turn_id: e.get("method") == "turn/completed"
                                and e["params"]["turn"]["id"] == t, 120)
    replay = client.request("thread/read", {"threadId": thread_id, "includeTurns": True})
    code = stop_server(client)
    turns = ((replay.get("result") or {}).get("thread") or {}).get("turns") or []
    return {"scenario": "codex-turn-duplicate", "handle": procs.as_dict(client.child.identity),
            "threadId": thread_id, "startReplies": replies, "turnIds": turn_ids,
            "turns": [_turn_summary(client, t) for t in dict.fromkeys(t for t in turn_ids if t)],
            "threadReadTurns": [[t.get("id"), t.get("status"), len(t.get("items") or [])] for t in turns],
            "exitCode": code}


def _is_command_started(event: dict) -> bool:
    """item/started for a command execution."""
    item = (event.get("params") or {}).get("item") or {}
    return event.get("method") == "item/started" and item.get("type") == "commandExecution"


def start_sleep_turn(client: RpcClient, probe: Probe, seconds: int,
                     root: procs.ProcessIdentity | None = None) -> dict:
    """Thread + turn that runs a unique sleep; returns handles once the sleep process exists.

    root is the app-server process to search under; it defaults to the client's
    own launched child (stdio transport).
    """
    root = root or client.child.identity
    thread = client.request("thread/start", thread_params(probe, default_model(client)))
    thread_id = ((thread.get("result") or {}).get("thread") or {}).get("id")
    reply = client.request("turn/start", turn_params(thread_id, SLEEP_PROMPT.format(n=seconds)), 60)
    turn_id = ((reply.get("result") or {}).get("turn") or {}).get("id")
    started = client.child.wait_event(_is_command_started, 120)
    shapes = (("sleep", str(seconds)), ("/bin/sleep", str(seconds)))
    found = procs.find_descendant(procs.ArgvSearch(root, shapes, 20)) if started else None
    return {"threadId": thread_id, "turnId": turn_id, "model": (thread.get("result") or {}).get("model"),
            "commandStarted": started, "sleep": found, "tree": procs.tree(root) if found else []}


def _settle(found) -> dict:
    """Whether the host removed the sleep; remove it ourselves if not."""
    gone = procs.wait_gone(found, 15)
    leaked = found is not None and gone is None
    if leaked:
        procs.signal_exact(found, signal.SIGKILL)
    return {"identity": procs.as_dict(found), "goneWithinS": gone, "leakedAndKilledByProbe": leaked}


def interrupt(probe: Probe) -> dict:
    """turn/interrupt while the turn's shell command runs; confirm terminal state and cleanup."""
    client = start_server(probe, "codex-interrupt")
    run = start_sleep_turn(client, probe, 302)
    time.sleep(2)
    reply = client.request("turn/interrupt", {"threadId": run["threadId"], "turnId": run["turnId"]}, 30)
    done = client.child.wait_event(lambda e: e.get("method") == "turn/completed", 60)
    sleep_state = _settle(run["sleep"])
    command_done = [[s, (e["params"]["item"].get("status"), e["params"]["item"].get("exitCode"),
                         e["params"]["item"].get("processId"))]
                    for s, e in client.notes("item/completed")
                    if e["params"]["item"].get("type") == "commandExecution"]
    replay = client.request("thread/read", {"threadId": run["threadId"], "includeTurns": True})
    code = stop_server(client)
    turns = ((replay.get("result") or {}).get("thread") or {}).get("turns") or []
    started = run["commandStarted"]
    return {"scenario": "codex-interrupt", "handle": procs.as_dict(client.child.identity),
            "threadId": run["threadId"], "turnId": run["turnId"], "model": run["model"],
            "commandStartedAt": started and started[0],
            "commandItem": started and started[1]["params"]["item"], "treeAtCommand": run["tree"],
            "interruptReply": reply, "turnCompleted": done and [done[0], done[1]["params"]["turn"].get("status")],
            "commandItemsCompleted": command_done, "sleep": sleep_state,
            "usage": _turn_summary(client, run["turnId"]),
            "threadReadTurns": [[t.get("id"), t.get("status")] for t in turns], "exitCode": code}

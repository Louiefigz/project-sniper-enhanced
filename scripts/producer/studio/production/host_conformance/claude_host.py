"""Launch shapes and event readers for the Claude Code CLI in print mode.

Every child gets a minimal environment: no provider key, no variables that bind
it to a running desktop/host session. Stub runs add a loopback base URL and a
placeholder key so host mechanics can be exercised with no provider call.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

CLEAN_PATH = "{home}/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"
STUB_KEY = "stub-not-a-key"
QUIET = {"DISABLE_TELEMETRY": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
         "DISABLE_AUTOUPDATER": "1", "DISABLE_ERROR_REPORTING": "1"}


@dataclass(frozen=True)
class ClaudeTurn:
    """One print-mode invocation: session binding, input style and tool scope."""

    session: str
    resume: bool = False
    prompt: str | None = None
    tools: bool = False


def clean_env() -> dict[str, str]:
    """Minimal child environment with no provider or host-session variables."""
    home = str(Path.home())
    return {"HOME": home, "USER": os.environ.get("USER", ""),
            "LOGNAME": os.environ.get("USER", ""), "SHELL": "/bin/zsh",
            "TMPDIR": os.environ.get("TMPDIR", "/tmp"), "LANG": "en_US.UTF-8",
            "PATH": CLEAN_PATH.format(home=home)}


def stub_env(base_url: str) -> dict[str, str]:
    """Clean environment pointed at a loopback stub with a placeholder key."""
    if not base_url.startswith("http://127.0.0.1:"):
        raise ValueError("Stub runs may only target a loopback address")
    return {**clean_env(), **QUIET, "ANTHROPIC_BASE_URL": base_url,
            "ANTHROPIC_API_KEY": STUB_KEY}


def binary() -> str:
    """The installed claude CLI resolved on the clean PATH."""
    found = shutil.which("claude", path=clean_env()["PATH"])
    if found is None:
        raise FileNotFoundError("claude CLI is not on the clean PATH")
    return found


def version(exe: str) -> str:
    """Reported CLI version string."""
    return subprocess.run([exe, "--version"], capture_output=True, text=True,
                          env=clean_env(), timeout=30).stdout.strip()


def argv(exe: str, turn: ClaudeTurn) -> tuple[str, ...]:
    """Print-mode argv: stream-json out, safe mode, sonnet, exact session binding.

    A prompt argument goes directly after -p because --tools is variadic and
    would otherwise swallow it.
    """
    args = [exe, "-p"] + ([turn.prompt] if turn.prompt is not None else [])
    args += ["--output-format", "stream-json", "--verbose", "--safe-mode", "--model", "sonnet",
             "--resume" if turn.resume else "--session-id", turn.session]
    if turn.prompt is None:
        args += ["--input-format", "stream-json"]
    if turn.tools:
        return tuple(args + ["--permission-mode", "bypassPermissions", "--tools", "Bash"])
    return tuple(args + ["--tools", ""])


def user_message(text: str) -> dict:
    """One stream-json user message."""
    return {"type": "user", "parent_tool_use_id": None, "session_id": "",
            "message": {"role": "user", "content": [{"type": "text", "text": text}]}}


def interrupt_request(request_id: str) -> dict:
    """The control-protocol interrupt the Agent SDK sends on stdin."""
    return {"type": "control_request", "request_id": request_id,
            "request": {"subtype": "interrupt"}}


def is_type(kind: str, subtype: str | None = None):
    """Predicate for events of one type (and optional subtype)."""
    return lambda e: e.get("type") == kind and (subtype is None or e.get("subtype") == subtype)


def is_tool_use(event: dict) -> bool:
    """An assistant event that requests a tool."""
    content = (event.get("message") or {}).get("content") or []
    return event.get("type") == "assistant" and any(
        isinstance(b, dict) and b.get("type") == "tool_use" for b in content)


def init_fields(event: dict | None) -> dict | None:
    """Identity-relevant fields of the init event."""
    if event is None:
        return None
    keys = ("session_id", "apiKeySource", "model", "claude_code_version", "tools",
            "permissionMode", "cwd", "uuid")
    return {k: event.get(k) for k in keys if k in event}


def result_fields(event: dict | None) -> dict | None:
    """Terminal result fields: outcome, handles and per-turn usage."""
    if event is None:
        return None
    keys = ("subtype", "is_error", "result", "session_id", "uuid", "num_turns",
            "duration_ms", "duration_api_ms", "total_cost_usd", "usage", "modelUsage",
            "stop_reason", "terminal_reason", "errors")
    return {k: event.get(k) for k in keys if k in event}


def transcript(session: str) -> dict:
    """Locate the host's on-disk transcript for a session this probe created."""
    root = Path.home() / ".claude" / "projects"
    matches = sorted(root.glob(f"*/{session}.jsonl"))
    if not matches:
        return {"found": False}
    lines = matches[0].read_text(errors="replace").splitlines()
    kinds = [_line_kind(line) for line in lines]
    return {"found": True, "path": str(matches[0]), "lines": len(lines), "kinds": kinds[-12:]}


def _line_kind(line: str) -> str:
    """Compact type label for one transcript row."""
    try:
        row = json.loads(line)
    except ValueError:
        return "unparsed"
    content = (row.get("message") or {}).get("content")
    blocks = [b.get("type") for b in content if isinstance(b, dict)] if isinstance(content, list) else []
    return f"{row.get('type')}:{'+'.join(blocks)}" if blocks else str(row.get("type"))

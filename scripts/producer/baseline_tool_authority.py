#!/usr/bin/env python3
"""Attest the direct entrypoints and binaries used by a baseline command."""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

_CURRENT_ENTRYPOINTS = (
    "render.py",
    "assemble.py",
    "audit/audit_render.py",
    "current_render_oracle.py",
    "baseline_repeat_equivalence.py",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_file(raw: str, label: str) -> Path:
    candidate = Path(raw)
    if not candidate.is_absolute():
        located = shutil.which(raw)
        if not located:
            raise RuntimeError(f"cannot resolve baseline {label}: {raw}")
        candidate = Path(located)
    path = Path(os.path.realpath(candidate))
    if not path.is_file():
        raise RuntimeError(f"baseline {label} is not a file: {path}")
    return path


def _record(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": _sha256_file(path)}


def _command_script(command: tuple[str, ...]) -> Path | None:
    for token in command[1:]:
        candidate = Path(token)
        if candidate.is_absolute() and candidate.is_file():
            return Path(os.path.realpath(candidate))
        if token == "-c":
            return None
    return None


def observe_command_tools(command: tuple[str, ...]) -> dict:
    """Return exact direct tool authority for one command invocation."""
    executable = _resolve_file(command[0], "executable")
    script = _command_script(command)
    entrypoints = [_record(script)] if script is not None else []
    if script is not None and script.name == "current_full_path_baseline.py":
        producer = script.parent
        entrypoints.extend(
            _record(_resolve_file(str(producer / relative), "entrypoint"))
            for relative in _CURRENT_ENTRYPOINTS
        )
    external = [
        _record(_resolve_file(name, name)) for name in ("ffmpeg", "ffprobe")
    ]
    return {
        "executable": _record(executable),
        "entrypoints": entrypoints,
        "externalTools": external,
        "scope": "direct-entrypoints-not-transitive-source-closure",
    }


def require_unchanged(command: tuple[str, ...], expected: dict) -> None:
    """Reject a trace if a direct tool changes between observations."""
    if observe_command_tools(command) != expected:
        raise RuntimeError("baseline direct tool authority changed during capture")

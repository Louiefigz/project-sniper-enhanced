"""Diagnostic cut execution receipts, never a render or review approval."""
from __future__ import annotations

import contextvars
import hashlib
import json
import os
import platform
import shutil
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from cut_decode import eligible_source, execute
from cut_preview_io import file_identity
from fingerprint_io import file_sha256, write_json_atomic
from media_probe import run_ff

_ACTIVE: contextvars.ContextVar[CutExecution | None] = contextvars.ContextVar(
    "cut_execution", default=None)


def digest(value: object) -> str:
    """Full canonical digest for an execution key or sealed observation."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def tool_record(name: str) -> dict:
    """Bind a resolved binary and its reported build, once per cut invocation."""
    path = shutil.which(name)
    if path is None:
        raise RuntimeError(f"missing cut tool: {name}")
    path = os.path.realpath(path)
    return {"path": path, "sha256": file_sha256(path),
            "version": run_ff([path, "-version"])}


def code_records() -> list[dict]:
    """Reuse the dependency walker so newly imported helpers affect every key."""
    from render_effect_discovery import local_python_import_closure
    root = Path(__file__).resolve().parent
    paths = local_python_import_closure([root / "cut_speed.py"])
    return [{"path": str(path.relative_to(root)), "sha256": file_sha256(str(path))}
            for path in sorted(paths)]


def observe_sources(channels: dict) -> tuple[dict, dict]:
    """Reuse held audio-source hashes; observe silent-source bytes too."""
    records, identities = {}, {}
    for path, authority in channels.items():
        before = file_identity(os.stat(path))
        if authority is not None:
            authority.assert_stable()
        sha = authority.request.source_sha256 if authority is not None else file_sha256(path)
        if file_identity(os.stat(path)) != before:
            raise RuntimeError("cut source changed while execution inputs were observed")
        records[path] = {"path": os.path.realpath(path), "sha256": sha}
        identities[path] = before
    return records, identities


@dataclass
class CutExecution:
    """One invocation's exact execution context and completed part observations."""

    environment: dict
    sources: dict
    identities: dict
    hardware: set[str]
    parts: list[dict] = field(default_factory=list)
    current: dict | None = None
    stage_commands: list[dict] = field(default_factory=list)

    def begin(self, job: object, frames_before: int) -> None:
        """Bind both sides of a J-cut and the cumulative fractional frame clock."""
        paths = {job.src_path}
        if job.tail is not None:
            paths.add(job.tail.src_path)
        self.current = {"framesBefore": frames_before,
            "sources": [self.sources[path] for path in sorted(paths)],
            "frameRate": job.profile.fps_arg, "commands": [], "source": job.src_path}

    def command(self, command: list[str], runner: Callable) -> str:
        """Record actual picture, PCM clamp and concat commands after execution."""
        if self.current is None:
            result = runner(command)
            self.stage_commands.append({"argv": command, "exitCode": 0})
            return result
        picture = "libx264" in command
        accelerated = picture and self.current["source"] in self.hardware
        result = execute(command, runner, accelerated)
        if accelerated and result["decoder"] != "videotoolbox":
            self.hardware.discard(self.current["source"])
        self.current["commands"].append(result)
        return ""

    def finish(self, path: str, frames: int) -> None:
        """Seal only after the final PCM-clamped part exists."""
        record = dict(self.current)
        record.pop("source")
        record["videoFrames"] = frames
        key = digest({"environment": self.environment, **record})
        self.parts.append({**record, "executionKey": key,
                           "output": {"path": path, "sha256": file_sha256(path)}})
        self.current = None

    def publish(self, output: str) -> dict:
        """Refuse input drift and bind observations to the completed mezzanine."""
        for path, identity in self.identities.items():
            if file_identity(os.stat(path)) != identity:
                raise RuntimeError("cut execution source changed during rendering")
        record = {"schemaVersion": 1, "kind": "cut-execution-observation",
                  "environment": self.environment, "parts": self.parts,
                  "stageCommands": self.stage_commands,
                  "output": {"path": output, "sha256": file_sha256(output)},
                  "reviewCarryForward": False}
        record["receiptHash"] = digest(record)
        write_json_atomic(os.path.join(os.path.dirname(output), "cut_execution.json"), record, 2)
        return record


@contextmanager
def execution_scope(channels: dict, allow_hardware: bool) -> Iterator[CutExecution]:
    """Hold execution metadata only for the current render, never across calls."""
    sources, identities = observe_sources(channels)
    environment = {"tools": {name: tool_record(name) for name in ("ffmpeg", "ffprobe")},
                   "code": code_records(), "hostCpuCount": os.cpu_count(),
                   "system": platform.system(), "machine": platform.machine(),
                   "osRelease": platform.release()}
    hardware = {path for path in channels if allow_hardware and eligible_source(path)}
    recording = CutExecution(environment, sources, identities, hardware)
    token = _ACTIVE.set(recording)
    try:
        yield recording
    finally:
        _ACTIVE.reset(token)


def run_command(command: list[str], runner: Callable[[list[str]], str]) -> str:
    """Keep historical native-leaf test hooks and original guards intact."""
    recording = _ACTIVE.get()
    return recording.command(command, runner) if recording is not None else runner(command)

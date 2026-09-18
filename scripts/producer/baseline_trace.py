#!/usr/bin/env python3
"""Capture truthful first-run/repeat resource traces for named fixtures."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from baseline_fixture_authority import (
    FixtureAuthorityError,
    load_fixture,
    verify_current_authority,
)
from baseline_media_observation import observe_media
from baseline_repeat_equivalence import preserve_first_output, prove_repeat
from baseline_repeat_validation import PIXEL_IDENTICAL_CLASS
from baseline_tool_authority import observe_command_tools, require_unchanged
from baseline_trace_validation import (
    classify,
    classify_execution,
    validate_trace_document,
)
from current_render_oracle import CODEC_FLOOR_POLICY

SCHEMA_VERSION = 1
PARTIAL_OUTPUT_BYTES = 8_192


class BaselineTraceError(ValueError):
    """A baseline fixture or trace is not safe to classify."""


@dataclass(frozen=True)
class TraceConfig:
    fixture: dict[str, Any]
    command: tuple[str, ...]
    cwd: Path
    timeout_s: int


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_fixture(path: Path) -> dict[str, Any]:
    try:
        return load_fixture(path)
    except FixtureAuthorityError as exc:
        raise BaselineTraceError(str(exc)) from exc


def _verify_current_authority(config: TraceConfig) -> None:
    try:
        verify_current_authority(config.fixture, config.cwd)
    except FixtureAuthorityError as exc:
        raise BaselineTraceError(str(exc)) from exc


def _usage() -> resource.struct_rusage:
    return resource.getrusage(resource.RUSAGE_CHILDREN)


def _rss_bytes(value: int) -> int:
    return value if sys.platform == "darwin" else value * 1024


def _events(stdout: bytes) -> list[dict[str, Any]]:
    rows = []
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("event") in {
            "baseline_stage", "baseline_cache_state", "baseline_timing_coverage",
        }:
            rows.append(value)
    return rows


def _cache_state(events: list[dict[str, Any]]) -> str:
    states = [
        row.get("state") for row in events
        if row.get("event") == "baseline_cache_state"
    ]
    if len(states) != 1 or states[0] not in {"cold", "warm"}:
        return "unproved"
    return str(states[0])


def _artifact(root: Path, relative: str, observe: bool) -> dict[str, Any]:
    lexical = root / relative
    if lexical.is_symlink():
        return {"path": relative, "status": "missing"}
    path = lexical.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise BaselineTraceError(f"output path escapes trace cwd: {relative}") from exc
    if not path.is_file() or path.is_symlink():
        return {"path": relative, "status": "missing"}
    size = path.stat().st_size
    artifact = {
        "path": relative,
        "status": "present",
        "bytes": size,
        "sha256": _sha256_file(path),
    }
    if observe:
        artifact["media"] = observe_media(path)
    return artifact


def _execute(config: TraceConfig, label: str) -> tuple[bytes, bytes, int | None]:
    """Capture a timeout after subprocess.run kills/waits for its direct child."""
    try:
        result = subprocess.run(
            config.command, cwd=config.cwd, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=config.timeout_s, check=False,
            env={**os.environ, "SNIPER_BASELINE_RUN_LABEL": label},
        )
    except subprocess.TimeoutExpired as exc:
        return exc.stdout or b"", exc.stderr or b"", None
    return result.stdout, result.stderr, result.returncode


def _partial_output(value: bytes) -> dict[str, Any]:
    """Bound retained text while preserving the observed partial stream size."""
    return {"tail": value[-PARTIAL_OUTPUT_BYTES:].decode("utf-8", errors="replace"),
            "capturedBytes": len(value), "truncated": len(value) > PARTIAL_OUTPUT_BYTES}


def _run(config: TraceConfig, label: str) -> dict[str, Any]:
    before = _usage()
    started = datetime.now(timezone.utc)
    began = time.monotonic_ns()
    stdout, stderr, exit_code = _execute(config, label)
    elapsed_ms = (time.monotonic_ns() - began) // 1_000_000
    after = _usage()
    events = _events(stdout)
    return {
        "label": label,
        "startedAt": started.isoformat().replace("+00:00", "Z"),
        "wallMs": elapsed_ms,
        "childUserCpuMs": round((after.ru_utime - before.ru_utime) * 1000, 3),
        "childSystemCpuMs": round((after.ru_stime - before.ru_stime) * 1000, 3),
        "childrenCumulativeMaxRssBytes": _rss_bytes(after.ru_maxrss),
        "exitCode": exit_code,
        "stdoutSha256": _sha256(stdout),
        "stderrSha256": _sha256(stderr),
        **({"status": "timed_out", "timeoutSeconds": config.timeout_s,
            "terminalObserved": False, "descendantCleanup": "unverified",
            "partialStdout": _partial_output(stdout),
            "partialStderr": _partial_output(stderr)} if exit_code is None else {}),
        "cacheState": _cache_state(events),
        "events": events,
        "outputs": [
            {"path": relative, "status": "not-observed", "reason": "command-timed-out"}
            if exit_code is None else _artifact(
                config.cwd,
                relative,
                config.fixture["evidenceClass"] == "current-full-path-baseline",
            )
            for relative in config.fixture["outputPaths"]
        ],
    }


def capture_trace(config: TraceConfig) -> dict[str, Any]:
    """Capture first/repeat observations; a timeout prevents further execution."""
    tools = observe_command_tools(config.command)
    runs = []
    first_output = None
    for label in ("first-run", "immediate-repeat"):
        _verify_current_authority(config)
        require_unchanged(config.command, tools)
        runs.append(_run(config, label))
        _verify_current_authority(config)
        require_unchanged(config.command, tools)
        if runs[-1].get("status") == "timed_out":
            break  # Descendants may still be alive; never overlap an immediate repeat.
        if (label == "first-run"
                and config.fixture["evidenceClass"]
                == "current-full-path-baseline"
                and runs[-1]["exitCode"] == 0):
            first_output = preserve_first_output(config.cwd, config.fixture)
    repeat = (
        prove_repeat(config.cwd, config.fixture, first_output)
        if first_output is not None and runs[-1]["exitCode"] == 0 else None
    )
    require_unchanged(config.command, tools)
    execution = classify_execution(config.fixture, runs)
    trace = {
        "schemaVersion": SCHEMA_VERSION,
        "fixture": config.fixture,
        "classification": classify(config.fixture, runs, repeat),
        "executionObserved": {
            "complete": execution == config.fixture["evidenceClass"],
            "classification": execution,
        },
        "repeatEquivalence": repeat,
        "command": list(config.command),
        "toolAuthority": tools,
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "runs": runs,
    }
    if not validate_trace_document(trace):
        raise BaselineTraceError("captured baseline trace is internally invalid")
    return trace


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--cwd", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout-s", type=int, default=7_200)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or args.timeout_s < 1:
        raise BaselineTraceError("baseline command and positive timeout are required")
    cwd = args.cwd.resolve(strict=True)
    config = TraceConfig(
        fixture=_load_fixture(args.fixture.resolve(strict=True)),
        command=tuple(command),
        cwd=cwd,
        timeout_s=args.timeout_s,
    )
    trace = capture_trace(config)
    _write_json(args.output.resolve(), trace)
    print(json.dumps({
        "fixtureId": config.fixture["fixtureId"],
        "classification": trace["classification"],
        "output": str(args.output.resolve()),
    }, sort_keys=True))
    qualified = (
        trace["classification"] == config.fixture["evidenceClass"]
        or (
            config.fixture["evidenceClass"] == "current-full-path-baseline"
            and trace["classification"] in {
                CODEC_FLOOR_POLICY["pictureClaim"], PIXEL_IDENTICAL_CLASS,
            }
        )
    )
    return 0 if qualified else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BaselineTraceError, OSError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from error

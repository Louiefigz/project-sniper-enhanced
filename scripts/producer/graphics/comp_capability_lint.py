"""Owned, bounded upstream root-lint preflight; never a render qualification."""
from __future__ import annotations

import json
import math
import os
import stat
import time
from pathlib import Path

from cut_preview_io import file_hash, read_bytes, write_new
from graphics.comp_capability_artifact import (
    MOTION_DIR, _SHARED_RUNTIME_FILES, composition_paths,
    current_source_digest,
)
from graphics.render_tools import _validated_pin
from headless.process_runner import ProcessRequest, run_text
from headless.source_closure import discover_source_set

VERSION = "0.8.31"
MAX_SECONDS = 30
MAX_OUTPUT = 4 * 1024 * 1024
MAX_FILE = 8 * 1024 * 1024
MAX_NODE = 128 * 1024 * 1024
MAX_SNAPSHOT = 256 * 1024 * 1024
_ROOT = Path(MOTION_DIR).parents[1]
_RUNNER = Path(__file__).with_suffix(".mjs")
_PRELOAD = _ROOT / "scripts/producer/headless/node_isolated_user.cjs"
_PACKAGE = _ROOT / "node_modules/@hyperframes/lint"


def _remaining(end: float) -> float:
    """Charge setup, subprocess, validation, and publication to the caller end."""
    remaining = end - time.monotonic()
    if not math.isfinite(remaining) or remaining <= 0:
        raise RuntimeError("original capability root-lint deadline expired")
    return remaining


def _identity(path: Path) -> list[str]:
    """Require canonical regular single-link files and retain their original stat."""
    info = path.lstat()
    if path.resolve() != path or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise RuntimeError(f"root-lint input is not a canonical regular file: {path}")
    return [str(value) for value in (info.st_dev, info.st_ino, info.st_mode, info.st_uid,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)]


def _motion_paths() -> list[Path]:
    """Use the existing registered inventory and source closure, not a shadow lint."""
    motion = Path(MOTION_DIR)
    paths = {Path(value) for value in composition_paths()}
    budget = {"bytes": 64 * 1024 * 1024, "files": 512}
    sources = (_source_bytes(path.relative_to(motion).as_posix(), budget).decode() for path in sorted(paths))
    dependencies = discover_source_set(sources, lambda name: _source_bytes(name, budget))
    paths.update(motion / name for name in dependencies)
    paths.update(motion / name for name in _SHARED_RUNTIME_FILES)
    for name in ("icons", "reference", "vendor/gsap"):
        paths.update(path for path in (motion / name).rglob("*") if path.is_file())
    return sorted(paths)


def _source_bytes(relative: str, budget: dict) -> bytes:
    """Use the existing bounded stable reader for the existing closure parser."""
    if budget["files"] <= 0 or budget["bytes"] <= 0:
        raise RuntimeError("root-lint declared source closure exceeds its bound")
    raw = read_bytes(Path(MOTION_DIR) / relative, min(MAX_FILE, budget["bytes"]))
    budget["files"] -= 1
    budget["bytes"] -= len(raw)
    return raw


def lint_validator_state() -> dict:
    """Retain the installed official implementation and exact owned runner pins."""
    node = Path(_validated_pin("SNIPER_NODE_PATH", os.environ.get("SNIPER_NODE_PATH", "")))
    paths = {node, Path(__file__), _RUNNER, _PRELOAD, _ROOT / "package-lock.json"}
    for package in (_PACKAGE, _PACKAGE.parent / "parsers"):
        installed = json.loads(read_bytes(package / "package.json", MAX_FILE))
        if installed.get("version") != VERSION:
            raise RuntimeError("official lint/parser package version differs from the pinned release")
        paths.add(package / "package.json")
        paths.update((package / "dist").glob("*.js"))
    return {"version": VERSION, "node": str(node), "files": _files(paths, node), "parents": _parents(paths)}


def _files(paths: set[Path], node: Path | None = None, maximum: int = MAX_SNAPSHOT) -> dict:
    """Hash bounded original regular files and keep exact decimal stat identities."""
    if len(paths) > 512:
        raise RuntimeError("root-lint file inventory exceeds 512 files")
    identities = {path: _identity(path) for path in sorted(paths)}
    if sum(int(value[4]) for value in identities.values()) > maximum:
        raise RuntimeError("root-lint aggregate snapshot exceeds its byte bound")
    files = {}
    for path, identity in identities.items():
        hashed = file_hash(path, MAX_NODE if path == node else MAX_FILE)
        if _identity(path) != identity:
            raise RuntimeError("original root-lint input changed while hashing")
        files[str(path)] = {"identity": identity, "sha256": hashed}
    return files


def _parents(paths: set[Path]) -> dict:
    """Retain parent inode identities without binding unrelated directory mtimes."""
    return {str(parent): [str(parent.stat().st_dev), str(parent.stat().st_ino)]
            for path in paths for parent in path.parents}


def lint_source_state() -> dict:
    """Retain original official validator plus every existing motion dependency."""
    validator = lint_validator_state()
    paths = set(_motion_paths())
    if len(paths) + len(validator["files"]) > 512:
        raise RuntimeError("root-lint combined file inventory exceeds 512 files")
    remaining = MAX_SNAPSHOT - sum(int(row["identity"][4]) for row in validator["files"].values())
    files = {**validator["files"], **_files(paths, maximum=remaining)}
    parents = {**validator["parents"], **_parents(paths)}
    entries = [{"kind": Path(path).stem, "path": path, "sha256": files[path]["sha256"]}
               for path in composition_paths()]
    if not 1 <= len(entries) <= 128:
        raise RuntimeError("root-lint composition inventory is empty or exceeds 128 entries")
    return {"version": VERSION, "node": validator["node"], "motionSourceDigest": current_source_digest(),
            "files": files, "parents": parents, "entries": entries, "validator": validator}


def _unchanged(original: dict) -> None:
    """Preserve the original full before/after byte and inventory binding."""
    if lint_source_state() != original:
        raise RuntimeError("original root-lint source, inventory, validator or Node changed")
    _metadata_unchanged(original)


def _metadata_unchanged(original: dict) -> None:
    """Hold original identities without repeatedly hashing source or validator bytes."""
    _parents_unchanged(original["parents"])
    for name, held in original["files"].items():
        if _identity(Path(name)) != held["identity"]:
            raise RuntimeError("original root-lint source or validator changed")
    if composition_paths() != [entry["path"] for entry in original["entries"]] \
            or _validated_pin("SNIPER_NODE_PATH", os.environ.get("SNIPER_NODE_PATH", "")) != original["node"]:
        raise RuntimeError("original root-lint source, inventory, validator or Node changed")
    _parents_unchanged(original["parents"])


def _parents_unchanged(parents: dict) -> None:
    """Bracket each finite file sweep with the original canonical directory chain."""
    for name, expected in parents.items():
        path = Path(name)
        info = path.lstat()
        if path.resolve() != path or not stat.S_ISDIR(info.st_mode) \
                or [str(info.st_dev), str(info.st_ino)] != expected:
            raise RuntimeError("original root-lint parent directory changed")


def _request_unchanged(path: Path, identity: list[str]) -> None:
    """Retain the exact new-only request through process and publication tails."""
    if _identity(path) != identity:
        raise RuntimeError("original root-lint request changed")


def _environment(directory: Path) -> dict[str, str]:
    """No inherited credentials, socket, proxy, loader, or tool discovery variables."""
    user = directory / "user"
    user.mkdir(mode=0o700)
    return {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "TZ": "UTC", "NO_COLOR": "1",
            "DO_NOT_TRACK": "1", "HYPERFRAMES_NO_TELEMETRY": "1",
            "HYPERFRAMES_NO_UPDATE_CHECK": "1", "HYPERFRAMES_NO_AUTO_INSTALL": "1",
            "HYPERFRAMES_SKIP_SKILLS": "1", "SNIPER_ISOLATED_USER_DIR": str(user),
            "HEYGEN_CONFIG_DIR": str(user / "heygen")}


def _findings(result: dict) -> tuple[int, int, int]:
    """Check upstream diagnostic types/counts; never reinterpret its lint rules."""
    if type(result) is not dict or not {"ok", "errorCount", "warningCount", "infoCount", "findings"} <= result.keys():
        raise RuntimeError("malformed official root-lint findings")
    findings = result["findings"]
    if type(findings) is not list or len(findings) > 16384:
        raise RuntimeError("invalid official root-lint findings bound")
    for finding in findings:
        if type(finding) is not dict or finding.get("severity") not in {"error", "warning", "info"} \
                or not all(type(finding.get(key)) is str and finding[key] for key in ("code", "message")):
            raise RuntimeError("malformed official root-lint finding")
    counts = tuple(sum(row["severity"] == severity for row in findings) for severity in ("error", "warning", "info"))
    declared = tuple(result[key] for key in ("errorCount", "warningCount", "infoCount"))
    if any(type(value) is not int for value in declared) or declared != counts or result["ok"] is not (counts[0] == 0):
        raise RuntimeError("official root-lint counts disagree with retained findings")
    return counts


def _unique(pairs: list[tuple]) -> dict:
    """Do not accept duplicate JSON keys in a subprocess's structured result."""
    value = dict(pairs)
    if len(value) != len(pairs):
        raise RuntimeError("duplicate key in official root-lint output")
    return value


def _row_counts(row: object, entry: dict) -> tuple[int, int, int]:
    """Join one actual upstream root result to the exact original entry bytes."""
    if type(row) is not dict or set(row) != {"kind", "path", "sha256", "result"} \
            or {key: row[key] for key in entry} != entry:
        raise RuntimeError("official root-lint inventory differs from original entries")
    result = row["result"]
    if type(result) is not dict or set(result) != {"results", "totalErrors", "totalWarnings", "totalInfos"} \
            or type(result["results"]) is not list or len(result["results"]) != 1:
        raise RuntimeError("official root-lint did not return one root result")
    selected = result["results"][0]
    if type(selected) is not dict or set(selected) != {"file", "contentHash", "result"} \
            or selected["file"] != f"compositions/{entry['kind']}.html" \
            or selected["contentHash"] != entry["sha256"][:16]:
        raise RuntimeError("official root-lint root content/path changed")
    counts = _findings(selected["result"])
    declared = tuple(result[key] for key in ("totalErrors", "totalWarnings", "totalInfos"))
    if any(type(value) is not int for value in declared) or counts != declared:
        raise RuntimeError("official root-lint aggregate counts disagree")
    return counts


def _result(raw: str, request_sha: str, entries: list[dict]) -> dict:
    """Refuse malformed/partial results and forbidden attempts before any render."""
    value = json.loads(raw, object_pairs_hook=_unique)
    expected = {"schemaVersion", "scope", "version", "requestSha256", "rows", "blocked", "deniedAttempts", "elapsedMs"}
    if type(value) is not dict or set(value) != expected or type(value["schemaVersion"]) is not int \
            or value["schemaVersion"] != 1 or value["scope"] != "official-root-lint-not-render-or-approval" \
            or value["version"] != VERSION or value["requestSha256"] != request_sha:
        raise RuntimeError("malformed or mixed official root-lint output")
    if type(value["rows"]) is not list or len(value["rows"]) != len(entries) \
            or value["deniedAttempts"] != [] or type(value["blocked"]) is not bool \
            or type(value["elapsedMs"]) not in (float, int) or not 0 <= value["elapsedMs"] <= MAX_SECONDS * 1000:
        raise RuntimeError("partial, unbounded, or forbidden official root-lint output")
    counts = [_row_counts(row, entry) for row, entry in zip(value["rows"], entries)]
    if value["blocked"] is not any(row[0] for row in counts):
        raise RuntimeError("official strict-error render gate disagrees")
    return value


def preflight_root_lint(root: Path, deadline: float) -> dict:
    """Run once under the original cohort end, retaining success and failure facts."""
    started = time.monotonic()
    _remaining(deadline)
    end = min(deadline, started + MAX_SECONDS)
    directory = root / "root-lint"
    directory.mkdir(mode=0o700)
    outcome = {"scope": "static-preflight-not-render-or-approval", "passed": False}
    try:
        original = lint_source_state()
        request = {"schemaVersion": 1, "version": VERSION, "motion": MOTION_DIR,
                   "packageRoot": str(_PACKAGE), "entries": original["entries"]}
        write_new(directory / "request.json", request)
        request_sha = file_hash(directory / "request.json")
        request_identity = _identity(directory / "request.json")
        environment = _environment(directory)
        _unchanged(original)
        process = ProcessRequest((original["node"], "--require", str(_PRELOAD), str(_RUNNER),
            str(directory / "request.json"), request_sha), "", str(_ROOT), environment,
            _remaining(end), max_output_bytes=MAX_OUTPUT)
        completed = run_text(process)
        write_new(directory / "process.json", {"returncode": completed.returncode,
            "stdout": completed.stdout, "stderr": completed.stderr})
        result = _result(completed.stdout, request_sha, original["entries"])
        _unchanged(original)
        _request_unchanged(directory / "request.json", request_identity)
        _remaining(end)
        if completed.returncode != 0 or completed.stderr or result["blocked"]:
            raise RuntimeError("official root-lint strict errors or forbidden work; see retained process.json")
        outcome.update({"passed": True, "sourceState": original, "result": result})
        outcome["elapsedMs"] = round((time.monotonic() - started) * 1000)
        write_new(directory / "result.json", outcome)
        _metadata_unchanged(original)
        _request_unchanged(directory / "request.json", request_identity)
        _remaining(end)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        outcome["passed"] = False
        outcome["error"] = f"{type(error).__name__}: {error}"[:4000]
        outcome["elapsedMs"] = round((time.monotonic() - started) * 1000)
        write_new(directory / "failure.json", outcome)
        raise
    return outcome

"""Disposable-project lifecycle and retained evidence for live acceptance."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from palmier.desktop_state import JOURNAL_NAME, STATE_NAME, pointer_path
from palmier.live_acceptance_media import validate_media_authority
from palmier.live_acceptance_project_safety import (
    active_project, capture_prior, require_disposable_bundle,
    restore_project, validate_protected_path,
)
from palmier.mcp_client import PalmierError
from palmier.process_deadline import process_timeout
from palmier.timeline_authority import atomic_write_record

FORMATS = {"short": "9:16", "long": "16:9"}
QUALITIES = {
    ("1080p", "9:16"): (1080, 1920),
    ("1080p", "16:9"): (1920, 1080),
    ("720p", "9:16"): (720, 1280),
    ("720p", "16:9"): (1280, 720),
}
@dataclass(frozen=True)
class LiveAcceptanceConfig:
    """Explicit immutable inputs for one short or long live cohort."""

    repo: str
    out_dir: str
    plan_path: str
    repair_plan_path: str
    manifest_path: str
    bootstrap_path: str
    transcripts_dir: str
    evidence_path: str
    format: str
    fps: int
    aspect: str
    quality: str
    prefix: str
    timeout_s: float = 180.0
    mode: str = "build"
    reviews_path: str | None = None
    cleanup_timeout_s: float = 120.0
    cadence_approval_path: str | None = None
    cadence_approval_digest: str | None = None
    protected_project_path: str | None = None
def _regular(path: str, label: str) -> str:
    absolute = os.path.abspath(path)
    if not os.path.isfile(absolute) or os.path.islink(absolute):
        raise PalmierError(f"{label} is not a regular file: {absolute}")
    return absolute


def validate_config(config: LiveAcceptanceConfig) -> dict:
    """Fail before MCP if format, paths, bootstrap, or authority collide."""
    expected_aspect = FORMATS.get(config.format)
    if expected_aspect is None or config.aspect != expected_aspect:
        raise PalmierError(
            f"{config.format!r} acceptance requires aspect {expected_aspect!r}")
    if isinstance(config.fps, bool) or config.fps <= 0:
        raise PalmierError("live acceptance fps must be a positive integer")
    canvas = QUALITIES.get((config.quality, config.aspect))
    if canvas is None:
        raise PalmierError("live acceptance quality/aspect is unsupported")
    if config.mode not in {"build", "resume"}:
        raise PalmierError("live acceptance mode must be build or resume")
    paths = {
        "plan": _regular(config.plan_path, "plan"),
        "repairPlan": _regular(config.repair_plan_path, "repair plan"),
        "manifest": _regular(config.manifest_path, "manifest"),
        "bootstrap": _regular(config.bootstrap_path, "bootstrap"),
    }
    _validate_directories(config)
    media = validate_media_authority(config, paths, canvas)
    return {"paths": paths, **media,
            "canvas": list(canvas), "projectRate": f"{config.fps}/1"}


def _validate_directories(config: LiveAcceptanceConfig) -> None:
    for path, label in ((config.repo, "repo"), (config.out_dir, "out dir"),
                        (config.transcripts_dir, "transcripts dir")):
        if not os.path.isdir(path) or os.path.islink(path):
            raise PalmierError(f"live acceptance {label} is unavailable: {path}")
    if not os.path.isfile(os.path.join(config.out_dir, "final.mp4")):
        raise PalmierError("live acceptance out dir has no approved final.mp4")
    authority = [os.path.join(config.out_dir, name)
                 for name in (STATE_NAME, JOURNAL_NAME)]
    if config.mode == "build" and any(
            os.path.lexists(path) for path in authority):
        raise PalmierError(
            "live acceptance out dir already contains Desktop authority")
    if config.mode == "build" and os.path.lexists(config.evidence_path):
        raise PalmierError("live acceptance evidence path already exists")
    if config.mode == "resume" and (
            not all(os.path.isfile(path) and not os.path.islink(path)
                    for path in authority)
            or not os.path.isfile(config.evidence_path)
            or os.path.islink(config.evidence_path)):
        raise PalmierError("live acceptance resume authority is unavailable")
    if config.mode == "resume":
        _regular(str(config.reviews_path), "rendered reviews")
    if not config.prefix.strip() or "/" in config.prefix or len(config.prefix) > 72:
        raise PalmierError("live acceptance project prefix is unsafe")
    if config.timeout_s <= 0:
        raise PalmierError("live acceptance timeout must be positive")
    if config.cleanup_timeout_s <= 0:
        raise PalmierError("live acceptance cleanup timeout must be positive")
    validate_protected_path(config.protected_project_path)


def _backup(path: str) -> dict:
    if not os.path.lexists(path):
        return {"path": path, "existed": False}
    if os.path.islink(path) or not os.path.isfile(path):
        raise PalmierError(f"refusing to replace unsafe local state {path}")
    data = Path(path).read_bytes()
    return {"path": path, "existed": True,
            "sha256": hashlib.sha256(data).hexdigest(),
            "contentB64": base64.b64encode(data).decode("ascii")}


def restore_backup(record: dict) -> None:
    """Restore one exact local file snapshot without following symlinks."""
    path = record.get("path")
    if not isinstance(path, str) or os.path.islink(path):
        raise PalmierError("local-state backup has an unsafe destination")
    if record.get("existed") is not True:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        return
    raw = base64.b64decode(str(record.get("contentB64")), validate=True)
    if hashlib.sha256(raw).hexdigest() != record.get("sha256"):
        raise PalmierError("local-state backup is corrupt")
    temporary = f"{path}.{os.getpid()}.acceptance-restore"
    with open(temporary, "xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


class Evidence:
    """Atomically checkpoint facts so cleanup/failure evidence survives."""

    def __init__(self, config: LiveAcceptanceConfig, preflight: dict):
        self.path = config.evidence_path
        self.value = {
            "schemaVersion": 1, "kind": "p5-palmier-live-acceptance",
            "status": "running", "runId": str(uuid.uuid4()),
            "startedAt": time.time(), "config": asdict(config),
            "preflight": preflight, "phases": {}, "cleanup": {},
            "pointerBackup": _backup(pointer_path(config.repo)),
            "sidecarBackup": _backup(
                os.path.join(config.out_dir, "palmier.sync.json")),
        }
        self.save()

    def save(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        atomic_write_record(self.path, self.value)

    def phase(self, name: str, value: object) -> None:
        self.value["phases"][name] = value
        self.save()

    def fail(self, exc: BaseException) -> None:
        self.value.update({"status": "failed", "error": {
            "type": type(exc).__name__, "message": str(exc)}})
        self.save()

    @classmethod
    def resume(cls, config: LiveAcceptanceConfig, preflight: dict) -> "Evidence":
        """Open one retained review-required cohort without replacing evidence."""
        try:
            value = json.loads(Path(config.evidence_path).read_text(
                encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PalmierError(
                f"live acceptance resume evidence is unreadable: {exc}") from exc
        if not isinstance(value, dict) \
                or value.get("kind") != "p5-palmier-live-acceptance" \
                or value.get("status") not in {"review-required",
                                               "review-mismatch"}:
            raise PalmierError(
                "live acceptance evidence is not awaiting rendered review")
        original = value.get("config") or {}
        keys = (
            "repo", "out_dir", "plan_path", "repair_plan_path",
            "manifest_path", "bootstrap_path", "transcripts_dir",
            "evidence_path", "format", "fps", "aspect", "quality", "prefix",
            "cadence_approval_path", "cadence_approval_digest",
            "protected_project_path",
        )
        current = asdict(config)
        if any(original.get(key) != current.get(key) for key in keys) \
                or value.get("preflight") != preflight:
            raise PalmierError("live acceptance resume inputs changed")
        self = cls.__new__(cls)
        self.path, self.value = config.evidence_path, value
        self.value["resume"] = {
            "startedAt": time.time(),
            "pointerBackup": _backup(pointer_path(config.repo)),
            "sidecarBackup": _backup(
                os.path.join(config.out_dir, "palmier.sync.json")),
        }
        self.value["status"] = "resuming"
        self.save()
        return self


def disposable_name(config: LiveAcceptanceConfig, run_id: str) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    return f"{config.prefix} {config.format} {stamp} {run_id[:8]}"


def created_project(client: Any, name: str,
                    prior_paths: set[str]) -> dict:
    """Resolve and fence the one project just created by this run."""
    active = active_project(client.call_json("get_projects", {}))
    if not isinstance(active, dict) or active.get("name") != name:
        raise PalmierError("new disposable Palmier project is not active")
    path = active.get("path")
    require_disposable_bundle(path, active.get("name"), prior_paths)
    if active.get("isAccessible") is not True:
        raise PalmierError("new Palmier project is not accessible")
    return active


def trash_disposable(project: dict | None, prefix: str) -> bool:
    """Finder-trash only a returned .palmier bundle with this exact prefix."""
    path = project.get("path") if isinstance(project, dict) else None
    if not isinstance(path, str) or not os.path.exists(path):
        return False
    name = project.get("name")
    try:
        require_disposable_bundle(path, name)
    except PalmierError:
        raise PalmierError(f"refusing to trash non-disposable project {path}")
    if not isinstance(name, str) or not name.startswith(prefix):
        raise PalmierError(f"refusing to trash non-disposable project {path}")
    script = f'tell application "Finder" to delete POSIX file {json.dumps(path)}'
    subprocess.run(
        ["osascript", "-e", script], check=True,
        capture_output=True, text=True, timeout=process_timeout(60.0))
    if os.path.exists(path):
        raise PalmierError("Finder did not remove the disposable project path")
    return True

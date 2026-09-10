"""Owned full-source observation isolation; no media output or grade authority.

The caller must hold the project/resource lease and verify admitted source and
declaration parents before/after. This low-level execution receipt alone does
not authorize grading. V1 work is capped at 120s; explicitly selected v2 at
1200s. Mandatory exact-resource cleanup remains separately bounded at 90s.
"""
from __future__ import annotations

import json
import math
import os
import signal
import stat
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from color.deadline import require_time, wall_budget
from color.grade_observation_profile import observation_profile, parse_request
from cut_preview_io import digest, file_hash, read_bytes, real_directory, write_new
from headless.container_policy import (
    DockerRuntime, attest_image, reconcile_launch_abort, remove_container, required_runtime,
)
from headless.external_media_probe import _launch
from headless.external_media_probe_policy import (
    MediaProbeLimits, NODE_PROBE, PROBE_CPUS, PROBE_MEMORY_MIB, attest_probe_container, container_command,
)
from headless.network_probe import probe_container
from headless.owned_result_wait import OwnedResultWait, wait_owned_result
from headless.grade_launch_intent import HeldGradeLaunch, OwnedGradeLaunch, hold_grade_launch
from headless.grade_observation_phase import OwnedGradePhase, select_grade_phase
from render_effect_discovery import local_python_import_closure

WORKER = Path(__file__).with_name("grade_observation_worker.js")
POLICY = "sniper-private-grade-observation-v1"


@dataclass(frozen=True)
class _GradeInvocation:
    """Private optional launch ownership; never renew the caller's work clock."""

    deadline: float | None
    launch: HeldGradeLaunch | None = None


def implementation_sources() -> list[dict]:
    """Capture validator/policy dependencies, not only the worker's filename."""
    root = Path(__file__).resolve().parents[1]
    paths = local_python_import_closure([Path(__file__), root / "color/grade_frame_adapter.py",
                                       root / "color/grade_observation_read.py"])
    paths.extend([WORKER, Path(__file__).with_name("render_image_approval.json")])
    return [{"path": str(path), "sha256": file_hash(path)} for path in sorted(set(paths))]


class GradeIsolationError(RuntimeError):
    """Never release caller leases unless exact owned cleanup is proved."""

    def __init__(self, message: str, evidence: dict) -> None:
        super().__init__(message)
        self.evidence = evidence
        self.cleanup_verified = evidence["cleanupVerified"]


def _request(value: dict) -> dict:
    """Bound fixed source identity/count/time; never accept executable paths."""
    return parse_request(value)


def _directory(path: Path) -> None:
    """Require a new caller-owned private attempt without following links."""
    real_directory(path)
    info = path.lstat()
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077 or list(path.iterdir()):
        raise RuntimeError("grade observation requires an empty private owned attempt")


def _launch_command(runtime, context: tuple, request: dict) -> tuple[list[str], str]:
    """Use the current attested two-mount, 4CPU/768MiB/no-network boundary."""
    directory, name, source = context
    if PROBE_CPUS != 4 or PROBE_MEMORY_MIB != 768:
        raise RuntimeError("grade observation resource compatibility changed")
    command = container_command(runtime, str(directory), name, source, MediaProbeLimits())
    if command.count(NODE_PROBE) != 1:
        raise RuntimeError("grade observation pinned probe compatibility changed")
    worker = read_bytes(WORKER, 128 * 1024)
    return command[:command.index(NODE_PROBE)] + [worker.decode("utf8"), json.dumps(request)], file_hash(WORKER)


def _read_worker_result(config_dir: str) -> str | None:
    """Preserve canonical-parent, no-follow, bounded raw-publication reads."""
    try:
        return read_bytes(Path(config_dir) / "result" / "result.json", 64 * 1024).decode("utf8")
    except FileNotFoundError:
        return None


def _wait(runtime: DockerRuntime, config_dir: str, container_id: str, deadline: float) -> dict:
    """Keep structured worker failures and parsing within the original clock."""
    context = OwnedResultWait(runtime, config_dir, container_id, deadline)
    raw = wait_owned_result(context, lambda: _read_worker_result(config_dir))
    require_time(deadline)
    value = json.loads(raw)
    require_time(deadline)
    if type(value) is not dict or type(value.get("status")) is not str \
            or value["status"] not in {"complete", "partial", "failed"}:
        raise RuntimeError("color worker result is malformed")
    return value


def _launch_held(runtime: DockerRuntime, location: tuple, command: list[str], held: HeldGradeLaunch | None) -> str:
    """Publish the owned intent before launch, with post-launch failures still covered by cleanup."""
    directory, name, evidence = location
    if held is not None:
        evidence["launchIntentSha256"] = held.before_launch(runtime, command)
    evidence["launchAttempted"] = True
    reference = _launch(runtime, str(directory), command, name)
    if held is not None:
        held.after_launch(reference)
    return reference


def _check_held_launch(held: HeldGradeLaunch | None) -> None:
    """Recheck opt-in ownership without adding a clock or touching legacy execution."""
    if held is not None:
        held.check()


def _verify_completion(source: str, request: dict, context: tuple) -> None:
    """Keep original whole-source and worker checks after unconditional exact cleanup."""
    evidence, worker_sha, held = context
    deadline = int(evidence["workDeadlineMonotonicNs"]) / 1_000_000_000
    profile = observation_profile(request.get("profile"))
    with wall_budget(deadline):
        _check_held_launch(held)
        evidence["sourceAfterSha256"] = file_hash(Path(source), profile.max_source_bytes)
        if evidence["sourceAfterSha256"] != request["sourceSha256"] or file_hash(WORKER) != worker_sha \
                or implementation_sources() != evidence["executionSources"]:
            raise RuntimeError("grade observation source or worker changed during execution")
        worker = evidence["worker"]
        if worker.get("status") != "complete" or worker.get("request") != request \
                or worker.get("policy") != profile.policy:
            raise RuntimeError("grade observation worker did not complete: " + str(worker.get("error")))
        _check_held_launch(held)
        require_time(deadline)


def _execute_with_launch(source: str, request: dict, directory: Path, context: tuple) -> None:
    """Share the original decoder/cleanup path; only owned naming/publication differs."""
    evidence, name, held = context
    deadline = int(evidence["workDeadlineMonotonicNs"]) / 1_000_000_000
    profile = observation_profile(request.get("profile"))
    with wall_budget(deadline):
        _check_held_launch(held)
        runtime = required_runtime()
        launch, worker_sha = _launch_command(runtime, (directory, name, source), request)
        evidence.update(workerScriptSha256=worker_sha, launchCommandHash=digest(launch))
        evidence["executionSources"] = implementation_sources()
        evidence["sourceBeforeSha256"] = file_hash(Path(source), profile.max_source_bytes)
        if evidence["sourceBeforeSha256"] != request["sourceSha256"]:
            raise RuntimeError("grade observation admitted source bytes changed")
        evidence["imageId"] = attest_image(runtime, str(directory))["Id"]
    reference = name
    try:
        with wall_budget(deadline):
            reference = _launch_held(runtime, (directory, name, evidence), launch, held)
            evidence["isolation"] = attest_probe_container(runtime, str(directory), name, source, launch)
            evidence["network"] = probe_container(runtime, str(directory), name)
            _check_held_launch(held)
            evidence["worker"] = _wait(runtime, str(directory), reference, deadline)
    finally:
        _cleanup((runtime, directory, name, reference), evidence)
    _verify_completion(source, request, (evidence, worker_sha, held))


def _execute(source: str, request: dict, directory: Path, evidence: dict) -> None:
    """Preserve the historical random-name interface and unchanged cleanup policy."""
    name = "sniper-grade-observation-" + uuid.uuid4().hex
    _execute_with_launch(source, request, directory, (evidence, name, None))


def _cleanup(context: tuple, evidence: dict) -> None:
    """Keep cleanup timing even when exact daemon-owned removal fails."""
    runtime, directory, name, reference = context
    started = time.monotonic()
    # The owning server independently cancels work with USR1. Defer that one
    # signal until exact daemon cleanup finishes; ALRM still bounds cleanup.
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGUSR1})
    try:
        with wall_budget(started + 90):
            if reference == name:
                reconcile_launch_abort(runtime, str(directory), name)
            removal = remove_container(runtime, str(directory), reference)
            evidence["removal"] = removal
            evidence["cleanupVerified"] = removal.get("canonicalAbsenceProved") is True
            if not evidence["cleanupVerified"]:
                raise RuntimeError("grade observation owned container absence is unproved")
    finally:
        evidence["cleanupBudgetSeconds"] = 90
        evidence["cleanupMs"] = round((time.monotonic() - started) * 1000)
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)


def _publish_execution(evidence: dict, artifact_dir: Path, context: tuple) -> None:
    """Owned success publication still consumes its original effective phase cutoff."""
    deadline, held = context
    if held is None or evidence["status"] != "complete":
        write_new(artifact_dir / "execution.json", evidence)
        os.chmod(artifact_dir / "execution.json", 0o400)
        return
    with wall_budget(deadline):
        write_new(artifact_dir / "execution.json", evidence)
        os.chmod(artifact_dir / "execution.json", 0o400)
        held.check()


def _setup_grade_paths(source: str, artifact_dir: Path) -> None:
    """Keep the same empty-attempt and exact canonical-source setup rules."""
    _directory(artifact_dir)
    source_path = Path(source)
    if not source_path.is_absolute() or source_path.resolve(strict=True) != source_path:
        raise ValueError("grade observation requires the exact admitted source path")
    real_directory(source_path.parent)


def _run_isolated_grade(source: str, request: dict, artifact_dir: Path, context: _GradeInvocation) -> dict:
    """Retain exact private failure/success evidence; never delete the attempt."""
    deadline, held = context.deadline, context.launch
    request = _request(request) if held is None else request
    profile = observation_profile(request.get("profile"))
    if held is None:
        _setup_grade_paths(source, artifact_dir)
    else:
        with wall_budget(deadline):
            _setup_grade_paths(source, artifact_dir)
    started = time.monotonic()
    if deadline is not None and (type(deadline) not in (int, float) or not math.isfinite(deadline)):
        raise ValueError("grade observation absolute deadline is invalid")
    deadline = min(deadline, started + request["timeoutSeconds"]) if deadline is not None \
        else started + request["timeoutSeconds"]
    if held is None:
        os.mkdir(artifact_dir / "result", 0o700)
    else:
        with wall_budget(deadline):
            os.mkdir(artifact_dir / "result", 0o700)
    evidence = {"schemaVersion": profile.version, "kind": "private-grade-observation-execution",
        "policy": profile.policy, **profile.evidence(), "request": request, "requestHash": digest(request),
        "sourcePath": source, "status": "failed", "launchAttempted": False,
        "cleanupVerified": False, "gradeApplicable": False, "deliveryApproved": False,
        "workDeadlineMonotonicNs": str(int(deadline * 1_000_000_000)),
        "caveats": ["Decoder warnings/errors are rejected; this is not a perfect corruption oracle.",
                    "Per-frame corrupt/decode-error flags are unavailable in the pinned decoder.",
                    "Current admitted source/declaration and every decoded record need separate validation."]}
    try:
        if held is None:
            _execute(source, request, artifact_dir, evidence)
        else:
            _execute_with_launch(source, request, artifact_dir, (evidence, held.name, held))
        evidence["status"] = "complete"
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        evidence["error"] = str(exc)
        if not evidence["launchAttempted"] and held is None:
            evidence["cleanupVerified"] = True
    evidence["elapsedMs"] = round((time.monotonic() - started) * 1000)
    evidence["artifactHash"] = digest(evidence)
    _publish_execution(evidence, artifact_dir, (deadline, held))
    if evidence["status"] != "complete":
        raise GradeIsolationError(evidence["error"], evidence)
    return evidence


def run_isolated_grade(source: str, request: dict, artifact_dir: Path,
                       deadline: float | None = None) -> dict:
    """Preserve the legacy optional deadline, random name and private evidence shape."""
    return _run_isolated_grade(source, request, artifact_dir, _GradeInvocation(deadline))


def run_owned_isolated_grade(source: str, request: dict, artifact_dir: Path,
                            owner: OwnedGradeLaunch | OwnedGradePhase) -> dict:
    """Use an externally preclaimed exact resource without granting grade or release authority."""
    started = time.monotonic()
    request = _request(request)
    phase, deadline = select_grade_phase(owner, started, request["timeoutSeconds"])
    with wall_budget(deadline):
        held = hold_grade_launch(phase.owner, source, request, artifact_dir)
        phase.check()
    result = _run_isolated_grade(source, request, artifact_dir, _GradeInvocation(deadline, held))
    phase.check()
    require_time(deadline)
    return result

"""Private project-bound full-source observation, with one decreasing budget.

The server must hold its existing project and shared color-resource leases and
retain the exact input hash and live child result. This module never accepts a
stored execution receipt as execution authority or writes plan/grade/approval.
"""
from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from color.deadline import require_time, wall_budget
from color.grade_observation_read import BoundGradeObservation, read_observation
from color.grade_observation_profile import ObservationProfile, V2, project_profile
from color.grade_project_authority import observe_project
from color.grade_project_owned import (GradeProjectOwnedContext, OwnedProjectObservation,
    OwnedProjectObservationError, _PendingObservation, check_owned_source, finish_owned, observation_binding, retain_pending)
from cut_preview_io import bound_json, digest, file_hash, write_new
from headless.grade_launch_intent import OwnedGradeLaunch
from headless.grade_observation_phase import OwnedGradePhase
from headless.grade_observation_policy import (
    GradeIsolationError, implementation_sources, run_isolated_grade, run_owned_isolated_grade,
)
from render_effect_discovery import local_python_import_closure

POLICY = "sniper-private-project-source-observation-v1"


@dataclass(frozen=True)
class _ProjectOptions:
    """Retain optional launch arguments without changing the original typed owner."""

    owned: GradeProjectOwnedContext | None
    launch: OwnedGradeLaunch | None = None
    _original: tuple | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        """Capture exact references before the first callback, hash or publication."""
        if self.launch is None:
            return
        if type(self.launch) is not OwnedGradeLaunch or type(self.owned) is not GradeProjectOwnedContext:
            raise ValueError("owned grade launch requires its actual original context")
        if self.launch.binding() != self.launch._original or self.owned._current_binding() != self.owned._binding:
            raise RuntimeError("owned grade launch or context changed before invocation")
        if self.launch.deadline > self.owned.deadline:
            raise ValueError("owned grade launch cannot extend the original caller cutoff")
        object.__setattr__(self, "_original", self.binding())
        self.check()

    def binding(self) -> tuple:
        """Keep the original source, callbacks and exact deadline scalar types."""
        owned, launch = self.owned, self.launch
        if type(owned) is not GradeProjectOwnedContext or type(launch) is not OwnedGradeLaunch:
            raise RuntimeError("owned grade launch or context changed")
        return (id(owned), id(owned.source), id(owned.guard), id(owned._binding), owned._current_binding(),
                id(launch), id(launch._original), launch.binding())

    def check(self) -> None:
        """Check retained arguments and original time without another owner callback."""
        if self._original is None:
            return
        if self.binding() != self._original:
            raise RuntimeError("owned grade launch or context changed")
        require_time(self.launch.deadline)
        if self.binding() != self._original:
            raise RuntimeError("owned grade launch or context changed")


@dataclass(frozen=True)
class _RunContext:
    """Internal phase state; the optional live owner never changes legacy policy."""

    deadline: float
    result: dict
    options: _ProjectOptions

    @property
    def owned(self) -> GradeProjectOwnedContext | None:
        """Return the exact original owner, never a shortened replacement context."""
        return self.options.owned


def implementation() -> list[dict]:
    """Bind this adapter and the actual isolated observation closure together."""
    paths = local_python_import_closure([Path(__file__)])
    rows = {str(path): file_hash(path) for path in paths}
    rows.update({row["path"]: row["sha256"] for row in implementation_sources()})
    return [{"path": path, "sha256": sha} for path, sha in sorted(rows.items())]


def _errors(error: BaseException) -> list[str]:
    """Retain a bounded primary/cleanup exception chain without hiding either."""
    result, seen = [], set()
    while error is not None and id(error) not in seen and len(result) < 5:
        seen.add(id(error))
        result.append(f"{type(error).__name__}: {error}"[:2000])
        error = error.__cause__ or error.__context__
    return result


def _summary(observed: BoundGradeObservation, held: dict) -> dict:
    """Expose observation facts only, never pixels, correction or approval."""
    records = observed.records
    stream = records.stream
    metadata = getattr(stream, "source_metadata", None)
    extra = {"sourceMetadata": metadata.record(), "rawProbeSha256": observed.raw_probe_sha256} if metadata else {}
    return {"source": held["binding"], **extra, "decodedFrames": records.decoded_record_count,
        "firstPts": stream.first_pts, "timeBase": str(stream.time_base),
        "stepTicks": stream.step_ticks, "width": stream.width, "height": stream.height,
        "recordsSha256": records.records_sha256, "rawFramesSha256": observed.raw_frames_sha256,
        "executionSha256": observed.execution_sha256, "decodedFrameFlagsAvailable": False,
        "gradeApplicable": False, "deliveryApproved": False}


def _worker(held: dict, directory: Path, context: _RunContext, profile: ObservationProfile) -> dict:
    """Keep the original request limits and mandatory cleanup path unchanged."""
    deadline, result = context.deadline, context.result
    phase = time.monotonic()
    context.options.check()
    directory.mkdir(mode=0o700)
    remaining = min(profile.max_seconds, math.floor(require_time(deadline)))
    if remaining < 30:
        raise RuntimeError("insufficient remaining budget for full-source observation")
    request = {"sourceSha256": held["binding"]["sourceSha256"],
               "frameCount": held["binding"]["frameCount"], "timeoutSeconds": remaining}
    if profile is V2:
        request.update(schemaVersion=2, profile=profile.token)
    result["cleanupVerified"] = False
    try:
        launch = context.options.launch
        execution = run_isolated_grade(held["sourcePath"], request, directory, deadline) if launch is None \
            else run_owned_isolated_grade(held["sourcePath"], request, directory, OwnedGradePhase(launch, deadline))
        result["cleanupVerified"] = execution["cleanupVerified"]
        result["cleanupMs"] = execution.get("cleanupMs", 0)
        context.options.check()
    except GradeIsolationError as error:
        result["cleanupVerified"] = error.cleanup_verified
        result["cleanupMs"] = error.evidence.get("cleanupMs", 0)
        raise
    finally:
        result["workerPhaseMs"] = round((time.monotonic() - phase) * 1000)
    return execution


def _run(value: dict, directory: Path, context: _RunContext) -> tuple[BoundGradeObservation, dict, dict, tuple | None]:
    """Every active phase consumes the same absolute Python monotonic deadline."""
    deadline, result = context.deadline, context.result
    profile = project_profile(value)
    with wall_budget(deadline):
        if context.owned is not None:
            context.owned.check()
        held = observe_project(value)
        if context.owned is not None:
            check_owned_source(held, context.owned)
        sources = implementation()
        write_new(directory / "parents.json", held)
        result["parentsSha256"] = file_hash(directory / "parents.json")
    execution_dir = directory / "execution"
    execution = _worker(held, execution_dir, context, profile)
    phase = time.monotonic()
    with wall_budget(deadline):
        observation = read_observation(execution_dir, (held["binding"], held["declaration"]), execution)
        binding = observation_binding(observation) if context.owned is not None else None
        result["replayMs"] = round((time.monotonic() - phase) * 1000)
        if observe_project(value) != held or implementation() != sources:
            raise RuntimeError("full-source project/source/declaration/implementation parents changed")
        if bound_json(directory / "input.json") != value:
            raise RuntimeError("full-source immutable input changed")
        result["observation"] = _summary(observation, held)
        result["implementation"] = sources
    return observation, held, execution, binding


def _pending(parts: tuple, directory: Path, context: _RunContext) -> _PendingObservation | None:
    """No pending reader value escapes the original bounded observation phase."""
    if context.owned is None:
        return None
    with wall_budget(context.deadline):
        return retain_pending(parts, directory, context.result, context.owned)


def _input_hash(directory: Path, deadline: float, context: GradeProjectOwnedContext | None) -> str:
    """Bound opt-in input work without changing historical input behavior."""
    if context is None:
        return file_hash(directory / "input.json")
    with wall_budget(deadline):
        context.check()
        return file_hash(directory / "input.json", 128 * 1024)


def _project_observation(value: dict, directory: Path, deadline: float,
                         options: _ProjectOptions) -> tuple[dict, OwnedProjectObservation | None]:
    """Persist immutable private failure/success evidence; unknown cleanup stays held."""
    started = time.monotonic()
    profile = project_profile(value)
    if type(deadline) not in (int, float) or not math.isfinite(deadline):
        raise ValueError("full-source observation deadline is invalid")
    deadline = min(deadline, started + profile.max_seconds)
    options.check()
    if options.launch is not None:
        deadline = min(deadline, options.launch.deadline)
    result = {"schemaVersion": profile.version, "policy": profile.project_policy, **profile.evidence(), "jobId": value["jobId"],
        "inputSha256": _input_hash(directory, deadline, options.owned), "status": "failed",
        "cleanupVerified": True, "cleanupMs": 0, "workerPhaseMs": 0, "replayMs": 0,
        "gradeApplicable": False, "deliveryApproved": False}
    pending = None
    try:
        options.check()
        run_context = _RunContext(deadline, result, options)
        parts = _run(value, directory, run_context)
        options.check()
        pending = _pending(parts, directory, run_context)
        options.check()
        require_time(deadline)
        if os.getppid() != value["ownerPid"]:
            raise RuntimeError("full-source observation lost its original server owner")
        result["status"] = "complete"
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        result["errors"] = _errors(error)
        result.pop("observation", None)
        pending = None
    result["elapsedMs"] = round((time.monotonic() - started) * 1000)
    result["artifactHash"] = digest(result)
    with wall_budget(deadline if result["status"] == "complete" else time.monotonic() + 5):
        write_new(directory / "observation.json", result)
        os.chmod(directory / "observation.json", 0o400)
        if pending is not None and (implementation() != result["implementation"] or os.getppid() != value["ownerPid"]):
            raise RuntimeError("owned grade implementation or original server owner changed during publication")
        owned = finish_owned(pending, directory, result, deadline) if pending is not None else None
        if owned is not None:
            options.check()
    if owned is not None:
        options.check()
    return result, owned


def run_project_observation(value: dict, directory: Path, deadline: float) -> dict:
    """Preserve the historical JSON result, declarations, limits and cleanup policy."""
    return _project_observation(value, directory, deadline, _ProjectOptions(None))[0]


def run_project_observation_owned(value: dict, directory: Path,
                                 context: GradeProjectOwnedContext,
                                 launch: OwnedGradeLaunch | None = None) -> OwnedProjectObservation:
    """Return only actual typed completion, never reconstruct it from stored JSON."""
    if type(context) is not GradeProjectOwnedContext:
        raise ValueError("owned grade requires its actual original context")
    if type(value) is not dict or directory != Path(value["producerDir"]) / ".sniper-grade-observations" / value["jobId"]:
        raise ValueError("owned grade requires the exact original project job directory")
    options = _ProjectOptions(context, launch)
    result, owned = _project_observation(value, directory, context.deadline, options)
    if owned is None:
        raise OwnedProjectObservationError(result)
    return owned

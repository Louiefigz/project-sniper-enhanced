"""Explicit V2 cleanup orchestration, never worker settlement or lease authority.

TS must first prove the original outer/nested workers and launch clients stopped.
This entry only reconciles authenticated exact names, with one protected cutoff.
No source, job or sidecar is read and the resource reservation is never deleted.
"""
from __future__ import annotations

import json
import math
import os
import stat
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from cut_preview_io import read_bytes
from guided_opening_claim import HeldOpeningClaim, read_execution_claim, verify_runtime_controls
from guided_opening_execution import OpeningExecutionClock, work_timer
from guided_opening_inputs import closed, hash_value
from guided_presenter_read_fingerprint import hold_read_metadata, same_read_metadata
from guided_source_color_cleanup import SourceColorCleanupContext, prepare_opening_source_color_cleanup
from guided_source_color_staging_contract import _uuid
from guided_source_color_staging_files import capture_staging_file, check_staging_file, staging_path
from headless.container_policy import DockerRuntime
from headless.external_media_verification import snapshot_stat_identity
from headless.grade_launch_files import directory_identity, hold_launch_file


@dataclass(frozen=True)
class SourceColorCleanupRequest:
    """Explicit authenticated raw reservation and complete original request digest."""

    reservation_path: Path
    reservation_sha256: str
    source_color_hash: str


def _arguments(paths: tuple, refs: tuple, request: SourceColorCleanupRequest) -> tuple:
    """Validate and detach caller metadata before any filesystem or callback work."""
    if type(paths) is not tuple or len(paths) != 2 or type(refs) is not tuple or len(refs) != 3 \
            or type(request) is not SourceColorCleanupRequest:
        raise ValueError("source color cleanup requires exact original invocation")
    closed(vars(request), {"reservation_path", "reservation_sha256", "source_color_hash"}, "source color cleanup request")
    if staging_path(request.reservation_path).name != "active.json" or request.reservation_path.parent.name != ".sniper-color-resource":
        raise ValueError("source color cleanup requires the exact resource reservation path")
    return (id(paths), tuple(str(staging_path(row)) for row in paths), id(refs), hash_value(refs[0]),
            str(staging_path(refs[1])), hash_value(refs[2]), id(request), str(staging_path(request.reservation_path)),
            hash_value(request.reservation_sha256), hash_value(request.source_color_hash))


def _producer(claim_path: Path) -> Path:
    """Derive one producer namespace from the exact original execution-claim path."""
    parts = claim_path.parts
    if len(parts) < 6 or parts[-5] != "guided-v2-operations" or parts[-3] != "executions" \
            or parts[-1] != "execution-claim.json":
        raise ValueError("source color cleanup requires the original derived claim path")
    _uuid(parts[-4])
    _uuid(parts[-2])
    return claim_path.parents[4]


def _control(path: Path, socket: bool = False) -> tuple:
    """Capture actual control inode/full stat plus canonical parent identities."""
    staging_path(path)
    parents = directory_identity(path.parent)
    info = path.lstat()
    valid = stat.S_ISSOCK(info.st_mode) if socket else stat.S_ISREG(info.st_mode) and info.st_nlink == 1
    if not valid or path.resolve(strict=True) != path:
        raise RuntimeError("source color cleanup control is not original canonical metadata")
    return str(path), socket, snapshot_stat_identity(info), parents


def _claim_projection(claim: HeldOpeningClaim) -> tuple:
    """Hold the actual returned raw reference as well as its detached claim value."""
    if type(claim) is not HeldOpeningClaim or type(claim.path) is not type(Path()):
        raise RuntimeError("source color cleanup original claim return changed")
    return id(claim), str(claim.path), claim.sha256, id(claim.value), claim.value


class _Execution:
    """One original cleanup invocation and immutable metadata/control lifetime."""

    def __init__(self, paths: tuple, refs: tuple, allowance: tuple, request: SourceColorCleanupRequest) -> None:
        """Start from the public entry origin, never after setup or claim admission."""
        started, timeout = allowance
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 300:
            raise RuntimeError("opening cleanup requires a positive protected budget at most300 seconds")
        self.paths, self.refs, self.request = paths, refs, request
        self.original = hold_read_metadata(_arguments(paths, refs, request))
        self.started, self.clock = started, OpeningExecutionClock(started + timeout)
        self.clock_binding = hold_read_metadata((id(self.clock), self.clock.end, id(self.clock.events), self.started))
        self.producer = _producer(refs[1])
        self.claim, self.claim_binding, self.runtime, self.runtime_binding = None, None, None, None
        self.files, self.controls, self.config, self.config_identity = (), (), None, None
        self.output_identity = None
        self.reservation_file = None
        self.graphics = []

    def pure(self) -> None:
        """Keep original caller, clock and actual admitted return objects unchanged."""
        if not same_read_metadata(_arguments(self.paths, self.refs, self.request), self.original) \
                or type(self.clock) is not OpeningExecutionClock or set(vars(self.clock)) != {"end", "events"} \
                or not same_read_metadata((id(self.clock), self.clock.end, id(self.clock.events), self.started), self.clock_binding):
            raise RuntimeError("source color cleanup original invocation changed")
        if self.claim is not None and not same_read_metadata(_claim_projection(self.claim), self.claim_binding):
            raise RuntimeError("source color cleanup original claim return changed")
        if self.runtime is not None and not same_read_metadata((id(self.runtime), id(self.runtime.approval), self.runtime), self.runtime_binding):
            raise RuntimeError("source color cleanup original runtime changed")
        if any(not same_read_metadata((id(row), row), binding) for row, binding in self.graphics):
            raise RuntimeError("source color cleanup original graphic result changed")
        self.clock.remaining()

    def guard(self) -> None:
        """Stat original controls without per-name binary rehashing or daemon calls."""
        self.pure()
        for held in self.files:
            held.check()
        if self.reservation_file is not None:
            check_staging_file(self.reservation_file)
        if tuple(_control(Path(row[0]), row[1]) for row in self.controls) != self.controls:
            raise RuntimeError("source color cleanup original tool/socket/approval changed")
        if self.config is not None and directory_identity(self.config) != self.config_identity:
            raise RuntimeError("source color cleanup original private config changed")
        if self.output_identity is not None and directory_identity(self.paths[1]) != self.output_identity:
            raise RuntimeError("source color cleanup original output ancestry changed")
        self.pure()

    def prepare(self) -> None:
        """Hold original raw claim/input and controls before full runtime admission."""
        self.output_identity = directory_identity(self.paths[1])
        self.reservation_file = capture_staging_file(self.request.reservation_path)
        claim_file = hold_launch_file(self.refs[1], self.refs[2])
        input_file = hold_launch_file(self.paths[0], self.refs[0])
        self.files = (claim_file, input_file)
        raw_claim, raw_input = claim_file.value(), input_file.value()
        controls = raw_claim["runtime"]
        self.controls = tuple(_control(Path(controls[key]), key == "dockerSocketPath")
                              for key in ("dockerPath", "dockerSocketPath", "imageApprovalPath"))
        approval = read_bytes(Path(controls["imageApprovalPath"]), 1024 * 1024)
        self.guard()
        self.claim = read_execution_claim(self.paths, self.refs)
        self.claim_binding = hold_read_metadata(_claim_projection(self.claim))
        if self.claim.path != self.refs[1] or self.claim.sha256 != self.refs[2] \
                or not same_read_metadata(self.claim.value, hold_read_metadata(raw_claim)):
            raise RuntimeError("source color cleanup admitted claim differs from original raw bytes")
        self.snapshot = raw_input["pipeline"]["snapshotRoot"]
        self.runtime = DockerRuntime(controls["dockerPath"], controls["dockerSocketPath"], controls["imageId"],
                                     controls["userId"], json.loads(approval.decode("utf8", errors="strict")))
        self.runtime_binding = hold_read_metadata((id(self.runtime), id(self.runtime.approval), self.runtime))
        self.guard()
        self.config = Path(tempfile.mkdtemp(prefix="source-color-cleanup-", dir=self.paths[1]))
        self.config_identity = directory_identity(self.config)
        self.guard()

    def controls_after(self) -> None:
        """Verify actual original runtime again, bracketed by the first stat holds."""
        self.guard()
        verify_runtime_controls(self.claim.value["runtime"], self.snapshot)
        self.guard()

    def graphic(self, order: int) -> dict:
        """Bracket the unchanged graphic owner and retain its actual returned evidence."""
        from guided_opening_cleanup import reconcile_order

        self.guard()
        row = reconcile_order(self.claim, order)
        self.graphics.append((row, hold_read_metadata((id(row), row))))
        self.guard()
        return row

    def remove_config(self) -> None:
        """Remove only this exact newly created empty config, never recurse or adopt."""
        if self.config is None:
            return
        with work_timer(self.clock):
            self.guard()
            os.rmdir(self.config)
            self.config = None
            self.pure()


def _result(state: _Execution, rows: list, source_color: dict) -> dict:
    """Publish exact V2 evidence only after every native and local cleanup succeeds."""
    state.guard()
    return {"schemaVersion": 2, "kind": "guided-opening-cleanup-result", "claimPath": str(state.claim.path),
            "claimSha256": state.claim.sha256, "inputSha256": state.refs[0], "outputRoot": str(state.paths[1]),
            "executionId": state.claim.value["executionId"], "cleanupVerified": True, "graphics": rows,
            "sourceColor": source_color, "elapsedMs": round((time.monotonic() - state.started) * 1000),
            "stages": state.clock.events, "budgetScope": "separate-protected-cleanup-not-render-allowance",
            "processGroupStopped": "requires-owned-server-observation", "openingApproved": False}


def _run(state: _Execution) -> dict:
    """Keep real graphic reconciliation between reservation preparation and batch."""
    state.clock.phase("cleanup-claim-and-controls", state.prepare)
    selected = state.request
    context = SourceColorCleanupContext(state.claim, state.producer, selected.reservation_path.parent, selected.source_color_hash,
                                        state.clock, state.runtime, state.config, state.guard)
    prepared = prepare_opening_source_color_cleanup((selected.reservation_path, selected.reservation_sha256), context)
    rows = [state.clock.phase(f"reconcile-graphic-{order}", lambda order=order: state.graphic(order))
            for order in state.claim.value["selectedGraphicOrders"]]
    state.clock.phase("cleanup-controls-after", state.controls_after)
    source_color = prepared.reconcile()
    evidence = hold_read_metadata((id(rows), rows, id(source_color), source_color))
    with work_timer(state.clock):
        state.controls_after()
    state.remove_config()
    with work_timer(state.clock):
        result = _result(state, rows, source_color)
        if not same_read_metadata((id(rows), rows, id(source_color), source_color), evidence):
            raise RuntimeError("source color cleanup actual returned evidence changed")
        return result


def cleanup_source_color(paths: tuple, refs: tuple, allowance: tuple, request: SourceColorCleanupRequest) -> dict:
    """Reconcile only after caller-owned process settlement; never release any lease."""
    state = _Execution(paths, refs, allowance, request)
    try:
        return _run(state)
    except BaseException as error:
        try:
            state.remove_config()
        except BaseException as cleanup_error:
            error.add_note(f"Original private cleanup config retained/unverified: {cleanup_error}")
        raise

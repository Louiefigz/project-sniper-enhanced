"""Descriptor-held executable byte reobservation around one callback."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from .runtime_capability_manifest import (
    RuntimeCapabilityManifestV1,
    parse_runtime_capability_manifest_v1,
    validate_runtime_capability_manifest_v1,
)
from .runtime_executable_pins import (
    PinnedExecutableV1,
    RuntimeExecutableReobservationError,
    close_pins,
    pin_executable,
    snapshot_for_pin,
    verify_pins,
)
from .runtime_executable_reobservation_wire import (
    EXECUTABLE_REOBSERVATION_STATUS,
    RuntimeExecutableReobservationReportV1,
    RuntimeExecutableSnapshotV1,
    parse_runtime_executable_reobservation_report_v1,
)

ResultT = TypeVar("ResultT")

__all__ = (
    "RuntimeExecutableObservationV1",
    "RuntimeExecutableReobservationError",
    "RuntimeExecutableReobservationOutcomeV1",
    "RuntimeExecutableReobservationRequestV1",
    "reobserve_runtime_executables",
)


@dataclass(frozen=True)
class RuntimeExecutableReobservationRequestV1:
    """Exact runtime declaration and canonical paths to its two tool roles."""

    runtime_manifest: RuntimeCapabilityManifestV1
    ffmpeg_path: str
    ffprobe_path: str


@dataclass(frozen=True)
class RuntimeExecutableObservationV1:
    """Pre-callback observations; descriptor numbers stay private to the seam."""

    ffmpeg: RuntimeExecutableSnapshotV1
    ffprobe: RuntimeExecutableSnapshotV1


@dataclass(frozen=True)
class RuntimeExecutableReobservationOutcomeV1(Generic[ResultT]):
    """Callback result plus a canonical report that never grants authority."""

    observation_result: ResultT
    report: RuntimeExecutableReobservationReportV1


def _tool_document(value: RuntimeExecutableSnapshotV1) -> dict:
    return {
        "path": value.path,
        "sha256": value.sha256,
        "sizeBytes": value.size_bytes,
        "device": value.device,
        "inode": value.inode,
        "mode": value.mode,
        "linkCount": value.link_count,
        "uid": value.uid,
        "gid": value.gid,
        "mtimeNs": value.mtime_ns,
        "ctimeNs": value.ctime_ns,
    }


def _report(
    manifest: RuntimeCapabilityManifestV1, view: RuntimeExecutableObservationV1
) -> RuntimeExecutableReobservationReportV1:
    document = {
        "schemaVersion": 1,
        "status": EXECUTABLE_REOBSERVATION_STATUS,
        "scope": "synchronous-callback-endpoints",
        "requestDigest": manifest.request_digest,
        "qualityPolicyId": manifest.quality_policy_id,
        "runtimeCapabilityManifestSha256": hashlib.sha256(
            manifest.document_json
        ).hexdigest(),
        "tools": {
            "ffmpeg": _tool_document(view.ffmpeg),
            "ffprobe": _tool_document(view.ffprobe),
        },
        "claims": {
            "callbackCompleted": True,
            "exactExecutableBytesReobserved": True,
            "inodeSnapshotsStable": True,
            "runtimeVerified": False,
            "dynamicLibraryClosureVerified": False,
            "executionReobserved": False,
            "processExecutionAttested": False,
            "qualityMeasurementsReobserved": False,
            "executionAuthorized": False,
            "publicationAuthorized": False,
        },
    }
    raw = json.dumps(
        document,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("ascii")
    return parse_runtime_executable_reobservation_report_v1(raw)


def _checked_request(
    value: object,
) -> tuple[RuntimeCapabilityManifestV1, str, str]:
    if type(value) is not RuntimeExecutableReobservationRequestV1:
        raise RuntimeExecutableReobservationError(
            "runtime executable reobservation request is invalid"
        )
    try:
        validate_runtime_capability_manifest_v1(value.runtime_manifest)
        manifest = parse_runtime_capability_manifest_v1(
            value.runtime_manifest.document_json
        )
    except RuntimeError as exc:
        raise RuntimeExecutableReobservationError(
            "runtime executable declaration is forged or invalid"
        ) from exc
    if (
        type(value.ffmpeg_path) is not str
        or type(value.ffprobe_path) is not str
    ):
        raise RuntimeExecutableReobservationError(
            "runtime executable paths must be exact strings"
        )
    if value.ffmpeg_path == value.ffprobe_path:
        raise RuntimeExecutableReobservationError(
            "runtime executable roles alias"
        )
    return manifest, value.ffmpeg_path, value.ffprobe_path


def _pin_tools(
    manifest: RuntimeCapabilityManifestV1, ffmpeg_path: str, ffprobe_path: str
) -> tuple[PinnedExecutableV1, PinnedExecutableV1]:
    ffmpeg = pin_executable(ffmpeg_path, "ffmpeg", manifest.ffmpeg.sha256)
    try:
        ffprobe = pin_executable(
            ffprobe_path, "ffprobe", manifest.ffprobe.sha256
        )
    except BaseException:
        close_pins((ffmpeg,))
        raise
    first = (ffmpeg.identity.device, ffmpeg.identity.inode)
    second = (ffprobe.identity.device, ffprobe.identity.inode)
    if first == second:
        close_pins((ffmpeg, ffprobe))
        raise RuntimeExecutableReobservationError(
            "runtime executable inode roles alias"
        )
    return ffmpeg, ffprobe


def _observe(
    pins: tuple[PinnedExecutableV1, PinnedExecutableV1],
    callback: Callable[[RuntimeExecutableObservationV1], ResultT],
) -> tuple[ResultT, RuntimeExecutableObservationV1]:
    _verified(pins)
    view = RuntimeExecutableObservationV1(
        snapshot_for_pin(pins[0]), snapshot_for_pin(pins[1])
    )
    try:
        result = callback(view)
    except BaseException:
        try:
            _verified(pins)
        except RuntimeExecutableReobservationError as verification_error:
            raise RuntimeExecutableReobservationError(
                "runtime executables changed during failed observation"
            ) from verification_error
        raise
    _verified(pins)
    return result, view


def _verified(pins: tuple[PinnedExecutableV1, ...]) -> None:
    try:
        verify_pins(pins)
    except OSError as exc:
        raise RuntimeExecutableReobservationError(
            "runtime executable descriptor reobservation failed"
        ) from exc


def reobserve_runtime_executables(
    request: object,
    observation: Callable[[RuntimeExecutableObservationV1], ResultT],
) -> RuntimeExecutableReobservationOutcomeV1[ResultT]:
    """Rehash stable held tool inodes before/after one synchronous callback.

    This endpoint check does not prove which executable a process ran, any dynamic
    library closure, any media measurement, or execution/publication authority.
    """
    if not callable(observation):
        raise RuntimeExecutableReobservationError(
            "observation callback is invalid"
        )
    manifest, ffmpeg_path, ffprobe_path = _checked_request(request)
    try:
        pins = _pin_tools(manifest, ffmpeg_path, ffprobe_path)
    except OSError as exc:
        raise RuntimeExecutableReobservationError(
            "runtime executable descriptor acquisition failed"
        ) from exc
    try:
        result, view = _observe(pins, observation)
        report = _report(manifest, view)
        return RuntimeExecutableReobservationOutcomeV1(result, report)
    finally:
        close_pins(pins)

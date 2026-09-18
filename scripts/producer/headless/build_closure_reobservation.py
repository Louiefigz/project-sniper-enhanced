"""Reobserve exact declared source and tool bytes around one callback."""

from __future__ import annotations

import hashlib
import hmac
import os
import stat
from collections.abc import Callable
from typing import TypeVar

from .build_closure_reobservation_wire import (
    BUILD_CLOSURE_REOBSERVATION_STATUS,
    BuildClosureReobservationReportV1,
    build_closure_set_digest,
    encode_build_closure_document,
    parse_build_closure_reobservation_report_v1,
)
from .build_receipt_binding import (
    BuildReceiptBindingError,
    BuildReceiptBindingV1,
    bind_build_receipt_semantics,
)
from .build_closure_reobservation_types import (
    BuildClosureObservationV1,
    BuildClosureReobservationOutcomeV1,
    BuildClosureReobservationRequestV1,
)
from .build_closure_rows import (
    BuildClosureRowsError,
    build_source_rows,
    build_tool_rows,
)
from .runtime_executable_pins import (
    PinnedExecutableV1,
    close_pins,
    pin_executable,
    verify_pins,
)
from .safe_source_files import PinnedSourceRoot

ResultT = TypeVar("ResultT")


class BuildClosureReobservationError(RuntimeError):
    """Build closure endpoint bytes or metadata are not exact."""


def _checked_request(value: object) -> BuildClosureReobservationRequestV1:
    if type(value) is not BuildClosureReobservationRequestV1:
        raise BuildClosureReobservationError(
            "build closure reobservation request is invalid"
        )
    try:
        bind_build_receipt_semantics(value.binding)
    except BuildReceiptBindingError as exc:
        raise BuildClosureReobservationError(
            "build receipt authority is invalid"
        ) from exc
    root = value.pipeline_root
    valid = type(root) is str and os.path.isabs(root)
    valid = valid and os.path.normpath(root) == root
    valid = valid and os.path.realpath(root) == root
    declared_root = value.binding.render_receipt.manifest.pipeline_root
    valid = valid and root == declared_root
    if not valid:
        raise BuildClosureReobservationError(
            "build source root does not match its retained canonical root"
        )
    return value


def _source_identity(path: str) -> tuple[int, ...]:
    info = os.stat(path, follow_symlinks=False)
    safe = stat.S_ISREG(info.st_mode) and info.st_nlink == 1
    safe = safe and info.st_uid == os.geteuid()
    safe = safe and stat.S_IMODE(info.st_mode) & 0o022 == 0
    if not safe or os.path.realpath(path) != path:
        raise BuildClosureReobservationError("build source inode is unsafe")
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_uid,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _verify_sources(
    root: PinnedSourceRoot, rows: tuple[dict, ...]
) -> tuple[tuple[int, ...], ...]:
    identities = []
    for row in rows:
        path = os.path.join(root.path, row["path"])
        before = _source_identity(path)
        raw = root.read(row["path"])
        actual = hashlib.sha256(raw).hexdigest()
        valid = len(raw) == row["sizeBytes"]
        valid = valid and hmac.compare_digest(actual, row["sha256"])
        after = _source_identity(path)
        if not valid or before != after:
            raise BuildClosureReobservationError(
                "build source bytes or metadata changed"
            )
        identities.append(after)
    snapshot = tuple(identities)
    current = tuple(
        _source_identity(os.path.join(root.path, row["path"])) for row in rows
    )
    root.assert_current()
    if current != snapshot:
        raise BuildClosureReobservationError("build source snapshot changed")
    return snapshot


def _pin_tools(rows: tuple[dict, ...]) -> tuple[PinnedExecutableV1, ...]:
    pins = []
    try:
        for row in rows:
            pin = pin_executable(row["path"], row["label"], row["sha256"])
            pins.append(pin)
            if pin.identity.size_bytes != row["sizeBytes"]:
                raise BuildClosureReobservationError(
                    "build tool size differs from its receipt"
                )
        identities = {
            (pin.identity.device, pin.identity.inode) for pin in pins
        }
        if len(identities) != len(pins):
            raise BuildClosureReobservationError(
                "build tool inode roles alias"
            )
        return tuple(pins)
    except BaseException:
        close_pins(tuple(pins))
        raise


def _verify_all(
    root: PinnedSourceRoot,
    sources: tuple[dict, ...],
    pins: tuple[PinnedExecutableV1, ...],
    baseline: tuple[tuple[int, ...], ...],
) -> None:
    try:
        verify_pins(pins)
    except RuntimeError as exc:
        raise BuildClosureReobservationError(
            "build tool bytes or metadata changed"
        ) from exc
    try:
        current = _verify_sources(root, sources)
    except BuildClosureReobservationError:
        raise
    except RuntimeError as exc:
        raise BuildClosureReobservationError(
            "build source root or metadata changed"
        ) from exc
    if current != baseline:
        raise BuildClosureReobservationError(
            "build source endpoint identity changed"
        )


def _observation(
    value: BuildReceiptBindingV1,
    sources: tuple[dict, ...],
    tools: tuple[dict, ...],
) -> BuildClosureObservationV1:
    return BuildClosureObservationV1(
        value.compositor_receipt.build_digest,
        value.render_receipt.build_digest,
        len(sources),
        build_closure_set_digest(b"sniper-build-source-set-v1\0", sources),
        len(tools),
        build_closure_set_digest(b"sniper-build-tool-set-v1\0", tools),
    )


def _report(
    value: BuildReceiptBindingV1, view: BuildClosureObservationV1
) -> BuildClosureReobservationReportV1:
    runtime = value.runtime_binding.runtime_manifest
    document = {
        "schemaVersion": 1,
        "status": BUILD_CLOSURE_REOBSERVATION_STATUS,
        "scope": "synchronous-callback-endpoints",
        "requestDigest": runtime.request_digest,
        "qualityPolicyId": runtime.quality_policy_id,
        "runtimeCapabilityManifestSha256": hashlib.sha256(
            runtime.document_json
        ).hexdigest(),
        "builds": {
            "compositor": view.compositor_build_digest,
            "render": view.render_build_digest,
        },
        "sources": {
            "count": view.source_count,
            "setDigest": view.source_set_digest,
        },
        "tools": {"count": view.tool_count, "setDigest": view.tool_set_digest},
        "claims": {
            "callbackCompleted": True,
            "dynamicLibraryClosureVerified": False,
            "endpointMetadataStable": True,
            "exactSourceBytesReobserved": True,
            "exactToolBytesReobserved": True,
            "executionAuthorized": False,
            "executionReobserved": False,
            "processExecutionAttested": False,
            "publicationAuthorized": False,
            "runtimeVerified": False,
            "sourceRootDescriptorHeld": True,
            "toolInodeDescriptorsHeld": True,
        },
    }
    raw = encode_build_closure_document(document)
    return parse_build_closure_reobservation_report_v1(raw)


def _run_callback(
    callback: Callable[[BuildClosureObservationV1], ResultT],
    view: BuildClosureObservationV1,
    verify: Callable[[], None],
) -> ResultT:
    verify()
    try:
        result = callback(view)
    except BaseException:
        try:
            verify()
        except RuntimeError as verification_error:
            raise BuildClosureReobservationError(
                "build closure changed during failed observation"
            ) from verification_error
        raise
    verify()
    return result


def reobserve_build_closure(
    request: object,
    callback: Callable[[BuildClosureObservationV1], ResultT],
) -> BuildClosureReobservationOutcomeV1[ResultT]:
    """Rehash static sources and held tools; never attest execution."""
    checked = _checked_request(request)
    if not callable(callback):
        raise BuildClosureReobservationError("observation callback is invalid")
    try:
        sources = build_source_rows(checked.binding)
        tools = build_tool_rows(checked.binding)
    except BuildClosureRowsError as exc:
        raise BuildClosureReobservationError(str(exc)) from exc
    view = _observation(checked.binding, sources, tools)
    try:
        pins = _pin_tools(tools)
    except (OSError, RuntimeError) as exc:
        raise BuildClosureReobservationError(
            "build tool descriptor acquisition failed"
        ) from exc
    try:
        with PinnedSourceRoot(checked.pipeline_root) as root:
            baseline = _verify_sources(root, sources)

            def verify() -> None:
                _verify_all(root, sources, pins, baseline)

            result = _run_callback(callback, view, verify)
            return BuildClosureReobservationOutcomeV1(
                result, _report(checked.binding, view)
            )
    except OSError as exc:
        raise BuildClosureReobservationError(
            "build source descriptor reobservation failed"
        ) from exc
    finally:
        close_pins(pins)


def require_build_closure_execution_authorized(value: object) -> None:
    """Keep endpoint reobservation outside all execution gates."""
    raise BuildClosureReobservationError(BUILD_CLOSURE_REOBSERVATION_STATUS)

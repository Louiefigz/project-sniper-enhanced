"""Non-GUI composition root for durable attempt admission and safe recovery."""
from __future__ import annotations

import os
from dataclasses import dataclass

from .admission_registry import (
    AdmissionError,
    AdmissionOutcome,
    AdmissionRequest,
    AttemptStateConflict,
    admit,
    list_admissions,
    locate_admission,
)
from .attempt_trace import (
    AttemptTrace,
    TornTraceTail,
    TraceContext,
    TraceCorruption,
    TraceError,
    TraceState,
)
from .boot_identity import read_boot_id
from .durable_files import DurableFileError
from .terminal_manifest import TerminalManifestError, recover_terminal_manifest


class DurabilityControllerError(RuntimeError):
    """A durable attempt cannot be classified without unsafe guessing."""


@dataclass(frozen=True)
class ControllerAdmissionOutcome:
    """One durable admission plus its trace and optional terminal result."""

    created: bool
    record: dict
    trace_state: TraceState
    terminal_manifest: dict | None


@dataclass(frozen=True)
class RecoveryObservation:
    """One startup-scan classification that never guesses worker liveness."""

    attempt_id: str
    action: str
    phase: str | None
    trace_disposition: str | None
    terminal: bool
    reason_code: str | None


def _boot_id(explicit: str | None) -> str:
    return read_boot_id() if explicit is None else explicit


def _attempt_dir(authority_root: str, attempt_id: str) -> str:
    return os.path.join(authority_root, "attempts", attempt_id)


def _trace(authority_root: str, record: dict, boot_id: str) -> AttemptTrace:
    context = TraceContext(
        unit_id=record["unitId"], attempt_id=record["attemptId"],
        release_id=record["releaseId"], build_id=record["buildId"],
        boot_id=boot_id, policy_id=record["policyId"],
        expected_parent=record["expectedParent"],
        request_digest=record["requestIdentityDigest"],
        authority_id=record["authorityId"])
    return AttemptTrace(_attempt_dir(authority_root, record["attemptId"]), context)


def _replay_request(authority_root: str, record: dict) -> AdmissionRequest:
    return AdmissionRequest(
        authority_root=authority_root, authority_id=record["authorityId"],
        idempotency_key=record["idempotencyKey"],
        request_identity_digest=record["requestIdentityDigest"],
        attempt_id=record["attemptId"], unit_id=record["unitId"],
        first_submitted_at=record["firstSubmittedAt"],
        release_id=record["releaseId"], build_id=record["buildId"],
        policy_id=record["policyId"], expected_parent=record["expectedParent"])


def _complete_durable_boundaries(
        authority_root: str, outcome: AdmissionOutcome,
        boot_id: str) -> ControllerAdmissionOutcome:
    trace = _trace(authority_root, outcome.record, boot_id)
    terminal = recover_terminal_manifest(trace)
    trace.ensure_admitted()
    state = trace.validate()
    if state.terminal_disposition is not None and terminal is None:
        raise DurabilityControllerError(
            "terminal trace has no recoverable result intent or manifest")
    return ControllerAdmissionOutcome(
        outcome.created, outcome.record, state, terminal)


def admit_attempt(request: AdmissionRequest,
                  boot_id: str | None = None) -> ControllerAdmissionOutcome:
    """Durably admit and trace one attempt before returning acceptance."""
    outcome = admit(request)
    return _complete_durable_boundaries(
        request.authority_root, outcome, _boot_id(boot_id))


def resolve_attempt(authority_root: str, attempt_id: str,
                    boot_id: str | None = None) -> ControllerAdmissionOutcome:
    """Resolve and heal only the durable boundaries of one admitted attempt."""
    outcome = locate_admission(authority_root, attempt_id)
    return _complete_durable_boundaries(
        authority_root, outcome, _boot_id(boot_id))


def _observation(authority_root: str, record: dict,
                 boot_id: str) -> RecoveryObservation:
    outcome = admit(_replay_request(authority_root, record))
    trace = _trace(authority_root, outcome.record, boot_id)
    terminal = recover_terminal_manifest(trace)
    try:
        admission = trace.ensure_admitted()
    except TornTraceTail:
        return RecoveryObservation(
            record["attemptId"], "RECONCILIATION_REQUIRED", None, None,
            False, "TORN_TRACE_TAIL")
    state = trace.validate()
    if state.terminal_disposition is not None and terminal is None:
        return RecoveryObservation(
            record["attemptId"], "BROKEN", state.phase,
            state.terminal_disposition, False, "TERMINAL_RESULT_UNAVAILABLE")
    if terminal is not None:
        action = ("TERMINAL_CONFIRMED" if outcome.terminal_manifest is not None
                  else "TERMINAL_MANIFEST_RECOVERED")
        return RecoveryObservation(
            record["attemptId"], action, state.phase,
            state.terminal_disposition, True, None)
    if admission is not None:
        reason = ("TORN_ADMISSION" if admission.recovered_tail_bytes
                  else "ADMISSION_GAP")
        return RecoveryObservation(
            record["attemptId"], "ADMISSION_TRACE_RECOVERED", state.phase,
            None, False, reason)
    reason = "HOST_REBOOT" if state.boot_id != boot_id else "PROCESS_STATE_UNKNOWN"
    return RecoveryObservation(
        record["attemptId"], "RECONCILIATION_REQUIRED", state.phase,
        None, False, reason)


def _broken_observation(record: dict, reason: str) -> RecoveryObservation:
    return RecoveryObservation(
        record["attemptId"], "BROKEN", None, None, False, reason)


def _classify_record(authority_root: str, record: dict,
                     boot_id: str) -> RecoveryObservation:
    try:
        return _observation(authority_root, record, boot_id)
    except TraceCorruption:
        return _broken_observation(record, "TRACE_CORRUPT")
    except TerminalManifestError:
        return _broken_observation(record, "TERMINAL_CORRUPT")
    except AttemptStateConflict:
        return _broken_observation(record, "ATTEMPT_PATH_UNSAFE")
    except AdmissionError:
        return _broken_observation(record, "ADMISSION_IDENTITY_CONFLICT")
    except DurableFileError:
        return _broken_observation(record, "ATTEMPT_PATH_UNSAFE")
    except TraceError:
        return _broken_observation(record, "TRACE_PATH_UNSAFE")


def recover_durable_boundaries(authority_root: str,
                               boot_id: str | None = None
                               ) -> list[RecoveryObservation]:
    """Heal only unambiguous admission/terminal gaps and classify the rest."""
    current_boot = _boot_id(boot_id)
    return [_classify_record(authority_root, record, current_boot)
            for record in list_admissions(authority_root)]

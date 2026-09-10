#!/usr/bin/env python3
"""Top-level classification for closed baseline execution/repeat evidence."""
from __future__ import annotations

from typing import Any

from baseline_repeat_equivalence import calibration_authority
from baseline_media_validation import classify_execution
from baseline_repeat_validation import repeat_classification
from baseline_tool_authority import observe_command_tools
from baseline_validation_common import (
    document_sha256 as _document_sha256,
    valid_tool_authority,
)


def classify(
    fixture: dict[str, Any],
    runs: list[dict[str, Any]],
    repeat_equivalence: object = None,
) -> str:
    """Classify execution first, then exact or calibrated codec-floor parity."""
    execution = classify_execution(fixture, runs)
    if execution != fixture.get("evidenceClass"):
        return execution
    if fixture["evidenceClass"] != "current-full-path-baseline":
        return execution
    repeat = repeat_classification(fixture, runs, repeat_equivalence)
    return repeat or "repeat-equivalence-unproved"


def _trace_shape(trace: dict) -> bool:
    required = {
        "schemaVersion", "fixture", "classification", "command",
        "toolAuthority", "host", "runs", "executionObserved",
        "repeatEquivalence",
    }
    if set(trace) != required:
        return False
    command = trace["command"]
    fixture = trace["fixture"]
    host = trace["host"]
    execution = trace["executionObserved"]
    return (
        trace["schemaVersion"] == 1
        and isinstance(fixture, dict)
        and isinstance(command, list)
        and bool(command)
        and all(isinstance(item, str) and item for item in command)
        and isinstance(host, dict)
        and set(host) == {"platform", "machine", "python"}
        and all(isinstance(value, str) and value for value in host.values())
        and isinstance(trace["runs"], list)
        and isinstance(execution, dict)
        and set(execution) == {"complete", "classification"}
        and valid_tool_authority(trace["toolAuthority"])
    )


def _authorities_are_current(trace: dict) -> bool:
    """Reobserve retained direct tools and current calibration inputs."""
    try:
        command = tuple(trace["command"])
        if observe_command_tools(command) != trace["toolAuthority"]:
            return False
        if trace["fixture"].get(
                "evidenceClass") != "current-full-path-baseline":
            return True
        repeat = trace.get("repeatEquivalence")
        if classify_execution(trace["fixture"], trace["runs"]) != "current-full-path-baseline":
            # A failed/incomplete execution has no repeat-picture claim. Keep
            # its observed tool-bound failure without demanding a success oracle.
            return repeat is None
        return (
            isinstance(repeat, dict)
            and repeat.get("calibrationAuthority") == calibration_authority()
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        return False


def validate_trace_document(trace: object) -> bool:
    """Whether a retained trace is closed and internally self-consistent."""
    if not isinstance(trace, dict) or not _trace_shape(trace):
        return False
    fixture = trace["fixture"]
    if (
        fixture.get("evidenceClass") == "current-full-path-baseline"
        and not trace["toolAuthority"]["entrypoints"]
    ):
        return False
    if not _authorities_are_current(trace):
        return False
    try:
        execution_class = classify_execution(fixture, trace["runs"])
        expected = classify(
            fixture, trace["runs"], trace["repeatEquivalence"])
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return False
    execution = {
        "complete": execution_class == fixture.get("evidenceClass"),
        "classification": execution_class,
    }
    return (
        trace["executionObserved"] == execution
        and trace["classification"] == expected
    )

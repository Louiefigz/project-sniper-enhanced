"""Released repository provenance for deterministic retake choice."""
from __future__ import annotations

import importlib
import os
import sys

import producer_config
import rapidfuzz
import retake_scan
from edit import study_edit_diff
from edit.cut_repair_context_sources import digest, stable_file_digest
from rapidfuzz import fuzz

_REPOSITORY_FILES = (
    ("detector-authority-adapter", "alternate_take_scan_authority.py"),
    ("candidate-range-authority", "alternate_take_candidates.py"),
    ("operation-binding-derivation", "alternate_take_derivation.py"),
    ("released-selection-policy", "alternate_take_selection.py"),
    ("alternate-take-value-types", "alternate_take_types.py"),
    ("candidate-qc-value-types", "cut_repair_candidate_qc_types.py"),
    ("context-authority", "cut_repair_context_sources.py"),
    ("cross-runtime-canonical-json", "../cross_runtime_canonical_json.py"),
    ("exact-timing", "exact_timing.py"),
    ("target-word-authority", "target_resolver.py"),
    ("repair-impact", "repair_impact.py"),
    ("repair-ranges", "repair_ranges.py"),
    ("non-ripple-contracts", "non_ripple_contracts.py"),
    ("pause-scan-import", "pause_scan.py"),
)


def _real_file(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} path is absent")
    path = os.path.realpath(value)
    if not os.path.isfile(path) or os.path.islink(path):
        raise ValueError(f"{label} path is not a real file")
    return path


def _implementation_path() -> str:
    module_name = getattr(fuzz.ratio, "__module__", "")
    if not isinstance(module_name, str) or not module_name:
        raise ValueError("RapidFuzz implementation module is absent")
    module = importlib.import_module(module_name)
    return _real_file(
        getattr(module, "__file__", None), "RapidFuzz implementation")


def _row(role: str, path: str) -> dict:
    return {
        "role": role, "path": path,
        "sha256": stable_file_digest(path, role),
    }


def detector_tool_closure() -> dict:
    """Reobserve released code pins without claiming an OS/stdlib closure."""
    directory = os.path.dirname(os.path.realpath(__file__))
    files = [_row(role, os.path.realpath(os.path.join(directory, name)))
             for role, name in _REPOSITORY_FILES]
    files.extend([
        _row("closure-controller", os.path.realpath(__file__)),
        _row("detector-entrypoint", _real_file(
            retake_scan.__file__, "retake detector")),
        _row("detector-config", _real_file(
            producer_config.__file__, "producer config")),
        _row("transcript-policy-helper", _real_file(
            study_edit_diff.__file__, "transcript policy helper")),
        _row("python-runtime", _real_file(
            sys.executable, "Python runtime")),
        _row("rapidfuzz-package", _real_file(
            rapidfuzz.__file__, "RapidFuzz package")),
        _row("rapidfuzz-dispatch", _real_file(
            getattr(fuzz, "__file__", None), "RapidFuzz dispatch")),
        _row("rapidfuzz-implementation", _implementation_path()),
    ])
    files.sort(key=lambda item: (item["role"], item["path"]))
    core = {
        "schemaVersion": 1,
        "kind": "deterministic-retake-detector-tool-closure",
        "scope":
            "transitive-repository-choice-derivation-rapidfuzz-"
            "python-executable-not-os-stdlib-dylibs",
        "files": files,
    }
    return {**core, "closureHash": digest(core)}

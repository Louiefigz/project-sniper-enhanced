"""Reviewed compact OCI compatibility receipt; raw evidence is a separate check.

Validation here never claims to have reopened the private media or archives.
Use comp_rate_oci_audit for deep revalidation; absent raw evidence must fail there.
"""
from __future__ import annotations

import re
from pathlib import Path

from cut_preview_io import bound_json, digest, file_hash
from graphics.comp_capability_artifact import capability_digest, current_source_digest
from graphics.comp_rate_artifact import (
    PROBE_FRAMES, RELEASED_RATES, _current_capabilities, _duration_for, _stream_issue,
)
from graphics.render_tools import resolve_tools

ROOT = Path(__file__).resolve().parents[3]
SCOPE = "approved-oci-render-with-pinned-host-decode-proof"
CLAIM = "Four-frame exact-rate/codec/alpha-format/canvas/full-decode only; not motion or perceptual quality."
SHA = re.compile(r"[0-9a-f]{64}")
CHECKS = ["media-and-sealed-input-hashes", "exact-current-source-and-defaults",
          "exact-CLI-arguments", "runtime-network-and-resource-policy", "exact-container-absence"]
KEYS = {"schemaVersion", "kind", "runtimeScope", "passed", "qualityClaim", "sourceDigest",
        "capabilityDigest", "compositionCount", "rates", "probeFrames", "imageId", "renderToolClosure",
        "proofTools", "executionSources", "rawEvidence", "runnerObservation", "probes", "elapsedMs", "receiptHash"}
ROW_KEYS = {"kind", "rate", "duration", "stream", "mediaSha256", "inputSha256", "runtimeReceiptSha256",
            "sourceSha256", "specHash", "decoded", "checks", "elapsedMs"}


def _require(condition: bool, message: str) -> None:
    """Reject a malformed receipt before exposing a qualification result."""
    if not condition:
        raise RuntimeError(message)


def current_proof_tools() -> dict:
    """Read current host decoders only; never substitute their versions for OCI."""
    tools = resolve_tools()
    return {name: {"path": str(Path(tools[name]).resolve(strict=True)),
                   "sha256": file_hash(Path(tools[name]).resolve(strict=True), 512 * 1024 * 1024)}
            for name in ("ffmpeg", "ffprobe")}


def _header(value: dict, reviewed_hash: str, capabilities: dict) -> None:
    """Bind closed structure, exact reviewed bytes, inventory, and limited scope."""
    _require(set(value) == KEYS, "OCI receipt has unsupported or missing fields")
    _require(bool(SHA.fullmatch(reviewed_hash)), "an explicit reviewed OCI receipt hash is required")
    actual = digest({key: item for key, item in value.items() if key != "receiptHash"})
    _require(value["receiptHash"] == actual == reviewed_hash, "OCI receipt is not the reviewed exact artifact")
    expected = {"schemaVersion": 2, "kind": "hyperframes-oci-released-rate-matrix", "runtimeScope": SCOPE,
                "passed": True, "qualityClaim": CLAIM, "sourceDigest": current_source_digest(),
                "capabilityDigest": capability_digest(capabilities), "compositionCount": len(capabilities),
                "rates": list(RELEASED_RATES), "probeFrames": PROBE_FRAMES}
    _require(all(value[key] == item for key, item in expected.items()), "OCI receipt scope/source/catalog is stale")
    _require(type(value["elapsedMs"]) is int and value["elapsedMs"] > 0, "OCI cohort timing is malformed")


def _runtime_identity(value: dict, tools: dict) -> None:
    """Require approved OCI closure separately from current host decode proof."""
    approval = bound_json(ROOT / "scripts/producer/headless/render_image_approval.json")
    _require(value["imageId"] == approval["imageId"] and value["renderToolClosure"] == approval["probedClosure"],
             "OCI render image/tool closure is stale")
    _require(value["proofTools"] == tools and set(tools) == {"ffmpeg", "ffprobe"}, "host proof decoders are stale")
    for row in tools.values():
        _require(set(row) == {"path", "sha256"} and bool(SHA.fullmatch(row["sha256"])), "proof decoder receipt malformed")


def _source_rows(rows: object) -> None:
    """Hash only canonical repo-relative captured files, never artifact-chosen host paths."""
    _require(isinstance(rows, list) and bool(rows), "OCI execution source closure is absent")
    paths = []
    for row in rows:
        _require(isinstance(row, dict) and set(row) == {"path", "sha256"}, "OCI source row malformed")
        relative = row["path"]
        _require(isinstance(relative, str) and not relative.startswith("/") and ".." not in relative.split("/"),
                 "OCI source path is unsafe")
        _require(relative.startswith(("scripts/producer/", "templates/motion/")), "OCI source path is out of scope")
        path = ROOT / relative
        _require(path.resolve(strict=True) == path and file_hash(path) == row["sha256"], "OCI execution source changed")
        paths.append(relative)
    _require(paths == sorted(set(paths)), "OCI source inventory repeats or is unordered")


def _evidence(value: dict) -> None:
    """Keep reviewed compact integrity and deep private evidence explicitly distinct."""
    raw = value["rawEvidence"]
    _require(isinstance(raw, dict) and set(raw) == {"receiptHash", "inputsSha256", "auditSources", "checks",
                                                  "privateEvidenceRequiredForDeepRevalidation"}, "raw evidence binding malformed")
    _require(all(isinstance(raw[key], str) and SHA.fullmatch(raw[key]) for key in ("receiptHash", "inputsSha256")),
             "raw evidence digests malformed")
    _require(raw["checks"] == CHECKS and raw["privateEvidenceRequiredForDeepRevalidation"] is True,
             "compact receipt cannot replace deep private evidence")
    _source_rows(raw["auditSources"])
    observation = value["runnerObservation"]
    _require(isinstance(observation, dict) and set(observation) == {"startupCapture", "observedAfterStartSha256"},
             "runner observation malformed")
    _require(observation["startupCapture"] == "unavailable" and bool(SHA.fullmatch(observation["observedAfterStartSha256"])),
             "this cohort has no provable runner startup capture")


def _probes(rows: object, capabilities: dict) -> None:
    """Require all exact pairs and re-check every retained stream fact."""
    _require(isinstance(rows, list), "OCI probes are not a list")
    expected = {(kind, rate) for kind in capabilities for rate in RELEASED_RATES}
    _require(len(rows) == len(expected), "OCI probe cross-product is incomplete")
    pairs = []
    for row in rows:
        _require(isinstance(row, dict) and set(row) == ROW_KEYS, "OCI probe fields malformed")
        pair = (row["kind"], row["rate"])
        _require(pair in expected, "OCI probe kind/rate is unsupported")
        _require(row["duration"] == _duration_for(row["rate"]) and row["decoded"] is True,
                 "OCI probe duration/decode is malformed")
        hashes = ("mediaSha256", "inputSha256", "runtimeReceiptSha256", "sourceSha256", "specHash")
        _require(all(isinstance(row[key], str) and SHA.fullmatch(row[key]) for key in hashes), "OCI probe digests malformed")
        _require(row["checks"] == CHECKS and type(row["elapsedMs"]) is int and row["elapsedMs"] > 0,
                 "OCI probe checks/timing malformed")
        _require(not _stream_issue(row["stream"], row["rate"], capabilities[row["kind"]]["canvas"]), "OCI stream facts failed")
        pairs.append(pair)
    _require(pairs == sorted(expected), "OCI probe pairs repeat, are missing, or are unordered")


def validate_oci_receipt(value: object, reviewed_hash: str, tools: dict | None = None) -> str:
    """Return an issue or validate reviewed compact integrity, not raw availability."""
    try:
        _require(isinstance(value, dict), "OCI receipt is not an object")
        capabilities = _current_capabilities()
        _header(value, reviewed_hash, capabilities)
        _runtime_identity(value, tools if tools is not None else current_proof_tools())
        _source_rows(value["executionSources"])
        _evidence(value)
        _probes(value["probes"], capabilities)
        return ""
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError) as exc:
        return str(exc) or "OCI receipt is malformed"


def load_oci_receipt(path: Path, reviewed_hash: str) -> tuple[dict | None, str]:
    """Read one bounded reviewed receipt without running Docker or decoding media."""
    try:
        value = bound_json(path)
    except (OSError, RuntimeError, ValueError, UnicodeDecodeError) as exc:
        return None, f"OCI receipt is unreadable: {exc}"
    issue = validate_oci_receipt(value, reviewed_hash)
    return (None, issue) if issue else (value, "")

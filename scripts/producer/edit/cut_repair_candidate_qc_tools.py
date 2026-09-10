"""Pinned tool-manifest validation for candidate-bound cut-repair QC."""
from __future__ import annotations

import os
import sys

from edit.cut_repair_candidate_qc_types import (
    AlignerTool,
    CandidateQcContractError,
    QcTools,
    ToolFile,
    VisualImplementationFile,
    VisualOracleTool,
)
from edit.cut_repair_context_sources import (
    digest,
    require_hash,
    require_keys,
    stable_file_digest,
    stable_json,
)
from edit.cut_repair_visual_lip_sync_types import (
    VISUAL_IMPLEMENTATION_NONCLAIMS,
    VISUAL_IMPLEMENTATION_SCOPE,
)

_TOOL_KEYS = {"path", "sha256"}
_WHISPER_KEYS = {"path", "sha256", "modelPath", "modelSha256"}
_ALIGNER_KEYS = {
    "protocol", "runtimePath", "runtimeSha256",
    "implementationPath", "implementationSha256",
    "policyPath", "policySha256",
}
_VISUAL_KEYS = _ALIGNER_KEYS | {
    "implementationScope", "implementationNonClaims",
    "implementationClosureHash", "implementationFiles"}
_VISUAL_FILE_KEYS = {"role", "path", "sha256"}
_ALIGNMENT_PROTOCOL = "deterministic-source-waveform-v1"
_VISUAL_PROTOCOL = "deterministic-selected-source-av-offset-v1"


def approved_alignment_paths() -> tuple[str, str, str]:
    """Return the only runtime/implementation/policy production may admit."""
    producer = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    return (
        os.path.realpath(sys.executable),
        os.path.realpath(os.path.join(
            os.path.dirname(__file__),
            "source_waveform_alignment_adapter.py")),
        os.path.realpath(os.path.join(
            producer, "contracts",
            "cut-repair-source-waveform-alignment-policy-v1.json")),
    )


def approved_visual_oracle_paths() -> tuple[str, str, str]:
    """Return the only visual-oracle runtime/implementation/policy paths."""
    producer = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    return (
        os.path.realpath(sys.executable),
        os.path.realpath(os.path.join(
            os.path.dirname(__file__), "cut_repair_visual_lip_sync.py")),
        os.path.realpath(os.path.join(
            producer, "contracts",
            "cut-repair-visual-lip-sync-policy-v1.json")),
    )


def approved_visual_oracle_files() -> tuple[tuple[str, str], ...]:
    """Return only repository code that computes/maps/seals a visual pass.

    QC orchestration, storage, promotion, Python stdlib, OS code, and dynamic
    libraries are explicit nonclaims carried in the manifest and receipt.
    """
    root = os.path.dirname(__file__)
    return tuple((role, os.path.realpath(os.path.join(root, name))) for
                 role, name in (
                     ("controller", "cut_repair_visual_lip_sync.py"),
                     ("media-decoder", "cut_repair_visual_lip_sync_media.py"),
                     ("receipt-projector",
                      "cut_repair_visual_lip_sync_receipt.py"),
                     ("visual-value-types",
                      "cut_repair_visual_lip_sync_types.py"),
                     ("authority-hashing", "cut_repair_context_sources.py"),
                     ("candidate-qc-value-types",
                      "cut_repair_candidate_qc_types.py"),
                     ("candidate-qc-visual-adapter",
                      "cut_repair_candidate_qc_visual.py"),
                     ("candidate-qc-seam-projector",
                      "cut_repair_candidate_qc_receipts.py"),
                     ("visual-seam-contract",
                      "cut_repair_visual_lip_sync_contract.py"),
                 ))


def _canonical_producer(producer: str) -> str:
    lexical = os.path.abspath(producer)
    if lexical != producer or os.path.realpath(lexical) != lexical \
            or not os.path.isdir(lexical) or os.path.islink(lexical):
        raise CandidateQcContractError(
            "producer directory must be canonical and real")
    return lexical


def _inside(path: str, root: str) -> str:
    if os.path.abspath(path) != path or os.path.realpath(path) != path \
            or os.path.islink(path) \
            or os.path.commonpath([root, path]) != root:
        raise CandidateQcContractError(
            "QC tool manifest escapes producer authority")
    return path


def _tool_file(value: object, keys: set[str], label: str) -> dict:
    if not isinstance(value, dict):
        raise CandidateQcContractError(f"{label} is not an object")
    require_keys(value, keys, keys, label)
    return value


def pinned_file(path: object, expected: object, label: str) -> ToolFile:
    """Reopen one canonical regular file and require its sealed digest."""
    if not isinstance(path, str) or os.path.abspath(path) != path \
            or os.path.realpath(path) != path or os.path.islink(path):
        raise CandidateQcContractError(f"{label} path is not canonical")
    expected_hash = require_hash(expected, f"{label} hash")
    if stable_file_digest(path, label) != expected_hash:
        raise CandidateQcContractError(f"TOOL_DRIFT:{label}")
    return ToolFile(path, expected_hash)


def _aligner(value: object) -> AlignerTool | None:
    if value is None:
        return None
    row = _tool_file(value, _ALIGNER_KEYS, "independent aligner tool")
    if row["protocol"] != _ALIGNMENT_PROTOCOL:
        raise CandidateQcContractError(
            "independent aligner protocol is unsupported")
    result = AlignerTool(
        _ALIGNMENT_PROTOCOL,
        pinned_file(
            row["runtimePath"], row["runtimeSha256"],
            "independent aligner runtime"),
        pinned_file(
            row["implementationPath"], row["implementationSha256"],
            "independent aligner implementation"),
        pinned_file(
            row["policyPath"], row["policySha256"],
            "independent aligner policy"),
    )
    observed_paths = (
        result.runtime.path, result.implementation.path, result.policy.path)
    if observed_paths != approved_alignment_paths():
        raise CandidateQcContractError(
            "independent aligner is not the repository-approved toolchain")
    return result


def _visual_oracle(value: object) -> VisualOracleTool | None:
    if value is None:
        return None
    row = _tool_file(value, _VISUAL_KEYS, "visual lip-sync oracle")
    if row["protocol"] != _VISUAL_PROTOCOL:
        raise CandidateQcContractError(
            "visual lip-sync oracle protocol is unsupported")
    files = _visual_files(row)
    nonclaims = row.get("implementationNonClaims")
    if row.get("implementationScope") != VISUAL_IMPLEMENTATION_SCOPE \
            or nonclaims != list(VISUAL_IMPLEMENTATION_NONCLAIMS):
        raise CandidateQcContractError(
            "visual implementation scope or nonclaims are stale")
    closure = require_hash(
        row["implementationClosureHash"], "visual implementation closure")
    closure_value = [
        {"role": item.role, "path": item.file.path,
         "sha256": item.file.sha256} for item in files]
    if closure != digest(closure_value):
        raise CandidateQcContractError(
            "visual implementation closure is stale")
    result = VisualOracleTool(
        _VISUAL_PROTOCOL,
        pinned_file(
            row["runtimePath"], row["runtimeSha256"],
            "visual oracle runtime"),
        pinned_file(
            row["implementationPath"], row["implementationSha256"],
            "visual oracle implementation"),
        VISUAL_IMPLEMENTATION_SCOPE,
        VISUAL_IMPLEMENTATION_NONCLAIMS,
        pinned_file(
            row["policyPath"], row["policySha256"],
            "visual oracle policy"),
        closure,
        files,
    )
    if (result.runtime.path, result.implementation.path, result.policy.path) \
            != approved_visual_oracle_paths():
        raise CandidateQcContractError(
            "visual lip-sync oracle is not repository-approved")
    return result


def _visual_files(row: dict) -> tuple[VisualImplementationFile, ...]:
    supplied = row.get("implementationFiles")
    if not isinstance(supplied, list):
        raise CandidateQcContractError(
            "visual implementation files are absent")
    expected = approved_visual_oracle_files()
    if len(supplied) != len(expected):
        raise CandidateQcContractError(
            "visual implementation closure is incomplete")
    result = []
    for value, (role, path) in zip(supplied, expected):
        item = _tool_file(
            value, _VISUAL_FILE_KEYS, "visual implementation file")
        if item.get("role") != role or item.get("path") != path:
            raise CandidateQcContractError(
                "visual implementation closure is not repository-approved")
        result.append(VisualImplementationFile(
            role, pinned_file(
                path, item.get("sha256"), f"visual {role} implementation")))
    return tuple(result)


def load_qc_tools(producer: str, manifest_path: str) -> QcTools:
    """Validate one sealed tool manifest and every referenced byte."""
    producer = _canonical_producer(producer)
    manifest_path = _inside(manifest_path, producer)
    manifest, raw_hash = stable_json(manifest_path, "QC tool manifest")
    keys = {
        "schemaVersion", "kind", "ffmpeg", "whisper",
        "independentAligner", "visualLipSyncOracle", "authorityHash",
    }
    require_keys(manifest, keys, keys, "QC tool manifest")
    core = {key: value for key, value in manifest.items()
            if key != "authorityHash"}
    supplied = require_hash(manifest.get("authorityHash"), "tool authority")
    if supplied != digest(core) or manifest.get("schemaVersion") != 1 \
            or manifest.get("kind") != "cut-repair-qc-tool-manifest":
        raise CandidateQcContractError("QC tool manifest is stale")
    ffmpeg = _tool_file(manifest["ffmpeg"], _TOOL_KEYS, "ffmpeg tool")
    whisper = _tool_file(
        manifest["whisper"], _WHISPER_KEYS, "whisper tool")
    aligner = _aligner(manifest["independentAligner"])
    visual = _visual_oracle(manifest["visualLipSyncOracle"])
    result = QcTools(
        raw_hash,
        pinned_file(ffmpeg["path"], ffmpeg["sha256"], "ffmpeg runtime"),
        pinned_file(
            whisper["path"], whisper["sha256"], "whisper runtime"),
        pinned_file(
            whisper["modelPath"], whisper["modelSha256"], "whisper model"),
        aligner,
        visual,
    )
    if aligner and (
            aligner.runtime.sha256 == result.whisper.sha256
            or aligner.implementation.sha256
            in {result.whisper.sha256, result.whisper_model.sha256}
            or aligner.policy.sha256 == result.whisper_model.sha256):
        raise CandidateQcContractError(
            "independent aligner cannot reuse Whisper runtime/model bytes")
    if visual and aligner and (
            visual.implementation.sha256 == aligner.implementation.sha256
            or visual.policy.sha256 == aligner.policy.sha256):
        raise CandidateQcContractError(
            "visual oracle cannot reuse alignment implementation/policy bytes")
    return result


def reobserve_tools(tools: QcTools) -> None:
    """Reject any runtime, model, or cache replacement during execution."""
    rows = [tools.ffmpeg, tools.whisper, tools.whisper_model]
    if tools.aligner:
        rows.extend([
            tools.aligner.runtime, tools.aligner.implementation,
            tools.aligner.policy])
    if tools.visual_oracle:
        rows.extend([
            tools.visual_oracle.runtime,
            tools.visual_oracle.implementation,
            tools.visual_oracle.policy])
        rows.extend(
            item.file for item in tools.visual_oracle.implementation_files)
    for row in rows:
        if stable_file_digest(row.path, "QC tool reobservation") != row.sha256:
            raise CandidateQcContractError("TOOL_DRIFT_DURING_QC")

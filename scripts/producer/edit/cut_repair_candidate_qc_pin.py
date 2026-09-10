#!/usr/bin/env python3
"""Pin the exact local tools admitted to candidate-bound cut-repair QC."""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass

from edit.cut_repair_candidate_qc_store import publish_json
from edit.cut_repair_candidate_qc_tools import (
    approved_alignment_paths,
    approved_visual_oracle_files,
    approved_visual_oracle_paths,
)
from edit.cut_repair_context_sources import digest, stable_file_digest
from edit.cut_repair_visual_lip_sync_types import (
    VISUAL_IMPLEMENTATION_NONCLAIMS,
    VISUAL_IMPLEMENTATION_SCOPE,
)


@dataclass(frozen=True)
class PinRequest:
    """Requested local tool paths."""

    ffmpeg: str
    whisper: str
    whisper_model: str
    aligner_runtime: str | None
    aligner_implementation: str | None
    aligner_policy: str | None
    visual_runtime: str | None
    visual_implementation: str | None
    visual_policy: str | None


def _file(path: str, label: str) -> tuple[str, str]:
    resolved = os.path.realpath(os.path.abspath(path))
    if os.path.islink(resolved) or not os.path.isfile(resolved):
        raise ValueError(f"{label} is not a regular file")
    return resolved, stable_file_digest(resolved, label)


def _tool(path: str, label: str) -> dict:
    resolved, value_hash = _file(path, label)
    return {"path": resolved, "sha256": value_hash}


def _whisper(request: PinRequest) -> dict:
    runtime = _tool(request.whisper, "Whisper runtime")
    model_path, model_hash = _file(
        request.whisper_model, "Whisper model")
    return {
        **runtime, "modelPath": model_path, "modelSha256": model_hash}


def _aligner(request: PinRequest) -> dict | None:
    supplied = (
        request.aligner_runtime, request.aligner_implementation,
        request.aligner_policy)
    if all(value is None for value in supplied):
        return None
    if any(value is None for value in supplied):
        raise ValueError(
            "aligner runtime, implementation, and policy are all required")
    runtime_path, runtime_hash = _file(
        request.aligner_runtime or "", "independent aligner runtime")
    implementation_path, implementation_hash = _file(
        request.aligner_implementation or "",
        "independent aligner implementation")
    policy_path, policy_hash = _file(
        request.aligner_policy or "", "independent aligner policy")
    if (runtime_path, implementation_path, policy_path) \
            != approved_alignment_paths():
        raise ValueError(
            "only the repository-approved source-waveform toolchain "
            "may be pinned")
    return {
        "protocol": "deterministic-source-waveform-v1",
        "runtimePath": runtime_path,
        "runtimeSha256": runtime_hash,
        "implementationPath": implementation_path,
        "implementationSha256": implementation_hash,
        "policyPath": policy_path,
        "policySha256": policy_hash,
    }


def _visual_oracle(request: PinRequest) -> dict | None:
    supplied = (
        request.visual_runtime, request.visual_implementation,
        request.visual_policy)
    if all(value is None for value in supplied):
        return None
    if any(value is None for value in supplied):
        raise ValueError(
            "visual runtime, implementation, and policy are all required")
    paths = tuple(_file(value or "", f"visual oracle {label}")[0]
                  for value, label in zip(
                      supplied, ("runtime", "implementation", "policy")))
    if paths != approved_visual_oracle_paths():
        raise ValueError(
            "only the repository-approved visual oracle may be pinned")
    hashes = tuple(
        stable_file_digest(path, "visual oracle pin") for path in paths)
    files = _visual_files()
    return {
        "protocol": "deterministic-selected-source-av-offset-v1",
        "runtimePath": paths[0], "runtimeSha256": hashes[0],
        "implementationPath": paths[1], "implementationSha256": hashes[1],
        "implementationScope": VISUAL_IMPLEMENTATION_SCOPE,
        "implementationNonClaims": list(VISUAL_IMPLEMENTATION_NONCLAIMS),
        "policyPath": paths[2], "policySha256": hashes[2],
        "implementationClosureHash": digest(files),
        "implementationFiles": files,
    }


def _visual_files() -> list[dict]:
    rows = []
    for role, expected in approved_visual_oracle_files():
        path, value_hash = _file(expected, f"visual oracle {role}")
        if path != expected:
            raise ValueError(
                "visual implementation closure is not repository-approved")
        rows.append({"role": role, "path": path, "sha256": value_hash})
    return rows


def pin_tool_manifest(output_path: str, request: PinRequest) -> dict:
    """Publish one sealed manifest; a changed existing pin is a conflict."""
    core = {
        "schemaVersion": 1,
        "kind": "cut-repair-qc-tool-manifest",
        "ffmpeg": _tool(request.ffmpeg, "FFmpeg runtime"),
        "whisper": _whisper(request),
        "independentAligner": _aligner(request),
        "visualLipSyncOracle": _visual_oracle(request),
    }
    value = {**core, "authorityHash": digest(core)}
    manifest_hash = publish_json(output_path, value)
    return {
        "ok": True,
        "kind": value["kind"],
        "manifestHash": manifest_hash,
        "manifestPath": output_path,
        "independentAlignerConfigured":
            value["independentAligner"] is not None,
        "visualLipSyncOracleConfigured":
            value["visualLipSyncOracle"] is not None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_path")
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--whisper", required=True)
    parser.add_argument("--whisper-model", required=True)
    parser.add_argument("--aligner-runtime")
    parser.add_argument("--aligner-implementation")
    parser.add_argument("--aligner-policy")
    parser.add_argument("--visual-runtime")
    parser.add_argument("--visual-implementation")
    parser.add_argument("--visual-policy")
    args = parser.parse_args()
    request = PinRequest(
        args.ffmpeg, args.whisper, args.whisper_model,
        args.aligner_runtime, args.aligner_implementation,
        args.aligner_policy, args.visual_runtime,
        args.visual_implementation, args.visual_policy)
    try:
        result = pin_tool_manifest(
            os.path.abspath(args.output_path), request)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({
            "ok": False,
            "blocker": {
                "code": "QC_TOOL_PIN_REJECTED", "message": str(exc)},
        }, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Cheap freshness contract for retained P0 dirty/forced parity evidence."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from current_render_graph_contract import file_hash, object_hash
from current_render_toolchain import current_toolchain_hash
from render_effect_registry import registry_hash

REPO = Path(__file__).resolve().parents[3]
RETAINED_ROOT = (
    REPO / "artifacts" / "p0-render-effect-parity-canonical-closure-v1")
BASELINES = REPO / "artifacts" / "p0-current-baselines-20260729"
CASES = ("short", "lf14")
SHA256 = re.compile(r"^[0-9a-f]{64}$")

_SUMMARY_KEYS = {
    "schemaVersion", "kind", "baseline", "baselinePlanSha256",
    "manifestSha256", "incrementalGraphHash", "toolchainHash",
    "forcedToolchainHash", "currentToolchainHash", "toolchainFresh",
    "registryHash", "registryFresh", "incrementalFinalSha256",
    "forcedFinalSha256", "dirtyNodeIds", "reusedNodeIds",
    "forcedExecutionMode", "oraclePassed", "timings", "graphNodeCount",
}
_ORACLE_KEYS = {
    "schemaVersion", "kind", "policy", "policyHash", "toolchain",
    "incremental", "forcedFull", "pictureComparison",
    "decodedAudioMatch", "streamFactsMatch", "byteIdentical",
    "passed", "receiptHash",
}
_MEDIA_KEYS = {
    "path", "fileSha256", "sizeBytes", "pictureFrameMd5Sha256",
    "pcmSha256", "pcmBytes", "streamFacts",
}


class ParityArtifactError(RuntimeError):
    """Retained parity evidence is missing, malformed, or stale."""


@dataclass(frozen=True)
class CasePaths:
    """Exact retained paths for one short/LF-14 evidence case."""

    root: Path
    summary: Path
    oracle: Path
    incremental: Path
    forced: Path
    plan: Path
    manifest: Path


def _regular_file(path: Path, owner: Path | None = None) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ParityArtifactError(f"retained evidence file is unavailable: {path}")
    resolved = path.resolve(strict=True)
    if owner is not None:
        try:
            resolved.relative_to(owner.resolve(strict=True))
        except ValueError as exc:
            raise ParityArtifactError(
                f"retained evidence escapes its case root: {path}") from exc
    return resolved


def _read_object(path: Path, owner: Path) -> dict:
    try:
        value = json.loads(
            _regular_file(path, owner).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ParityArtifactError(
            f"retained evidence is unreadable: {path}") from exc
    if type(value) is not dict:
        raise ParityArtifactError(f"retained evidence is not an object: {path}")
    return value


def _case_paths(root: Path, case: str) -> CasePaths:
    if case not in CASES:
        raise ParityArtifactError(f"unknown retained parity case: {case}")
    case_root = root / case
    baseline = BASELINES / case
    return CasePaths(
        root=case_root,
        summary=case_root / "render-effect-parity-summary-v1.json",
        oracle=case_root / "04-oracle.json",
        incremental=case_root / "incremental" / "final.mp4",
        forced=case_root / "forced" / "final.mp4",
        plan=baseline / "edit_plan.json",
        manifest=baseline / "asset_manifest.json",
    )


def _verify_tool_record(value: object, label: str) -> None:
    if type(value) is not dict or set(value) != {"path", "sha256"}:
        raise ParityArtifactError(f"{label} tool record is malformed")
    raw_path, digest = value["path"], value["sha256"]
    if type(raw_path) is not str or not Path(raw_path).is_absolute():
        raise ParityArtifactError(f"{label} tool path is not absolute")
    path = _regular_file(Path(raw_path))
    if digest != file_hash(path):
        raise ParityArtifactError(f"{label} tool hash is stale")


def _verify_oracle_toolchain(value: object) -> None:
    expected = {"ffmpeg", "ffprobe", "oracle"}
    if type(value) is not dict or set(value) != expected:
        raise ParityArtifactError("retained oracle toolchain is malformed")
    for name in sorted(expected):
        _verify_tool_record(value[name], name)


def _verify_media(value: object, expected: Path, owner: Path) -> str:
    if type(value) is not dict or set(value) != _MEDIA_KEYS:
        raise ParityArtifactError("retained oracle media record is malformed")
    path = _regular_file(expected, owner)
    if value["path"] != str(path):
        raise ParityArtifactError("retained oracle media path drifted")
    digest = file_hash(path)
    if value["fileSha256"] != digest:
        raise ParityArtifactError("retained oracle media hash is stale")
    if value["sizeBytes"] != path.stat().st_size:
        raise ParityArtifactError("retained oracle media size is stale")
    for key in ("pictureFrameMd5Sha256", "pcmSha256"):
        if type(value[key]) is not str or not SHA256.fullmatch(value[key]):
            raise ParityArtifactError("retained decoded-media hash is malformed")
    return digest


def _verify_oracle(paths: CasePaths) -> tuple[dict, str, str]:
    value = _read_object(paths.oracle, paths.root)
    body = {key: item for key, item in value.items() if key != "receiptHash"}
    if set(value) != _ORACLE_KEYS:
        raise ParityArtifactError("retained oracle shape is malformed")
    if (
        value["schemaVersion"] != 1
        or value["kind"] != "current-render-forced-full-oracle"
        or value["receiptHash"] != object_hash(body)
        or value["policyHash"] != object_hash(value["policy"])
        or value["passed"] is not True
        or value["decodedAudioMatch"] is not True
        or value["streamFactsMatch"] is not True
    ):
        raise ParityArtifactError("retained oracle receipt is invalid")
    _verify_oracle_toolchain(value["toolchain"])
    incremental = _verify_media(
        value["incremental"], paths.incremental, paths.root)
    forced = _verify_media(value["forcedFull"], paths.forced, paths.root)
    return value, incremental, forced


def _verify_summary(
    paths: CasePaths,
    oracle: dict,
    media_hashes: tuple[str, str],
) -> dict:
    value = _read_object(paths.summary, paths.root)
    current_toolchain, current_registry = (
        current_toolchain_hash(), registry_hash())
    if set(value) != _SUMMARY_KEYS:
        raise ParityArtifactError("retained parity summary shape is malformed")
    if (
        value["schemaVersion"] != 1
        or value["kind"] != "render-effect-dirty-forced-parity"
        or value["baseline"] != paths.root.name
        or value["toolchainFresh"] is not True
        or value["registryFresh"] is not True
        or value["oraclePassed"] is not True
        or oracle["passed"] is not True
    ):
        raise ParityArtifactError("retained parity summary is not passing")
    tool_hashes = {
        value[key] for key in (
            "toolchainHash", "forcedToolchainHash", "currentToolchainHash")
    }
    if tool_hashes != {current_toolchain}:
        raise ParityArtifactError("retained parity toolchain is stale")
    if value["registryHash"] != current_registry:
        raise ParityArtifactError("retained parity registry is stale")
    expected_hashes = (value["incrementalFinalSha256"],
                       value["forcedFinalSha256"])
    if expected_hashes != media_hashes:
        raise ParityArtifactError("retained parity summary media drifted")
    return value


def validate_case(root: Path, case: str) -> dict:
    """Validate one retained case without invoking a renderer or decoder."""
    paths = _case_paths(root, case)
    if paths.root.is_symlink() or not paths.root.is_dir():
        raise ParityArtifactError(f"retained parity case is absent: {case}")
    oracle, incremental, forced = _verify_oracle(paths)
    summary = _verify_summary(paths, oracle, (incremental, forced))
    if summary["baselinePlanSha256"] != file_hash(
            _regular_file(paths.plan, BASELINES / case)):
        raise ParityArtifactError("retained parity baseline plan is stale")
    if summary["manifestSha256"] != file_hash(
            _regular_file(paths.manifest, BASELINES / case)):
        raise ParityArtifactError("retained parity manifest is stale")
    return summary


def validate_retained_parity(root: Path = RETAINED_ROOT) -> dict[str, dict]:
    """Validate the exact two-case release root without rerendering."""
    if root.is_symlink() or not root.is_dir():
        raise ParityArtifactError("retained parity evidence root is unavailable")
    directories = {path.name for path in root.iterdir() if path.is_dir()}
    if directories != set(CASES):
        raise ParityArtifactError(
            "retained parity evidence root has an unexpected case set")
    return {case: validate_case(root, case) for case in CASES}

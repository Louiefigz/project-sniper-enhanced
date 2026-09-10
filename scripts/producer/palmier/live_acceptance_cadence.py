"""Long-form cadence approval and normalized edit-time authority."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cut_manifestation_authority import verify_manifestation
from fingerprints import file_sha256
from ingest_execution_authority import verify_execution_media_authority
from qualification_cadence_approval import verify_cadence_approval
from qualification_mezzanine_files import observe_qualified_output
from transcript_cut_contract import check as check_transcript_cuts

from palmier.mcp_client import PalmierError

_SHA = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class CadenceAuthorityInput:
    """Inputs whose exact bytes must share one normalized media authority."""

    config: Any
    paths: dict
    plan: dict
    manifest: dict


def _approval(config: Any) -> tuple[dict, str]:
    path = getattr(config, "cadence_approval_path", None)
    digest = getattr(config, "cadence_approval_digest", None)
    if not isinstance(path, str) or not isinstance(digest, str) \
            or not _SHA.fullmatch(digest):
        raise PalmierError(
            "long acceptance requires cadence approval path and digest")
    absolute = os.path.abspath(path)
    if os.path.islink(absolute) or not os.path.isfile(absolute):
        raise PalmierError("long cadence approval is not a regular file")
    try:
        document = verify_cadence_approval(absolute)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise PalmierError(f"long cadence approval is invalid: {exc}") from exc
    if document.get("approvalDigest") != digest:
        raise PalmierError("long cadence approval digest does not match")
    return document, absolute


def _normalized(document: dict, config: Any) -> dict:
    media = document.get("media") or {}
    normalized = media.get("normalized") or {}
    downstream = document.get("downstreamTimeAuthority") or {}
    path, digest = normalized.get("path"), normalized.get("sha256")
    video = normalized.get("video") or {}
    source_hash = (media.get("source") or {}).get("sha256")
    valid = (
        isinstance(path, str) and os.path.isabs(path)
        and isinstance(digest, str) and _SHA.fullmatch(digest)
        and downstream.get("mediaPath") == path
        and downstream.get("mediaSha256") == digest
        and downstream.get("transcriptAndCutsMustBindThisAsset") is True
        and downstream.get("rawSourceIsNotEditTimeAuthority") is True
        and source_hash != digest
        and video.get("rate") == f"{config.fps}/1"
    )
    if not valid:
        raise PalmierError(
            "cadence approval does not declare normalized edit-time authority")
    try:
        observed = observe_qualified_output(path)
    except (OSError, RuntimeError) as exc:
        raise PalmierError(
            f"normalized cadence media cannot be reobserved: {exc}") from exc
    if observed.sha256 != digest \
            or observed.size_bytes != normalized.get("sizeBytes"):
        raise PalmierError("normalized cadence media bytes changed")
    return {
        "path": path, "sha256": digest, "sizeBytes": observed.size_bytes,
        "sourceSha256": source_hash, "video": video,
        "audio": normalized.get("audio"),
    }


def _used_sources(authority: CadenceAuthorityInput,
                  normalized: dict) -> list[dict]:
    plan, manifest = authority.plan, authority.manifest
    used = {row.get("sourceId") for row in plan.get("cutTrack") or []
            if isinstance(row, dict)}
    sources = manifest.get("sources")
    if not used or not isinstance(sources, list):
        raise PalmierError("long plan has no manifest source authority")
    rows = [row for row in sources if isinstance(row, dict)
            and row.get("id") in used]
    if len(rows) != len(used):
        raise PalmierError("long plan references a missing manifest source")
    expected = normalized["sha256"]
    for row in rows:
        path = row.get("path")
        if row.get("sourceSha256") != expected \
                or not isinstance(path, str) or not os.path.isfile(path) \
                or os.path.islink(path) or file_sha256(path) != expected:
            raise PalmierError(
                "long manifest does not admit normalized cadence media")
    try:
        admitted = verify_execution_media_authority(
            plan, manifest, authority.paths["manifest"])
    except RuntimeError as exc:
        raise PalmierError(
            f"normalized cadence media is not admitted: {exc}") from exc
    if admitted is not True:
        raise PalmierError(
            "normalized cadence media lacks admitted source-set authority")
    return rows


def _transcript_cut(authority: CadenceAuthorityInput) -> dict:
    result = check_transcript_cuts(
        authority.paths["plan"], authority.config.transcripts_dir,
        authority.paths["manifest"])
    if result.get("ok") is not True:
        errors = "; ".join(str(row) for row in result.get("errors") or [])
        raise PalmierError(
            f"normalized transcript/cut authority failed: {errors}")
    receipt = ((result.get("metrics") or {}).get("receipt"))
    if not isinstance(receipt, dict):
        raise PalmierError("normalized transcript/cut receipt is missing")
    return receipt


def _cut(authority: CadenceAuthorityInput, source_ids: set[str]) -> dict:
    try:
        record = verify_manifestation(
            authority.config.out_dir, authority.plan)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise PalmierError(
            f"normalized cut manifestation is invalid: {exc}") from exc
    part_ids = {row.get("sourceId") for row in record.get("parts") or []
                if isinstance(row, dict)}
    if part_ids != source_ids:
        raise PalmierError(
            "cut manifestation does not use the normalized source set")
    return {
        "manifestationReceiptHash": record["receiptHash"],
        "timelineMapSha256": record["timelineMapSha256"],
        "planCutTrackHash": record["planCutTrackHash"],
        "sourceIds": sorted(part_ids),
    }


def verify_longform_cadence(
        config: Any, paths: dict, plan: dict, manifest: dict) -> dict | None:
    """Prove long-form edit time descends from the normalized admitted MP4."""
    if config.format != "long":
        unexpected = (
            getattr(config, "cadence_approval_path", None),
            getattr(config, "cadence_approval_digest", None),
        )
        if any(value is not None for value in unexpected):
            raise PalmierError(
                "short acceptance cannot consume long cadence authority")
        return None
    document, approval_path = _approval(config)
    normalized = _normalized(document, config)
    authority = CadenceAuthorityInput(config, paths, plan, manifest)
    sources = _used_sources(authority, normalized)
    source_ids = {str(row["id"]) for row in sources}
    transcript = _transcript_cut(authority)
    cut = _cut(authority, source_ids)
    return {
        "approvalPath": approval_path,
        "approvalFileSha256": file_sha256(approval_path),
        "approvalDigest": document["approvalDigest"],
        "normalizedMedia": normalized,
        "manifest": {
            "sha256": file_sha256(paths["manifest"]),
            "sourceIds": sorted(source_ids),
            "sourceSha256": normalized["sha256"],
        },
        "transcriptAndPlan": {
            key: transcript[key] for key in (
                "planHash", "manifestHash", "transcriptDigest",
                "cutTrackDigest", "cutDecisionsDigest")
        },
        "cut": cut,
    }

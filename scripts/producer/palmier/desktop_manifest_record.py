"""Serialize a prepared Desktop Palmier stage into immutable authority bytes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fingerprints import file_sha256
from palmier.desktop_quality import quality_contract
from palmier.desktop_state import DesktopStageInput


@dataclass(frozen=True)
class PreparedDesktopStage:
    """One prepared stage before its immutable manifest is serialized."""

    authority: Any
    steps: list[dict]
    capability: dict
    revision: dict | None = None


def manifest_content(inputs: DesktopStageInput,
                     prepared: PreparedDesktopStage) -> dict:
    """Build one exact operation manifest, including revision pages."""
    content = {
        "schemaVersion": 1, "kind": "palmier-desktop-operation-manifest",
        "stage": inputs.stage, "planHash": file_sha256(inputs.plan_path),
        "manifestHash": file_sha256(inputs.manifest_path),
        "checkpointKey": prepared.authority.checkpoint_key,
        "capability": prepared.capability,
        "qualityContract": quality_contract(), "steps": prepared.steps,
    }
    if prepared.revision is None:
        return content
    from palmier.revision_schema import write_revision
    saved = write_revision(inputs.out_dir, prepared.revision["revision"])
    content["revision"] = {
        "revisionSetId": prepared.revision["revision"]["revisionSetId"],
        "path": saved["path"], "hash": file_sha256(saved["path"]),
        "pages": prepared.revision["pages"],
    }
    return content

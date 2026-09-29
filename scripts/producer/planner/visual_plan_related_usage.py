"""Stable cross-project identity for selected visual-plan candidates."""
from __future__ import annotations

from planner.visual_plan_fields import (
    MODALITIES, VisualPlanContractError, id_field, object_field, sha_field,
    text_field,
)

RELATED_USE_KEYS = {
    "candidateId", "modality", "sourceRecordId", "sourceSha256", "familyId",
    "anatomy", "development", "planSha256",
}
SOURCE_MODALITIES = {
    "catalog", "source-footage", "supplied-broll", "external-media",
}


def validate_related_use(value: object, name: str) -> dict:
    """Validate stable source identity plus descriptive composition fields."""
    row = object_field(value, name, RELATED_USE_KEYS, set())
    id_field(row["candidateId"], f"{name} candidateId")
    if row["modality"] not in MODALITIES:
        raise VisualPlanContractError(f"{name} modality is invalid")
    id_field(row["familyId"], f"{name} familyId")
    text_field(row["anatomy"], f"{name} anatomy")
    text_field(row["development"], f"{name} development")
    sha_field(row["planSha256"], f"{name} planSha256")
    _validate_source_identity(row, name)
    return row


def _validate_source_identity(row: dict, name: str) -> None:
    """Require both source fields together for source-backed modalities."""
    record, sha256 = row["sourceRecordId"], row["sourceSha256"]
    if (record is None) != (sha256 is None):
        raise VisualPlanContractError(f"{name} source identity must be a complete pair")
    if record is not None:
        id_field(record, f"{name} sourceRecordId")
        sha_field(sha256, f"{name} sourceSha256")
    if row["modality"] in SOURCE_MODALITIES and record is None:
        raise VisualPlanContractError(f"{name} source-backed modality lacks stable identity")

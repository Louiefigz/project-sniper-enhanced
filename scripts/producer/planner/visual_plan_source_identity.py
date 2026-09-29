"""Stable source identities shared by visual-plan admission and allocation."""
from __future__ import annotations

MEDIA_MODALITIES = {"source-footage", "supplied-broll", "external-media"}


def source_identity(candidate: dict) -> tuple[str, str, str] | None:
    """Return modality + controller record + immutable source hash when present."""
    source = candidate.get("source")
    if not isinstance(source, dict):
        return None
    record_id = source.get("recordId")
    source_sha = source.get("sourceSha256", source.get("sha256"))
    modality = candidate.get("modality")
    if not all(isinstance(value, str) and value
               for value in (modality, record_id, source_sha)):
        return None
    return modality, record_id, source_sha


def same_source(left: dict, right: dict) -> bool:
    """Compare candidates by stable source identity rather than authored labels."""
    left_key, right_key = source_identity(left), source_identity(right)
    return left_key is not None and left_key == right_key


def source_repeat_differs(left: dict, right: dict) -> bool:
    """Return whether a sourced repeat names a different stable identity."""
    left_key, right_key = source_identity(left), source_identity(right)
    return (left_key is not None or right_key is not None) \
        and not same_source(left, right)

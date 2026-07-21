"""Closed R0 artifact-class profile for immutable generation commits."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from .generation_schema import GenerationCommitV1, GenerationManifestRowV1

R0_SINGLETON_ARTIFACT_CLASSES = (
    "approved-parent-v1",
    "generation-verification-v1",
    "request-identity-v1",
    "execution-policy-v1",
    "repair-policy-v1",
    "quality-policy-v1",
    "fallback-policy-v1",
    "admission-inputs-v1",
    "realization-inputs-v1",
    "generation-inputs-v1",
    "source-snapshot-manifest-v1",
    "operator-intent-v1",
    "cut-approval-v1",
    "asset-closure-v1",
    "runtime-capability-manifest-v1",
    "repair-state-v1",
    "realization-v1",
    "template-usage-approval-v1",
    "proxy-disposition-v1",
    "refit-disposition-v1",
    "plan-v1",
    "base-media-v1",
    "base-plan-v1",
    "base-receipt-v1",
    "base-fingerprint-v1",
    "timeline-map-v1",
    "prebound-clips-v1",
    "render-build-receipt-v1",
    "compositor-build-receipt-v1",
    "final-media-v1",
    "assembly-receipt-v1",
    "cover-image-v1",
    "cover-proof-v1",
    "audit-b-receipt-v1",
    "full-decode-proof-v1",
    "effect-proof-v1",
    "qc-receipt-v1",
    "final-approval-v3",
)

R0_GENERATION_ARTIFACT_CLASS_COUNTS: Mapping[str, int] = MappingProxyType(
    {
        **{artifact_class: 1 for artifact_class in R0_SINGLETON_ARTIFACT_CLASSES},
        "critic-receipt-v1": 2,
        "graphic-media-v1": 1,
        "graphic-render-receipt-v1": 1,
    }
)

_CONTROL_MAX_BYTES = 16 * 1024 * 1024
_COVER_MAX_BYTES = 64 * 1024 * 1024
_MEDIA_MAX_BYTES = 512 * 1024 * 1024
R0_MAX_PATH_DEPTH = 8
R0_MAX_AGGREGATE_BYTES = 2 * 1024 * 1024 * 1024
R0_MANIFEST_ROWS = sum(R0_GENERATION_ARTIFACT_CLASS_COUNTS.values())
R0_ARTIFACT_CLASS_BYTE_CAPS: Mapping[str, int] = MappingProxyType(
    {
        **{
            artifact_class: _CONTROL_MAX_BYTES
            for artifact_class in R0_GENERATION_ARTIFACT_CLASS_COUNTS
        },
        "base-media-v1": _MEDIA_MAX_BYTES,
        "final-media-v1": _MEDIA_MAX_BYTES,
        "graphic-media-v1": _MEDIA_MAX_BYTES,
        "cover-image-v1": _COVER_MAX_BYTES,
    }
)


class GenerationProfileError(RuntimeError):
    """An immutable generation does not match the closed R0 profile."""


def _approved_parent_row(commit: GenerationCommitV1) -> GenerationManifestRowV1:
    matches = tuple(
        row for row in commit.files if row.path == commit.approved_parent_path
    )
    if len(matches) != 1:
        raise GenerationProfileError(
            "R0 approvedParentPath must select exactly one row"
        )
    if matches[0].artifact_class != "approved-parent-v1":
        raise GenerationProfileError(
            "R0 approvedParentPath row must be approved-parent-v1"
        )
    return matches[0]


def _verify_r0_bounds(commit: GenerationCommitV1) -> None:
    if len(commit.files) != R0_MANIFEST_ROWS:
        raise GenerationProfileError(
            f"R0 generation requires exactly {R0_MANIFEST_ROWS} manifest rows"
        )
    paths = tuple(row.path for row in commit.files)
    if paths != tuple(sorted(paths)):
        raise GenerationProfileError("R0 manifest rows must be path ordered")
    aggregate = 0
    for row in commit.files:
        if row.size_bytes <= 0:
            raise GenerationProfileError(f"R0 artifact must be nonempty: {row.path}")
        if len(row.path.split("/")) > R0_MAX_PATH_DEPTH:
            raise GenerationProfileError(f"R0 artifact path is too deep: {row.path}")
        cap = R0_ARTIFACT_CLASS_BYTE_CAPS.get(row.artifact_class)
        if cap is not None and row.size_bytes > cap:
            raise GenerationProfileError(
                f"R0 artifact exceeds class byte cap: {row.artifact_class}"
            )
        aggregate += row.size_bytes
    if aggregate > R0_MAX_AGGREGATE_BYTES:
        raise GenerationProfileError("R0 generation exceeds aggregate byte cap")


def _verify_r0_counts(
    groups: Mapping[str, list[GenerationManifestRowV1]],
) -> None:
    mismatches = []
    for artifact_class, expected in R0_GENERATION_ARTIFACT_CLASS_COUNTS.items():
        actual = len(groups[artifact_class])
        if actual != expected:
            mismatches.append(f"{artifact_class} expected {expected}, got {actual}")
    if mismatches:
        details = "; ".join(mismatches)
        raise GenerationProfileError(f"R0 class cardinality mismatch: {details}")


def verify_r0_generation_profile(
    commit: GenerationCommitV1,
) -> Mapping[str, tuple[GenerationManifestRowV1, ...]]:
    """Verify the closed R0 class multiset and return immutable ordered groups."""
    if type(commit) is not GenerationCommitV1 or type(commit.files) is not tuple:
        raise GenerationProfileError("R0 profile input must be a GenerationCommitV1")
    if any(type(row) is not GenerationManifestRowV1 for row in commit.files):
        raise GenerationProfileError("R0 manifest rows must use the V1 wire type")
    unknown = next(
        (
            row.artifact_class
            for row in commit.files
            if row.artifact_class not in R0_GENERATION_ARTIFACT_CLASS_COUNTS
        ),
        None,
    )
    if unknown is not None:
        raise GenerationProfileError(
            f"R0 generation has unknown artifact class: {unknown}"
        )
    _verify_r0_bounds(commit)
    _approved_parent_row(commit)
    groups: dict[str, list[GenerationManifestRowV1]] = {
        artifact_class: [] for artifact_class in R0_GENERATION_ARTIFACT_CLASS_COUNTS
    }
    for row in commit.files:
        groups[row.artifact_class].append(row)
    _verify_r0_counts(groups)
    immutable = {name: tuple(rows) for name, rows in groups.items()}
    return MappingProxyType(immutable)

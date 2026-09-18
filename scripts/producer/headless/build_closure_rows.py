"""Closed source and tool rows used by build endpoint reobservation."""

from __future__ import annotations

from .build_receipt_binding import BuildReceiptBindingV1


class BuildClosureRowsError(RuntimeError):
    """Two retained build roles contradict one source path identity."""


def build_source_rows(value: BuildReceiptBindingV1) -> tuple[dict, ...]:
    """Return all role-tagged rows, permitting only exact shared sources."""
    groups = (
        ("compositor", value.compositor_receipt.manifest.implementation),
        ("render", value.render_receipt.manifest.implementation),
    )
    rows = tuple(
        {
            "role": role,
            "path": row.path,
            "sha256": row.sha256,
            "sizeBytes": row.size_bytes,
        }
        for role, values in groups
        for row in values
    )
    claims: dict[str, tuple[str, int]] = {}
    for row in rows:
        identity = (row["sha256"], row["sizeBytes"])
        prior = claims.get(row["path"])
        if prior is not None and prior != identity:
            raise BuildClosureRowsError("shared build source conflicts")
        claims[row["path"]] = identity
    return rows


def build_tool_rows(value: BuildReceiptBindingV1) -> tuple[dict, ...]:
    """Return every exact tool row declared by the retained render build."""
    return tuple(
        {
            "label": row.label,
            "path": row.path,
            "sha256": row.sha256,
            "sizeBytes": row.size_bytes,
        }
        for row in value.render_receipt.manifest.tools
    )

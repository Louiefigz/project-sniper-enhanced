"""Independent-role alias rejection for graphic render receipts."""

from __future__ import annotations

from .graphic_render_receipt_binding_types import (
    BoundGraphicRenderReceiptV1,
    CheckedGraphicRenderBindingV1,
    GraphicRenderReceiptBindingError,
)


def reject_aliases(
    value: CheckedGraphicRenderBindingV1,
    bound: tuple[BoundGraphicRenderReceiptV1, ...],
) -> None:
    """Reject same bytes or paths serving independent graphic roles."""
    receipts = tuple(row.artifact for row in bound)
    media = tuple(row.media.artifact for row in bound)
    fields = (
        tuple(ref.relative_path for ref in receipts),
        tuple(ref.sha256 for ref in receipts),
        tuple(ref.relative_path for ref in media),
        tuple(ref.sha256 for ref in media),
    )
    if any(len(rows) != len(set(rows)) for rows in fields):
        raise GraphicRenderReceiptBindingError("graphic render roles alias")
    forbidden = {
        value.runtime.descriptor.plan.artifact.sha256,
        value.runtime.runtime.render_build.artifact.sha256,
    } | set(fields[3])
    if any(ref.sha256 in forbidden for ref in receipts):
        raise GraphicRenderReceiptBindingError(
            "graphic receipt bytes alias another role"
        )

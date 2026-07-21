"""Cross-bind retained graphic receipts to current R0 generation authority."""

from __future__ import annotations

from .graphic_render_receipt_binding_checks import (
    bind_one,
    checked_binding,
    plan_rows,
)
from .graphic_render_receipt_aliases import reject_aliases
from .graphic_render_receipt_admission import bind_graphic_admission_evidence
from .graphic_render_receipt_binding_types import (
    GRAPHIC_RENDER_RECEIPT_STATUS,
    BoundGraphicRenderReceiptV1,
    GraphicRenderReceiptBindingError,
    GraphicRenderReceiptBindingReportV1,
    GraphicRenderReceiptBindingV1,
)

__all__ = (
    "GRAPHIC_RENDER_RECEIPT_STATUS",
    "BoundGraphicRenderReceiptV1",
    "GraphicRenderReceiptBindingError",
    "GraphicRenderReceiptBindingReportV1",
    "GraphicRenderReceiptBindingV1",
    "bind_graphic_render_receipts",
    "require_graphic_render_execution_authorized",
)


def bind_graphic_render_receipts(
    value: object,
) -> GraphicRenderReceiptBindingReportV1:
    """Bind exact declared receipt semantics without attesting execution."""
    checked = checked_binding(value)
    groups, rows = plan_rows(checked)
    bind_graphic_admission_evidence(checked, groups, rows)
    bound = tuple(
        bind_one(checked, row, index, groups) for index, row in enumerate(rows)
    )
    reject_aliases(checked, bound)
    return GraphicRenderReceiptBindingReportV1(
        GRAPHIC_RENDER_RECEIPT_STATUS,
        bound,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
    )


def require_graphic_render_execution_authorized(value: object) -> None:
    """Keep semantic receipt binding outside every execution gate."""
    raise GraphicRenderReceiptBindingError(GRAPHIC_RENDER_RECEIPT_STATUS)

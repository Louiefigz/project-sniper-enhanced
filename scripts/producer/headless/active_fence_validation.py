"""Exact validation for non-authorizing active-fence operation results."""

from __future__ import annotations

from .active_fence_schema import parse_active_fence_document_v1
from .active_fence_types import ActiveFenceOperationResultV1
from .wire_identity import same_wire_value


class ActiveFenceResultValidationError(RuntimeError):
    """An active-fence operation result is malformed or forged."""


def validate_active_fence_operation_result_v1(value: object) -> None:
    """Rebuild exact state and require every authority flag to remain false."""
    if type(value) is not ActiveFenceOperationResultV1:
        raise ActiveFenceResultValidationError(
            "active-fence operation result is invalid"
        )
    try:
        state = parse_active_fence_document_v1(value.state.document_json)
        expected = ActiveFenceOperationResultV1(
            value.operation, state, value.created, value.replayed
        )
    except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
        raise ActiveFenceResultValidationError(
            "active-fence operation result bytes are invalid"
        ) from exc
    flags = (
        type(value.operation) is str
        and value.operation in {"BOOTSTRAP", "RESERVE", "CANCEL"}
        and type(value.created) is bool
        and type(value.replayed) is bool
        and value.created is not value.replayed
    )
    if not flags or not same_wire_value(value, expected):
        raise ActiveFenceResultValidationError(
            "active-fence operation result is invalid"
        )

"""Exact-value validation for durable order-start diagnostics."""

from __future__ import annotations

from .fence_order_start_records import fence_order_start_record_name_v1
from .fence_order_start_schema import validate_fence_order_start_intent_v1
from .fence_order_start_types import (
    FENCE_ORDER_START_STATUS,
    DurableFenceOrderStartV1,
)
from .wire_identity import same_wire_value


class DurableFenceOrderStartValidationError(RuntimeError):
    """A durable start result is malformed or forged."""


def validate_durable_fence_order_start_v1(value: object) -> None:
    """Rebuild every field while preserving false authority flags."""
    if type(value) is not DurableFenceOrderStartV1:
        raise DurableFenceOrderStartValidationError(
            "durable fence order start is invalid"
        )
    try:
        validate_fence_order_start_intent_v1(value.intent)
        expected = DurableFenceOrderStartV1(
            FENCE_ORDER_START_STATUS,
            value.created,
            fence_order_start_record_name_v1(value.intent.attempt_id),
            value.intent,
            True,
            True,
            True,
            True,
            True,
            False,
            False,
        )
    except RuntimeError as exc:
        raise DurableFenceOrderStartValidationError(
            "durable fence order start bytes are invalid"
        ) from exc
    if type(value.created) is not bool or not same_wire_value(value, expected):
        raise DurableFenceOrderStartValidationError(
            "durable fence order start is invalid"
        )

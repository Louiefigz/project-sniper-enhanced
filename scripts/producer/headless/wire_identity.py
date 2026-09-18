"""Exact-type identity comparison for reparsed immutable wire values."""

from __future__ import annotations

from dataclasses import fields, is_dataclass

_LEAF_TYPES = {str, int, float, bool, bytes, type(None)}


def same_wire_value(actual: object, expected: object) -> bool:
    """Compare parsed values without invoking attacker-defined equality."""
    if type(actual) is not type(expected):
        return False
    if is_dataclass(expected):
        return all(
            same_wire_value(getattr(actual, field.name), getattr(expected, field.name))
            for field in fields(expected)
        )
    if type(expected) is tuple:
        return len(actual) == len(expected) and all(
            same_wire_value(left, right) for left, right in zip(actual, expected)
        )
    if type(expected) not in _LEAF_TYPES:
        return False
    return actual == expected

"""Canonical JSON text that matches JavaScript ``JSON.stringify`` numbers."""
from __future__ import annotations

import json
import math
from decimal import Decimal

SAFE_INTEGER_MAX = (1 << 53) - 1


class CrossRuntimeCanonicalJsonError(ValueError):
    """A value cannot retain one exact identity in Python and JavaScript."""


def _string_token(value: str) -> str:
    """Match well-formed JSON.stringify, including lone-surrogate escaping."""
    encoded = json.dumps(value, ensure_ascii=False)
    return "".join(
        f"\\u{ord(char):04x}" if 0xD800 <= ord(char) <= 0xDFFF else char
        for char in encoded
    )


def _float_token(value: float) -> str:
    """Render one finite non-integral float with ECMAScript thresholds."""
    decimal = Decimal(repr(abs(value))).as_tuple()
    digits = "".join(str(digit) for digit in decimal.digits)
    point = len(digits) + decimal.exponent
    sign = "-" if value < 0 else ""
    if point <= -6 or point > 21:
        fraction = f".{digits[1:]}" if len(digits) > 1 else ""
        exponent = point - 1
        exponent_sign = "+" if exponent >= 0 else ""
        return f"{sign}{digits[0]}{fraction}e{exponent_sign}{exponent}"
    if point <= 0:
        return f"{sign}0.{('0' * -point)}{digits}"
    if point >= len(digits):
        return f"{sign}{digits}{('0' * (point - len(digits)))}"
    return f"{sign}{digits[:point]}.{digits[point:]}"


def _number_token(value: int | float) -> str:
    if isinstance(value, int):
        if abs(value) > SAFE_INTEGER_MAX:
            raise CrossRuntimeCanonicalJsonError(
                "integer exceeds JavaScript's exact safe range")
        return str(value)
    if not math.isfinite(value):
        raise CrossRuntimeCanonicalJsonError("number must be finite")
    if value == 0:
        return "0"
    if value.is_integer():
        if abs(value) > SAFE_INTEGER_MAX:
            raise CrossRuntimeCanonicalJsonError(
                "integer-valued float exceeds JavaScript's exact safe range")
        return str(int(value))
    return _float_token(value)


def _key_order(value: str) -> bytes:
    """JavaScript string comparison orders UTF-16 code units."""
    return value.encode("utf-16-be", errors="surrogatepass")


def _canonical_json(
    value: object,
    compact: bool,
    utf16_keys: bool,
) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _number_token(value)
    if isinstance(value, str):
        return _string_token(value)
    if isinstance(value, list):
        separator = "," if compact else ", "
        return f"[{separator.join(
            _canonical_json(item, compact, utf16_keys) for item in value)}]"
    if not isinstance(value, dict) or any(
            not isinstance(key, str) for key in value):
        raise CrossRuntimeCanonicalJsonError(
            "canonical value must use only JSON-domain types")
    separator = "," if compact else ", "
    key_separator = ":" if compact else ": "
    order = _key_order if utf16_keys else None
    entries = (
        f"{_string_token(key)}{key_separator}"
        f"{_canonical_json(value[key], compact, utf16_keys)}"
        for key in sorted(value, key=order)
    )
    return f"{{{separator.join(entries)}}}"


def canonical_json(value: object) -> str:
    """Match the plan serializer's spaced JSON and UTF-16 key order."""
    return _canonical_json(value, compact=False, utf16_keys=True)


def canonical_compact_json(value: object) -> str:
    """Match compact TS canonicalJson with Unicode code-point key order."""
    return _canonical_json(value, compact=True, utf16_keys=False)

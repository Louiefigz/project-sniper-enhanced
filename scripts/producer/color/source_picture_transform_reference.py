"""Independent scalar reference for the fixed display-referred float bridge.

Math follows zimg release-3.0.6 colorspace/gamma.cpp (xvycc_eotf and
rec_1886_inverse_eotf), not a call into FFmpeg/zimg. BT.709 YCbCr coefficients
are Kr=.2126, Kb=.0722; 8-bit limited-range offsets are 16/219 and 128/224.
This reference does not model spatial chroma interpolation or prove any media
was decoded. No tolerance is applied to the initial reject-out-of-gamut policy.

Primary source: https://github.com/sekrit-twc/zimg/blob/release-3.0.6/
src/zimg/colorspace/gamma.cpp
"""
from __future__ import annotations

import math

REFERENCE_POLICY = "zimg-3.0.6-display-xvycc709-scalar-v1"
_ALPHA = 1.09929682680944
_BETA = 0.018053968510807
_KR, _KB = 0.2126, 0.0722


def finite_sample(value: object) -> float:
    """Reject booleans, non-finite values and overflowing numeric conversions."""
    if type(value) not in (int, float):
        raise ValueError("picture sample must be finite numeric data")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError("picture sample conversion overflowed") from exc
    if not math.isfinite(result):
        raise ValueError("picture sample must be finite numeric data")
    return result


def xvycc709_to_linear(value: object) -> float:
    """Preserve signed extended values; legal values use display gamma 2.4."""
    encoded = finite_sample(value)
    if 0 <= encoded <= 1:
        return math.copysign(abs(encoded) ** 2.4, encoded)
    magnitude = abs(encoded)
    try:
        linear = magnitude / 4.5 if magnitude < 4.5 * _BETA else (
            (magnitude + _ALPHA - 1) / _ALPHA) ** (1 / 0.45)
    except OverflowError as exc:
        raise ValueError("picture transfer overflowed") from exc
    return finite_sample(math.copysign(linear, encoded))


def require_unit_gamut(samples: tuple[float, ...]) -> tuple[float, ...]:
    """Check one RGB triplet, not a media frame/coverage or approval receipt."""
    if type(samples) is not tuple or len(samples) != 3:
        raise ValueError("picture gamut check requires exactly three channels")
    result = tuple(finite_sample(value) for value in samples)
    if any(value < 0 or value > 1 for value in result):
        raise ValueError("picture linear RGB is outside the closed BT.709 gamut")
    return result


def linear_to_bt709(value: object) -> float:
    """Encode only legal linear samples; never silently clamp negative light."""
    linear = finite_sample(value)
    if not 0 <= linear <= 1:
        raise ValueError("picture linear sample is outside BT.709 gamut")
    return linear ** (1 / 2.4)


def limited_ycbcr_to_rgb(values: tuple[float, float, float]) -> tuple[float, ...]:
    """Decode one 8-bit code triplet without pre-clamping extended code values."""
    if type(values) is not tuple or len(values) != 3:
        raise ValueError("picture YCbCr reference requires three code values")
    y, cb, cr = (finite_sample(value) for value in values)
    if any(value < 0 or value > 255 for value in (y, cb, cr)):
        raise ValueError("picture YCbCr reference requires 8-bit code values")
    y, cb, cr = (y - 16) / 219, (cb - 128) / 224, (cr - 128) / 224
    red, blue = y + 2 * (1 - _KR) * cr, y + 2 * (1 - _KB) * cb
    green = (y - _KR * red - _KB * blue) / (1 - _KR - _KB)
    return red, green, blue


def limited_ycbcr_to_linear(values: tuple[float, float, float]) -> tuple[float, ...]:
    """Independent pointwise source-to-float reference, including extended RGB."""
    return tuple(xvycc709_to_linear(value) for value in limited_ycbcr_to_rgb(values))


def reference_bt709_rgb(values: tuple[float, float, float]) -> tuple[float, ...]:
    """Produce legal display RGB only after exact pointwise gamut rejection."""
    linear = require_unit_gamut(limited_ycbcr_to_linear(values))
    return tuple(linear_to_bt709(value) for value in linear)

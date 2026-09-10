"""Exact rational FPS normalization for HyperFrames and media proof."""
from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Mapping

_COMMON_RATES = tuple(Fraction(top, bottom) for top, bottom in (
    (24_000, 1_001), (24, 1), (25, 1), (30_000, 1_001), (30, 1),
    (50, 1), (60_000, 1_001), (60, 1),
))


@dataclass(frozen=True)
class RenderRate:
    """Canonical CLI token and numeric value for one exact rate."""

    numerator: int
    denominator: int

    @property
    def token(self) -> str:
        return (str(self.numerator) if self.denominator == 1 else
                f"{self.numerator}/{self.denominator}")

    @property
    def numeric(self) -> float:
        return self.numerator / self.denominator


def _terms(value: object) -> tuple[int, int] | None:
    if isinstance(value, Mapping) and set(value) == {
            "numerator", "denominator"}:
        raw = value["numerator"], value["denominator"]
        if all(isinstance(item, str) and item.isdigit()
               and not item.startswith("0") for item in raw):
            return int(raw[0]), int(raw[1])
        return None
    if isinstance(value, Fraction):
        return value.numerator, value.denominator
    if isinstance(value, str):
        parts = value.split("/")
        if len(parts) not in {1, 2} or not all(
                part.isdigit() and not part.startswith("0") for part in parts):
            return None
        return int(parts[0]), int(parts[1] if len(parts) == 2 else 1)
    if type(value) is int:
        return value, 1
    return None


def _from_float(value: float) -> tuple[int, int] | None:
    if not math.isfinite(value) or value <= 0:
        return None
    if value.is_integer():
        return int(value), 1
    match = next((rate for rate in _COMMON_RATES
                  if abs(float(rate) - value) <= 1e-9), None)
    return None if match is None else (match.numerator, match.denominator)


def normalize_render_rate(value: object) -> RenderRate:
    """Return a reduced positive rate; ambiguous decimal floats fail closed."""
    terms = _from_float(value) if type(value) is float else _terms(value)
    if terms is None:
        raise ValueError(
            "render FPS must be an exact positive rational, not a decimal")
    numerator, denominator = terms
    if numerator <= 0 or denominator <= 0:
        raise ValueError("render FPS must be positive")
    fraction = Fraction(numerator, denominator)
    if (fraction.numerator, fraction.denominator) != terms:
        raise ValueError("render FPS rational must be reduced")
    return RenderRate(fraction.numerator, fraction.denominator)

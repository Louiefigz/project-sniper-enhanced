"""Closed phrase directive parser for the cross-runtime repair route."""
from __future__ import annotations

from edit.target_resolver import PhraseTarget

_FIELDS = {
    "phrase", "sourceId", "occurrence", "speaker", "beforeContext",
    "afterContext", "approximateSourceSample", "toleranceSamples",
}
_STRINGS = ("sourceId", "speaker", "beforeContext", "afterContext")


class TargetDirectiveError(ValueError):
    """A phrase directive contains unbounded or ambiguous request data."""


def _optional_string(row: dict, key: str) -> str | None:
    value = row.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise TargetDirectiveError(
            f"directive target {key} must be 1..160 characters")
    return value.strip()


def _optional_integer(row: dict, key: str,
                      minimum: int) -> int | None:
    value = row.get(key)
    if value is None:
        return None
    if type(value) is not int or value < minimum:
        raise TargetDirectiveError(
            f"directive target {key} must be an integer >= {minimum}")
    return value


def parse_phrase_target(value: object) -> PhraseTarget:
    """Parse the exact structured target accepted by the TypeScript route."""
    if not isinstance(value, dict) or set(value) - _FIELDS \
            or "phrase" not in value:
        raise TargetDirectiveError(
            "directive target has unknown or missing fields")
    phrase = value["phrase"]
    if not isinstance(phrase, str) or not phrase.strip() \
            or len(phrase) > 160:
        raise TargetDirectiveError(
            "directive phrase must be 1..160 characters")
    strings = {key: _optional_string(value, key) for key in _STRINGS}
    occurrence = _optional_integer(value, "occurrence", 1)
    approximate = _optional_integer(
        value, "approximateSourceSample", 0)
    tolerance = _optional_integer(value, "toleranceSamples", 0)
    if (approximate is None) != (tolerance is None):
        raise TargetDirectiveError(
            "approximateSourceSample and toleranceSamples must be paired")
    return PhraseTarget(
        phrase.strip(), strings["sourceId"], occurrence, strings["speaker"],
        strings["beforeContext"], strings["afterContext"],
        approximate, tolerance)

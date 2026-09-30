"""The field conventions of P3a §4.0, stated once for every coordination validator (MASTER-PLAN M-081).

``id`` is ``section_results.IDENTIFIER``; ``hex64`` a lowercase SHA-256; ``pin`` a closed exact-byte reference
(``section_results.validate_pin``); ``range`` a half-open integer frame range ``[a, b]`` with ``0 <= a < b <=
totalFrames``; ``text(n)`` one non-empty line without NUL whose canonical encoding fits ``n`` bytes
(``host_contract.encoded_length``). Every refusal is ``ValueError('Coordination plan: <rule>: <detail>')``; a pin
refused by ``section_results`` is re-raised in that form. Nothing here reads a file.
"""
from __future__ import annotations

from typing import NoReturn

from cut_preview_io import digest
from studio.production.host_contract import encoded_length
from studio.production.section_results import IDENTIFIER, SHA256, matches, validate_pin, validate_pins

PREFIX = 'Coordination plan'


def refuse(rule: str, detail: str) -> NoReturn:
    """Raise the area's one refusal form."""
    raise ValueError(f'{PREFIX}: {rule}: {detail}')


def check(condition: bool, rule: str, detail: str) -> None:
    """Refuse unless the condition holds."""
    if not condition:
        refuse(rule, detail)


def closed(value: object, keys: tuple[str, ...], rule: str) -> dict:
    """An object with exactly these keys."""
    check(type(value) is dict and set(value) == set(keys), rule, f'fields must be exactly {sorted(keys)}')
    return value


def rows(value: object, rule: str, bounds: tuple[int, int]) -> list:
    """A list whose length lies in ``bounds`` (inclusive)."""
    low, high = bounds
    check(type(value) is list and low <= len(value) <= high, rule, f'must list {low}..{high} rows')
    return value


def identifier(value: object, rule: str) -> str:
    """An ``id``."""
    check(matches(value, IDENTIFIER), rule, f'{value!r} is not an id')
    return value


def identifiers(value: object, rule: str, bounds: tuple[int, int]) -> list[str]:
    """A bounded list of distinct ids."""
    found = rows(value, rule, bounds)
    for item in found:
        identifier(item, rule)
    check(len(set(found)) == len(found), rule, 'ids repeat')
    return found


def hex64(value: object, rule: str) -> str:
    """A lowercase SHA-256 hex digest."""
    check(matches(value, SHA256), rule, f'{value!r} is not a SHA-256 digest')
    return value


def count(value: object, limit: int, rule: str) -> int:
    """An integer in ``0..limit`` (a bool is not an integer here)."""
    check(type(value) is int and 0 <= value <= limit, rule, f'{value!r} is not an integer in 0..{limit}')
    return value


def text(value: object, limit: int, rule: str) -> str:
    """``text(n)``: one non-empty line, no NUL, canonical encoding at most ``limit`` bytes."""
    check(type(value) is str and value.strip() != '' and not {'\x00', '\n', '\r'} & set(value)
          and encoded_length(value) <= limit, rule, f'must be one non-empty line of at most {limit} bytes')
    return value


def maybe_text(value: object, limit: int, rule: str) -> str | None:
    """None, or ``text(limit)``."""
    return None if value is None else text(value, limit, rule)


def frame_range(value: object, clock: dict, rule: str) -> list:
    """A half-open integer frame range ``[a, b]`` with ``0 <= a < b <= totalFrames``."""
    total = clock['totalFrames']
    check(type(value) is list and len(value) == 2 and all(type(item) is int for item in value)
          and 0 <= value[0] < value[1] <= total, rule, f'range {value!r} is not [a, b] with 0 <= a < b <= {total}')
    return value


def maybe_range(value: object, clock: dict, rule: str) -> list | None:
    """None (the whole output) or a frame range."""
    return None if value is None else frame_range(value, clock, rule)


def contiguous(ranges: list[list], clock: dict, rule: str) -> None:
    """Ranges in list order tile ``[0, totalFrames)`` with no gap or overlap."""
    edge = 0
    for start, end in ranges:
        check(start == edge, rule, f'rows are not contiguous at frame {edge}')
        edge = end
    check(edge == clock['totalFrames'], rule, f'rows end at {edge}, not {clock["totalFrames"]}')


def pin(value: object, rule: str) -> dict:
    """A closed exact-byte reference (``section_results.validate_pin``), refused in this area's form."""
    try:
        return validate_pin(value)
    except ValueError as error:
        refuse(rule, str(error))


def maybe_pin(value: object, rule: str) -> dict | None:
    """None, or a pin."""
    return None if value is None else pin(value, rule)


def pins(value: object, rule: str) -> list[dict]:
    """At most 64 pins with distinct paths (``section_results.validate_pins``)."""
    try:
        return validate_pins(value)
    except ValueError as error:
        refuse(rule, str(error))


def authored_digest(entry: dict) -> str:
    """The code-computed ``digest`` of an authored entry: the canonical digest of its other fields."""
    return digest({key: value for key, value in entry.items() if key != 'digest'})

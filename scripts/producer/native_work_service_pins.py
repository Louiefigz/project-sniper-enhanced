"""Closed data and current immutable evidence pins for measured service rates."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

from cut_preview_io import file_hash, read_bytes, real_directory
from studio.native_stage_evidence import MAX_NATIVE_FILE_BYTES

MAX_DOCUMENT_BYTES = 4 * 1024 * 1024


class ServiceRateError(ValueError):
    """A rate is unavailable because its evidence is incomplete or changed."""


def require(condition: bool, message: str) -> None:
    """Refuse invalid evidence without granting any production authority."""
    if not condition:
        raise ServiceRateError(message)


def fields(value: object, names: str) -> dict:
    """Require one exact JSON object shape."""
    require(type(value) is dict and set(value) == set(names.split()), f'Expected exact fields: {names}')
    return value


def number(value: object, positive: bool = False) -> bool:
    """Accept finite real numbers, excluding bool and negative values."""
    return type(value) in (int, float) and math.isfinite(value) and (value > 0 if positive else value >= 0)


def text(value: object, maximum: int = 256) -> bool:
    """Require bounded nonblank single-line strings."""
    return type(value) is str and 0 < len(value.strip()) <= maximum and '\n' not in value


def identity(value: object) -> str:
    """Hash canonical JSON rather than a path or mutable label."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def digest(value: object) -> bool:
    """Recognize exact lowercase SHA256 hex digests."""
    return type(value) is str and len(value) == 64 and all(char in '0123456789abcdef' for char in value)


def pin(value: object) -> Path:
    """Check a canonical regular file and its current bytes, including media pins."""
    file = pin_path(value)
    require(file_hash(file, maximum=value['bytes']) == value['sha256'], 'Evidence pin bytes changed')
    return file


def pin_path(value: object) -> Path:
    """Validate bounded pin metadata before any media or JSON read."""
    row = fields(value, 'path bytes sha256')
    require(type(row['path']) is str and os.path.isabs(row['path']), 'Evidence pin path must be absolute')
    file = Path(row['path'])
    real_directory(file.parent)
    require(str(file.resolve(strict=True)) == row['path'] and not file.is_symlink() and file.is_file(),
            'Evidence pin path must be canonical and regular')
    require(type(row['bytes']) is int and 0 < row['bytes'] <= MAX_NATIVE_FILE_BYTES and digest(row['sha256']),
            'Evidence pin size/digest invalid')
    require(file.stat().st_size == row['bytes'], 'Evidence pin size changed')
    return file


def document(value: object) -> dict:
    """Read a bounded current JSON pin with duplicate keys and nonfinite numbers refused."""
    fields(value, 'path bytes sha256')
    require(type(value['bytes']) is int and 0 < value['bytes'] <= MAX_DOCUMENT_BYTES, 'Evidence JSON exceeds size bound')
    file = pin_path(value)
    data = read_bytes(file, maximum=MAX_DOCUMENT_BYTES)
    require(len(data) == value['bytes'] and hashlib.sha256(data).hexdigest() == value['sha256'],
            'Evidence changed during JSON read')
    return parse(data)


def parse(data: bytes) -> dict:
    """Decode a bounded JSON object without ambiguous duplicated fields."""
    require(len(data) <= MAX_DOCUMENT_BYTES, 'Service rate JSON exceeds size bound')
    value = json.loads(data, object_pairs_hook=unique_pairs,
                       parse_constant=lambda value: require(False, f'Nonfinite JSON: {value}'))
    require(type(value) is dict, 'Service rate JSON must be an object')
    return value


def unique_pairs(pairs: list) -> dict:
    """Reject duplicate object keys before normal dictionary construction."""
    result = {}
    for key, value in pairs:
        require(key not in result, f'Duplicate JSON field: {key}')
        result[key] = value
    return result

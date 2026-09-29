"""Rate-only evidence beside existing host qualification; never a capacity source."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass

from headless.durable_files import DurableFileError, open_private_dir, private_child_dir, read_private_file
from headless.durable_files import write_pending_replace
from native_work_qualification import record_directory
from native_work_service_pins import MAX_DOCUMENT_BYTES, parse, require

RECORD_NAME = 'long-review-package-service-v1.json'


@dataclass(frozen=True)
class RateCatalog:
    """Validated service rows and provenance; an empty catalog requires fallback."""

    rows: tuple = ()
    source: dict | None = None
    rejected: str | None = None


def read_service_rates(host: dict) -> RateCatalog:
    """Read only the canonical private sidecar, never inheriting rates in test namespaces."""
    directory = record_directory()
    if directory is None:
        return RateCatalog(rejected='Non-canonical namespace has no host service rates')
    if not os.path.lexists(directory / RECORD_NAME):
        return RateCatalog(rejected='No measured Long review-package service rates')
    try:
        descriptor = open_private_dir(str(directory))
        try:
            data = read_private_file(descriptor, RECORD_NAME, MAX_DOCUMENT_BYTES)
        finally:
            os.close(descriptor)
        from native_work_service_schema import validate_document
        rows = validate_document(parse(data), host)
        source = {'path': str(directory / RECORD_NAME), 'bytes': len(data),
                  'sha256': hashlib.sha256(data).hexdigest()}
        return RateCatalog(tuple(rows), source)
    except (DurableFileError, OSError, ValueError, KeyError, TypeError, ArithmeticError, RuntimeError) as error:
        return RateCatalog(rejected=f'{type(error).__name__}: {error}')


def write_service_rates(document: dict, host: dict) -> dict:
    """Publish explicitly adopted evidence atomically; no capacity or policy writes."""
    from native_work_service_schema import validate_document
    validate_document(document, host)
    directory = record_directory()
    require(directory is not None, 'Rate writes require the canonical host namespace')
    data = (json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
    require(len(data) <= MAX_DOCUMENT_BYTES, 'Service rate record exceeds size bound')
    directory.parent.mkdir(mode=0o700, exist_ok=True)
    parent = open_private_dir(str(directory.parent))
    try:
        child = private_child_dir(parent, directory.name)
    finally:
        os.close(parent)
    try:
        write_pending_replace(child, (RECORD_NAME + '.pending', RECORD_NAME), data)
    finally:
        os.close(child)
    return {'path': str(directory / RECORD_NAME), 'bytes': len(data),
            'sha256': hashlib.sha256(data).hexdigest()}

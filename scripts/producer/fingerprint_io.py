"""Durable file and sidecar primitives shared by fingerprint consumers."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable


def file_sha256(path: str) -> str:
    """Streaming SHA-256 of a completed file without loading it into memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def stage_receipt_path(output_path: str) -> str:
    """Sidecar proving which inputs produced a resumable stage output."""
    return output_path + ".stage.json"


def stage_receipt_current(output_path: str, fingerprint: str) -> bool:
    """Whether an existing stage output is backed by the expected receipt."""
    if not os.path.exists(output_path):
        return False
    try:
        with open(stage_receipt_path(output_path), encoding="utf-8") as handle:
            return json.load(handle).get("fingerprint") == fingerprint
    except (OSError, json.JSONDecodeError, AttributeError):
        return False


def write_json_atomic(
    path: str,
    payload: object,
    indent: int | None = None,
) -> None:
    """Durably replace one JSON document after flushing its staged bytes."""
    directory = os.path.dirname(os.path.abspath(path))
    descriptor, staged = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=indent)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, path)
    finally:
        if os.path.exists(staged):
            os.remove(staged)


def write_stage_receipt(output_path: str, fingerprint: str) -> None:
    """Atomically bind one completed intermediate to its stage fingerprint."""
    write_json_atomic(
        stage_receipt_path(output_path), {"fingerprint": fingerprint})


def assembled_sidecar_path(final_path: str) -> str:
    """Return the provenance sidecar path for ``final_path``."""
    return final_path + ".assembled.json"


def invalidate_assembled_sidecar(final_path: str) -> None:
    """Remove prior provenance before any operation mutates the final MP4."""
    try:
        os.remove(assembled_sidecar_path(final_path))
    except FileNotFoundError:
        pass


def read_recorded_fingerprints(
    fingerprint_path: str,
    record_builder: Callable[[dict], dict],
) -> dict:
    """Read stored fingerprints and refresh them from a retained plan."""
    with open(fingerprint_path) as handle:
        record = json.load(handle)
    snapshot = os.path.join(
        os.path.dirname(fingerprint_path), "base_plan.json")
    if os.path.exists(snapshot):
        with open(snapshot) as handle:
            derived = record_builder(json.load(handle))
        # A retained plan proves content intent, not which DSP executed. Never
        # invent or upgrade the processing policy of previously rendered bytes.
        derived.pop("masteringPolicyVersion", None)
        derived.pop("audioClockPolicy", None)
        record.update(derived)
    return record

"""Retain the actual sealed master publication; no file reads or color approval.

The ordinary audio publisher remains the only writer. These private same-run
joins keep its actual payload, returned receipt and returned master result
through the original callbacks, rather than adopting current receipt bytes.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
from weakref import WeakKeyDictionary

from edit.picture_lock_common import content_hash
from guided_presenter_read_fingerprint import hold_read_metadata, same_read_metadata
from guided_source_color_consumption_records import metadata_size, path, same

_PUBLICATIONS = WeakKeyDictionary()


@dataclass
class _Publication:
    """Private initial semantics and the actual original publisher return objects."""

    receipt_path: str
    payload: dict
    original: object
    fixed: dict
    receipt: dict | None = None
    receipt_hold: object = None
    completed: dict | None = None
    completed_hold: object = None


def _recorder(value: object) -> object:
    """Lazy dispatch avoids an import cycle while requiring the actual private capability."""
    from guided_source_color_consumption import SourceColorPictureConsumption, _state
    SourceColorPictureConsumption.assert_metadata(value)
    return _state(value)


def prepare_publication(recorder: object, values: tuple) -> None:
    """Capture the complete payload before seal, using the original top-level master output."""
    from guided_source_color_consumption import MAX_CONSUMPTION_BYTES
    state = _recorder(recorder)
    receipt_path, payload, request = values
    if recorder in _PUBLICATIONS or state.proof is None:
        raise RuntimeError("source-color master publication is incomplete or replayed")
    if type(payload) is not dict or payload.get("schemaVersion") != 2 or type(payload["schemaVersion"]) is not int \
            or payload.get("kind") != "ordinary-source-float-master" or payload.get("approved") is not False \
            or payload.get("audioClockPolicy") != "source-float-v2" \
            or payload.get("path") != path(request["outputPath"]) \
            or request["inputPath"] != state.joined["concatPath"] \
            or not same(payload.get("picture"), state.proof) \
            or type(payload.get("sha256")) is not str or not re.fullmatch(r"[0-9a-f]{64}", payload["sha256"]):
        raise RuntimeError("source-color master publication differs from the actual final output/proof")
    size = metadata_size({"receiptPath": receipt_path, "receipt": {
        **payload, "receiptHash": content_hash(payload)}}, MAX_CONSUMPTION_BYTES - state.retained_bytes)
    fixed = deepcopy(payload)
    _PUBLICATIONS[recorder] = _Publication(path(receipt_path), payload, hold_read_metadata(payload), fixed)
    state.retained_bytes += size


def assert_publication(recorder: object, complete: bool = False) -> None:
    """Callback-free comparison retains raw semantic objects, not a fresh baseline."""
    _recorder(recorder)
    value = _PUBLICATIONS.get(recorder)
    if value is None:
        if complete:
            raise RuntimeError("source-color master publication is incomplete")
        return
    if not same_read_metadata(value.payload, value.original) \
            or (value.receipt is not None and not same_read_metadata(value.receipt, value.receipt_hold)) \
            or (value.completed is not None and not same_read_metadata(value.completed, value.completed_hold)):
        raise RuntimeError("source-color original master publication changed")
    if complete and (value.receipt is None or value.completed is None):
        raise RuntimeError("source-color master publication is incomplete")


def retain_publication(recorder: object, receipt: dict) -> None:
    """Capture the actual seal return immediately, before any finalizer or callback."""
    assert_publication(recorder)
    value = _PUBLICATIONS[recorder]
    expected = {**value.fixed, "receiptHash": content_hash(value.fixed)}
    if value.receipt is not None or not same(receipt, expected):
        raise RuntimeError("source-color sealed master receipt changed or replayed")
    value.receipt, value.receipt_hold = receipt, hold_read_metadata(receipt)


def complete_publication(recorder: object, completed: dict) -> None:
    """Hold the exact actual master return before its final original owner guard."""
    assert_publication(recorder)
    value = _PUBLICATIONS[recorder]
    if value.receipt is None or value.completed is not None or type(completed) is not dict \
            or completed.get("out") != value.fixed["path"] \
            or completed.get("source_audio_receipt") != value.receipt_path \
            or completed.get("source_audio_receipt_hash") != value.receipt["receiptHash"]:
        raise RuntimeError("source-color final master result omitted or changed its sealed receipt")
    value.completed, value.completed_hold = completed, hold_read_metadata(completed)


def publication_record(recorder: object) -> dict:
    """Return detached JSON semantics only after the complete actual publication path."""
    _recorder(recorder)
    recorder.assert_current()
    assert_publication(recorder, True)
    value = _PUBLICATIONS[recorder]
    result = deepcopy({"receiptPath": value.receipt_path, "receipt": value.receipt})
    assert_publication(recorder, True)
    return result

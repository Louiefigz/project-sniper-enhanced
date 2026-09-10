"""Finite cold generated-picture lifetime, not source or execution authority.

The caller authenticates input/evidence/observation provenance, the executed
pipeline and tool bytes, and owns the SAME protected read phase. This helper
captures all finite generated files before the first caller callback. It never
opens original sources or creates a clock, renderer, lease or execution owner.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
from weakref import WeakKeyDictionary

from color.deadline import require_time
from audio.audio_mix_picture import PictureSource
from cut_preview_io import file_hash, read_bytes
from guided_opening_inputs import OpeningInputs, closed, hash_value
from guided_presenter_read_fingerprint import hold_read_metadata, same_read_metadata
from guided_source_color_observation_files import _File, _identity, check_observation_file
from guided_source_color_consumption_records import picture_fields
from guided_source_color_staging_contract import _path
from guided_source_color_staging_files import _pairs
from headless.grade_launch_files import directory_identity

_ORIGINAL_READS = WeakKeyDictionary()


@dataclass(frozen=True)
class SourceColorConsumptionReadContext:
    """Borrow actual original inputs, authenticated bindings and one caller cutoff."""

    inputs: OpeningInputs
    bindings: dict
    deadline: float
    guard: Callable[[], None]


def _context(value: SourceColorConsumptionReadContext) -> tuple:
    """Keep complete typed input/capture and callback identity before any helper IO."""
    if type(value) is not SourceColorConsumptionReadContext or type(value.inputs) is not OpeningInputs \
            or type(value.bindings) is not dict or not callable(value.guard) \
            or type(value.deadline) not in (int, float) or not math.isfinite(value.deadline):
        raise RuntimeError("cold picture consumption requires original inputs and caller deadline")
    inputs = value.inputs
    if type(inputs.path) is not type(Path()):
        raise RuntimeError("cold consumption original input path type changed")
    return (id(value), id(inputs), id(value.bindings), value.bindings, value.deadline, id(value.guard),
            str(inputs.path), inputs.sha256, id(inputs.value), inputs.value,
            id(inputs.documents), inputs.documents, id(inputs.verified_media), inputs.verified_media)


def _controls(value: ConsumptionReadFiles) -> tuple:
    """Capture handle surface and reference identities without mutable reader progress."""
    return (tuple(vars(value)), id(value.context), id(value.evidence), id(value.files),
            id(value.loaded), id(value.native), value.deadline, id(value.callback),
            value.path_environment, id(value.tool), value.tool)


def _file_fields(value: _File) -> tuple:
    """Detach original file identity/ancestry without exposing the private snapshot."""
    if type(value) is not _File or type(value.path) is not type(Path()):
        raise RuntimeError("cold picture consumption original file metadata changed")
    return (id(value), str(value.path), value.identity, value.parents, value.maximum)


def _original(value: ConsumptionReadFiles) -> dict:
    """Require the original constructor return and immutable complete handle surface."""
    if type(value) is not ConsumptionReadFiles or value not in _ORIGINAL_READS:
        raise RuntimeError("cold picture consumption requires its original retained read")
    state = _ORIGINAL_READS[value]
    if not same_read_metadata(_controls(value), state["controls"]) \
            or value.armed is not state["armed"] or value.busy is not state["busy"] \
            or value.record is not state["record"]:
        raise RuntimeError("cold picture consumption original retained handle metadata changed")
    return state


def _inventories(value: ConsumptionReadFiles, state: dict) -> None:
    """Check visible inventories against private originals before any file or native result use."""
    if tuple(value.files) != tuple(state["files"]) \
            or tuple(id(row) for row in value.loaded) != tuple(row[0] for row in state["loaded"]) \
            or tuple(id(row) for row in value.native) != tuple(row[0] for row in state["native"]):
        raise RuntimeError("cold picture consumption original retained inventories changed")
    for key, (row, fixed) in state["files"].items():
        if value.files[key] is not row or not same_read_metadata(_file_fields(row), fixed):
            raise RuntimeError("cold picture consumption original file metadata changed")
    if any(not same_read_metadata(row, fixed) for _, row, fixed in state["loaded"]) \
            or any(not same_read_metadata(picture_fields(row), fixed) for _, row, fixed in state["native"]):
        raise RuntimeError("cold picture consumption original metadata changed")


class ConsumptionReadFiles:
    """Private metadata lifetime retaining actual parser/native returns, not authority."""

    def __init__(self, evidence: dict, context: SourceColorConsumptionReadContext) -> None:
        """Capture original arguments before reading or invoking caller callbacks."""
        original = hold_read_metadata((_context(context), id(evidence), evidence))
        self.evidence, self.context = evidence, context
        self.deadline, self.callback = context.deadline, context.guard
        self.files: dict[str, _File] = {}
        self.loaded: list[tuple[object, object]] = []
        self.native: list[tuple[PictureSource, object]] = []
        self.record: dict | None = None
        self.armed, self.busy = False, False
        self.path_environment = os.environ.get("PATH")
        self.tool = context.bindings["tools"]["ffprobe"]
        closed(self.tool, {"path", "sha256"}, "cold picture ffprobe")
        _path(self.tool["path"])
        hash_value(self.tool["sha256"])
        _ORIGINAL_READS[self] = {"original": original, "controls": hold_read_metadata(_controls(self)),
            "files": {}, "loaded": [], "native": [], "record": None, "armed": False, "busy": False}
        ConsumptionReadFiles.unchanged(self)
        require_time(self.deadline)

    def retain(self, value: object) -> object:
        """Hold actual returned objects immediately; caller-visible record stays detached."""
        ConsumptionReadFiles.unchanged(self)
        state = _original(self)
        if state["record"] is not None or state["busy"]:
            raise RuntimeError("cold picture consumption cannot retain late parser metadata")
        view = (value, None)
        state["loaded"].append((id(view), value, hold_read_metadata(value)))
        self.loaded.append(view)
        return value

    def retain_picture(self, value: PictureSource) -> None:
        """Retain the actual packet observation object with exact rational fields, not JSON."""
        ConsumptionReadFiles.unchanged(self)
        state = _original(self)
        if type(value) is not PictureSource or state["record"] is not None or state["busy"]:
            raise RuntimeError("cold picture copy requires the actual packet observer return")
        view = (value, None)
        state["native"].append((id(view), value, hold_read_metadata(picture_fields(value))))
        self.native.append(view)

    def finish(self, record: dict) -> None:
        """Retain one detached complete record and its original returned object identity."""
        ConsumptionReadFiles.retain(self, record)
        _original(self)["record"] = record
        self.record = record

    def capture(self, path: Path, maximum: int) -> None:
        """Capture initial same-pass identity before reads; never add files after callbacks."""
        ConsumptionReadFiles.unchanged(self)
        state = _original(self)
        if state["armed"] or str(_path(str(path))) != str(path):
            raise RuntimeError("cold picture consumption cannot rebaseline late file roles")
        require_time(self.deadline)
        row = _File(path, _identity(path), directory_identity(path.parent), maximum)
        if not 0 < row.identity[6] <= maximum:
            raise RuntimeError("cold picture consumption artifact exceeds its finite bound")
        previous = self.files.get(str(path))
        if previous is not None and previous != row:
            raise RuntimeError("cold picture consumption conflicting original file roles")
        self.files[str(path)] = row
        state["files"][str(path)] = (row, hold_read_metadata(_file_fields(row)))
        check_observation_file(row)
        ConsumptionReadFiles.unchanged(self)
        require_time(self.deadline)

    def raw(self, ref: dict) -> bytes:
        """Read bounded metadata, retaining original file stats across the sole raw pass."""
        ConsumptionReadFiles.unchanged(self)
        row = _original(self)["files"][ref["path"]][0]
        raw = read_bytes(row.path, row.maximum)
        ConsumptionReadFiles.metadata(self)
        if hashlib.sha256(raw).hexdigest() != hash_value(ref["sha256"]) \
                or ("sizeBytes" in ref and (type(ref["sizeBytes"]) is not int or len(raw) != ref["sizeBytes"])):
            raise RuntimeError("cold picture consumption original raw reference changed")
        return raw

    def load(self, ref: dict) -> dict:
        """Read duplicate-free JSON data, never reconstructing an execution owner."""
        value = json.loads(ConsumptionReadFiles.raw(self, ref).decode("utf8", errors="strict"), object_pairs_hook=_pairs)
        if type(value) is not dict:
            raise RuntimeError("cold picture consumption metadata must be a JSON object")
        ConsumptionReadFiles.retain(self, value)
        ConsumptionReadFiles.metadata(self)
        return value

    def verify_hash(self, ref: dict) -> None:
        """Hash only named generated video artifacts; original sources are never opened."""
        ConsumptionReadFiles.unchanged(self)
        if file_hash(Path(ref["path"])) != hash_value(ref["sha256"]):
            raise RuntimeError("cold picture consumption generated artifact bytes changed")
        row = _original(self)["files"][ref["path"]][0]
        if "sizeBytes" in ref and (type(ref["sizeBytes"]) is not int or ref["sizeBytes"] != row.identity[6]):
            raise RuntimeError("cold picture consumption generated artifact size changed")
        ConsumptionReadFiles.metadata(self)

    def unchanged(self) -> None:
        """Compare originals and all actual parser/observation returns without callbacks."""
        state = _original(self)
        if not same_read_metadata((_context(self.context), id(self.evidence), self.evidence), state["original"]):
            raise RuntimeError("cold picture consumption original metadata changed")
        _inventories(self, state)

    def metadata(self) -> None:
        """Final finite byte/tool/path identity sweep closes on the original cutoff."""
        ConsumptionReadFiles.unchanged(self)
        require_time(self.deadline)
        for row, _ in _original(self)["files"].values():
            check_observation_file(row)
        selected = shutil.which("ffprobe")
        if os.environ.get("PATH") != self.path_environment or selected is None \
                or str(Path(selected).resolve(strict=True)) != self.tool["path"]:
            raise RuntimeError("cold picture consumption PATH no longer resolves original ffprobe")
        ConsumptionReadFiles.unchanged(self)
        require_time(self.deadline)

    def check(self) -> None:
        """Reuse original source/tool guard; no repeated decode or source-byte hashing here."""
        ConsumptionReadFiles.unchanged(self)
        state = _original(self)
        if state["busy"]:
            raise RuntimeError("cold picture consumption callback reentered its lifetime")
        self.armed, self.busy = True, True
        state["armed"], state["busy"] = True, True
        try:
            ConsumptionReadFiles.metadata(self)
            self.callback()
            ConsumptionReadFiles.metadata(self)
        finally:
            self.busy = False
            state["busy"] = False

    def assert_metadata(self) -> None:
        """Close final outer callbacks without new callbacks, native reads or clock renewal."""
        ConsumptionReadFiles.metadata(self)

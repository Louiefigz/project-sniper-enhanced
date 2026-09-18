"""Private original body-control capture before original source admission.

This seed borrows the already wall-bound body clock. It retains exactly one
actual source-input read and six original opening controls; it grants neither
native execution nor old opening runtime/resource authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import stat
from weakref import WeakKeyDictionary

from guided_body_contract import parse_current_body_input
from guided_body_execution import (BodyExecutionClock, BodyHeldFile, assert_body_files,
    _identity as file_identity, _parent_paths, _directory_states)
from guided_body_inputs import BodyControl
from guided_opening_claim import HeldOpeningClaim
from guided_opening_inputs import OpeningInputs, _json
from guided_opening_read import ReadAuthority
from guided_presenter_read_fingerprint import hold_read_metadata, same_read_metadata
from guided_source_color_read_clock import source_color_read_clock_fields, source_color_read_remaining
from guided_source_color_read_entry import capture_source_color_read_entry, assert_source_color_read_entry
from guided_source_color_read_transport import SourceColorReadTransport

_SEEDS = WeakKeyDictionary()
_CONTROLS = WeakKeyDictionary()


@dataclass(frozen=True, eq=False)
class _BodyControlOrigin:
    """Private raw control join; its empty public shape grants no copied authority."""


@dataclass(frozen=True, eq=False)
class BodySourceColorEntry:
    """Opaque original seed; copying the field does not copy private registration."""

    entry: object


@dataclass(frozen=True)
class BodyInputRead:
    """Original inputs plus their actual optional body replay seed, not a new owner."""

    inputs: OpeningInputs
    source_color_entry: BodySourceColorEntry | None


def _control(control: BodyControl, clock: BodyExecutionClock) -> tuple:
    """Detach original control references/values before any clock or file callback."""
    if type(control) is not BodyControl or type(clock) is not BodyExecutionClock:
        raise RuntimeError("source-color body seed requires actual control and body clock")
    return (id(control), id(control.invocation), str(control.root), id(control.root),
        tuple((key, id(value), str(value)) for key, value in vars(control.invocation).items()),
        id(control.value), control.value, id(control.activation), control.activation,
        id(control.documents), control.documents, id(control.held_files),
        tuple((id(row), str(row.path), row.sha256, row.identity) for row in control.held_files),
        source_color_read_clock_fields(clock))


def assert_body_control_origin(origin: object, control: BodyControl, clock: BodyExecutionClock) -> None:
    """Check original input and all control values without callbacks or JSON replay."""
    if type(origin) is not _BodyControlOrigin or origin not in _CONTROLS:
        raise RuntimeError("body control requires its actual original raw input hold")
    held_control, held_clock, original, held, parents, states = _CONTROLS[origin]
    if control is not held_control or clock is not held_clock or not same_read_metadata(_control(control, clock), original):
        raise RuntimeError("body original control/input/clock changed")
    if _directory_states(parents) != states or file_identity(held.path.lstat()) != held.identity \
            or _directory_states(parents) != states:
        raise RuntimeError("body original input metadata changed")


def capture_body_control_origin(control: BodyControl, clock: BodyExecutionClock) -> object:
    """Join the bounded original raw input BEFORE mutable version/source dispatch."""
    original = hold_read_metadata(_control(control, clock))
    invocation, origin = control.invocation, _BodyControlOrigin()
    info = invocation.input_path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= 128 * 1024:
        raise RuntimeError("body original input is not bounded regular metadata")
    held = BodyHeldFile(invocation.input_path, invocation.input_sha256, file_identity(info))
    parents = _parent_paths((held,))
    _CONTROLS[origin] = control, clock, original, held, parents, _directory_states(parents)
    source_color_read_remaining(clock)
    assert_body_control_origin(origin, control, clock)
    value = parse_current_body_input(_json(held.path, held.sha256, 128 * 1024)[0])
    if not same_read_metadata(control.value, hold_read_metadata(value)):
        raise RuntimeError("body control differs from its original raw input/version")
    assert_body_control_origin(origin, control, clock)
    source_color_read_remaining(clock)
    assert_body_control_origin(origin, control, clock)
    return origin


def _inputs(inputs: OpeningInputs) -> tuple:
    """Keep the SAME initial verified source capture, never reconstructed snapshots."""
    if type(inputs) is not OpeningInputs or inputs.verified_media is None:
        raise RuntimeError("source-color body seed needs actual verified source inputs")
    return (id(inputs), str(inputs.path), inputs.sha256, id(inputs.value), inputs.value,
        id(inputs.documents), inputs.documents, id(inputs.verified_media), inputs.verified_media.entries_json,
        tuple((id(row), row) for row in inputs.verified_media.snapshots))


def _state(seed: BodySourceColorEntry) -> dict:
    """Only the exact original private seed can expose retained read references."""
    if type(seed) is not BodySourceColorEntry or seed not in _SEEDS:
        raise RuntimeError("source-color body requires its original private input seed")
    state = _SEEDS[seed]
    if set(vars(seed)) != {"entry"} or seed.entry is not state["entry"]:
        raise RuntimeError("source-color body original input seed changed")
    return state


def _pure(state: dict) -> None:
    """Reject context or actual returned source-input substitutions before callbacks."""
    assert_body_control_origin(state["control_origin"], state["control"], state["clock"])
    if not same_read_metadata(_control(state["control"], state["clock"]), state["original"]):
        raise RuntimeError("source-color body original control or clock changed")
    if state["inputs"] is not None and not same_read_metadata(_inputs(state["inputs"]), state["input_binding"]):
        raise RuntimeError("source-color body original source input capture changed")


def check_body_source_color_entry(seed: BodySourceColorEntry) -> None:
    """Retain original controls and bound clock without a source hash or new timer."""
    state = _state(seed)
    _pure(state)
    assert_body_files(state["control"].held_files, state["clock"])
    assert_source_color_read_entry(state["entry"], state["clock"])
    _pure(state)
    _state(seed)


def capture_body_source_color_entry(control: BodyControl, clock: BodyExecutionClock,
                                   origin: object = None) -> BodySourceColorEntry:
    """Capture six original files BEFORE the current original-source input reader."""
    origin = capture_body_control_origin(control, clock) if origin is None else origin
    assert_body_control_origin(origin, control, clock)
    original = hold_read_metadata(_control(control, clock))
    if type(control.value.get("schemaVersion")) is not int or control.value["schemaVersion"] != 2:
        raise RuntimeError("source-color body input seed requires exact schema2")
    old, replay = control.documents["heldInput"]["opening"], control.value["sourceColorReplay"]
    held = ReadAuthority(old["inputSha256"], Path(old["claimPath"]), old["claimSha256"],
                         old["resultSha256"], control.documents["openingResult"]["receiptHash"])
    transport = SourceColorReadTransport(Path(replay["input"]["path"]), replay["input"]["sha256"],
        Path(replay["reservationArchive"]["path"]), replay["reservationArchive"]["sha256"])
    claim = HeldOpeningClaim(held.claim_path, held.claim_sha256, control.documents["openingExecutionClaim"])
    state = {"control": control, "clock": clock, "original": original, "inputs": None, "input_binding": None,
             "held": held, "transport": transport, "claim": claim, "used": False, "control_origin": origin}
    assert_body_files(control.held_files, clock)
    _pure(state)
    entry = capture_source_color_read_entry((Path(old["inputPath"]), Path(old["outputRoot"])), held, transport, clock)
    state["entry"] = entry
    seed = BodySourceColorEntry(entry)
    _SEEDS[seed] = state
    check_body_source_color_entry(seed)
    return seed


def finish_body_source_color_inputs(seed: BodySourceColorEntry, inputs: OpeningInputs) -> BodyInputRead:
    """Bind the actual original reader return before any later callback can alter it."""
    state = _state(seed)
    if state["inputs"] is not None:
        raise RuntimeError("source-color body original source inputs cannot be rebound")
    state["input_binding"] = hold_read_metadata(_inputs(inputs))
    state["inputs"] = inputs
    check_body_source_color_entry(seed)
    return BodyInputRead(inputs, seed)


def consume_body_source_color_entry(seed: BodySourceColorEntry, control: BodyControl,
                                    inputs: OpeningInputs, clock: BodyExecutionClock) -> tuple:
    """Use the exact original seed once; never upgrade a copied control/input/clock."""
    state = _state(seed)
    if control is not state["control"] or inputs is not state["inputs"] or clock is not state["clock"] or state["used"]:
        raise RuntimeError("source-color body original input seed is foreign or already consumed")
    check_body_source_color_entry(seed)
    state["used"] = True
    old = control.documents["heldInput"]["opening"]
    return (Path(old["outputRoot"]), state["claim"], clock, state["held"], state["entry"]), state["transport"]

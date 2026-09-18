"""Private successful picture consumption of the SAME held source-color metadata.

Tokens authenticate this live code path, not JSON, source rights, decoded
output color, an applied grade, media quality, or a publishable receipt. Native
hooks and existing manifestation/picture-copy joins are all required before a
complete record can be returned. No source hashes, decoders or clocks are made.
"""
from __future__ import annotations

from copy import deepcopy
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from weakref import WeakKeyDictionary

from audio.audio_mix_picture import PictureSource
from color.deadline import require_time
from guided_presenter_read_fingerprint import hold_read_metadata, same_read_metadata
from guided_source_color_base import HeldBt709BaseIdentity, _unchanged
from guided_source_color_consumption_records import bounded_timeline, copy_proof, join_manifestation, metadata_size, path, picture_fields, same

_HELD = WeakKeyDictionary()
_TOKENS = WeakKeyDictionary()
MAX_CONSUMPTION_BYTES = 8 * 1024 ** 2


@dataclass
class _State:
    """Private mutable progress; original ownership stays separately immutable."""

    holder: HeldBt709BaseIdentity
    guard: Callable[[], None]
    origin: tuple
    expected: dict
    cuts: tuple = ()
    pending: object = None
    joined: dict | None = None
    master: dict | None = None
    picture: object = None
    picture_hold: object = None
    proof: dict | None = None
    failed: bool = False
    busy: bool = False
    retained_bytes: int = 0
    preparation_started: bool = False


class PictureConsumptionToken:
    """Opaque single-use in-flight encode; a copied/constructed token is refused."""

    def __init__(self) -> None:
        """Only the actual recorder can create a pending token."""
        raise TypeError("picture consumption tokens are private actual encode returns")


def _state(value: object) -> _State:
    """Refuse DTOs/subclasses/constructed lookalikes before using progress."""
    if type(value) is not SourceColorPictureConsumption or value not in _HELD:
        raise RuntimeError("source-color picture recorder is not the actual held capability")
    result = _HELD[value]
    if result.failed:
        raise RuntimeError("source-color picture recorder retained a failed encode")
    if result.busy:
        raise RuntimeError("source-color picture recorder callback transition is already in progress")
    return result


def _original(value: object, state: _State) -> None:
    """Close original source metadata and deadline without invoking a new callback."""
    if vars(value) or type(state.holder) is not HeldBt709BaseIdentity:
        raise RuntimeError("source-color picture recorder fields were substituted")
    _unchanged(state.holder, state.origin)
    require_time(state.holder.batch.preparation.context.deadline)


class SourceColorPictureConsumption:
    """Optional internal recorder, tied to one actual holder and original callback."""

    def __init__(self, holder: HeldBt709BaseIdentity, guard: Callable[[], None]) -> None:
        """Capture actual original source/cut metadata before the first caller callback."""
        if type(holder) is not HeldBt709BaseIdentity or not callable(guard):
            raise RuntimeError("picture consumption requires actual held source-color and guard")
        _unchanged(holder, holder._origin)
        documents = holder.inputs.documents
        timeline = bounded_timeline(documents["candidatePlan"], documents["authority"])
        plan = deepcopy(documents["candidatePlan"])
        jobs = holder.batch.preparation.jobs
        sources = {row.binding.source_id: {"path": row.source.path, "sha256": row.binding.source_sha256,
            "admissionReceiptSha256": row.binding.admission_receipt_sha256,
            "declarationSha256": row.binding.declaration_sha256} for row in jobs}
        expected = {"plan": plan, "timeline": timeline, "sources": sources,
                    "authority": deepcopy(documents["authority"])}
        _HELD[self] = _State(holder, guard, holder._origin, expected)
        SourceColorPictureConsumption.assert_metadata(self)

    def assert_metadata(self) -> None:
        """No source/context return may substitute the actual recorder or its original owner."""
        state = _state(self)
        _original(self, state)
        if state.picture is not None and not same_read_metadata(picture_fields(state.picture), state.picture_hold):
            raise RuntimeError("source-color master original picture observation changed")

    def assert_current(self) -> None:
        """Use the original guard plus actual source holder, never a renewed allowance."""
        state = _state(self)
        SourceColorPictureConsumption.assert_metadata(self)
        state.busy = True
        try:
            HeldBt709BaseIdentity.assert_current(state.holder)
            state.guard()
        finally:
            state.busy = False
        SourceColorPictureConsumption.assert_metadata(self)

    def belongs_to(self, holder: object, guard: object) -> None:
        """Require the same original objects, not matching serialized metadata."""
        state = _state(self)
        if holder is not state.holder or guard is not state.guard:
            raise RuntimeError("source-color picture recorder belongs to another original owner")
        SourceColorPictureConsumption.assert_metadata(self)

    def begin_preparation(self) -> None:
        """Claim one fresh internal preparation before callbacks; completed hooks cannot be recycled."""
        state = _state(self)
        SourceColorPictureConsumption.assert_metadata(self)
        if state.preparation_started or state.pending is not None or state.cuts or state.master is not None:
            raise RuntimeError("source-color picture preparation cannot replay an existing recorder")
        state.preparation_started = True

    def begin(self, kind: str, request: dict, argv: tuple[str, ...]) -> PictureConsumptionToken:
        """Start one exact ordered cut occurrence or the sole post-cut master encode."""
        state = _state(self)
        if kind not in {"cut", "master"} or state.pending is not None:
            raise RuntimeError("source-color picture encode is already in flight")
        original = hold_read_metadata(request)
        expected = self._cut(request) if kind == "cut" else self._master(request)
        if not argv or argv[-1] != request["outputPath"] or request.get("sourcePath", request.get("inputPath")) not in argv:
            raise RuntimeError("source-color picture actual argv differs from its input/output")
        record = {**deepcopy(request), **expected, "argv": argv}
        size = metadata_size(record, MAX_CONSUMPTION_BYTES - state.retained_bytes - 64) + 64
        self.assert_current()
        if not same_read_metadata(request, original):
            raise RuntimeError("source-color picture request changed during original callback")
        token = object.__new__(PictureConsumptionToken)
        _TOKENS[token] = (self, kind, record, False)
        state.retained_bytes += size
        state.pending = token
        return token

    def _cut(self, request: dict) -> dict:
        """Reject reordered/repeated source occurrences and invented cumulative frames."""
        state = _state(self)
        rows = state.expected["timeline"]["segments"]
        index = len(state.cuts)
        if state.joined is not None or state.master is not None or index >= len(rows) \
                or not same(request["segment"], rows[index]) \
                or request["framesBefore"] != sum(row["frames"] for row in state.cuts):
            raise RuntimeError("source-color cut occurrence order or actual frame clock changed")
        source = state.expected["sources"][rows[index]["source_id"]]
        if request["sourcePath"] != source["path"] or path(request["outputPath"]).rsplit("/", 1)[-1] != f"part_{index:04d}.mp4" \
                or request["outputPath"] in {row["path"] for row in state.expected["sources"].values()}:
            raise RuntimeError("source-color cut source/output binding changed")
        authority = state.expected["authority"]
        expected_profile = {**authority["target"], "frameRate": request["profile"]["frameRate"], "pixelFormat": "yuv420p"}
        if not same(request["profile"], expected_profile) \
                or Fraction(request["profile"]["frameRate"]) != Fraction(authority["frameRate"]):
            raise RuntimeError("source-color cut changed the original full picture profile")
        return {"source": deepcopy(source)}

    def _master(self, request: dict) -> dict:
        """A master encode cannot hide omitted cuts, burns, or a changed exact clock."""
        state = _state(self)
        if state.joined is None or state.master is not None or request["ass"] is not None \
                or not same(request["frameCount"], state.joined["concat"]["videoFrames"]) \
                or request["inputPath"] != state.joined["concatPath"] \
                or request["inputPath"] == request["outputPath"] \
                or type(request["fps"]) is not int or not 1 <= request["fps"] <= 60:
            raise RuntimeError("source-color master omitted joined cuts or changed picture inputs")
        if Fraction(request["fpsExact"] or str(request["fps"])) != Fraction(state.joined["frameRate"]):
            raise RuntimeError("source-color master changed the original exact frame rate")
        return {}

    def native_completed(self, token: PictureConsumptionToken) -> None:
        """Only after native success and its original postguard may a token advance."""
        state, kind, record, completed = self._token(token)
        if completed:
            raise RuntimeError("source-color picture native completion was replayed")
        self.assert_current()
        _TOKENS[token] = (self, kind, record, True)
        if kind == "master":
            state.master, state.pending = record, None

    def part_completed(self, token: PictureConsumptionToken, frames: int) -> None:
        """Record measured post-clamp frames, never nominal source-time rounding."""
        state, kind, record, completed = self._token(token)
        if kind != "cut" or not completed or type(frames) is not int or not 1 <= frames <= 72000:
            raise RuntimeError("source-color cut part completion is invalid")
        self.assert_current()
        state.cuts += ({**record, "frames": frames},)
        state.pending = None

    def _token(self, token: object) -> tuple:
        """Require the actual original pending token, with no replay or DTO path."""
        state = _state(self)
        if type(token) is not PictureConsumptionToken or token not in _TOKENS \
                or _TOKENS[token][0] is not self or state.pending is not token:
            raise RuntimeError("source-color picture token is stale, foreign or fabricated")
        _owner, kind, record, completed = _TOKENS[token]
        return state, kind, record, completed

    def failed(self) -> None:
        """A native/postguard/clamp failure permanently prevents successful reuse."""
        if type(self) is SourceColorPictureConsumption and self in _HELD:
            _HELD[self].failed = True

    def join_cut_manifestation(self, value: dict, paths: tuple[str, ...], concat_path: str) -> None:
        """Bind post-remux raw parts using the existing elementary/frame proof."""
        state = _state(self)
        if state.pending is not None or state.joined is not None \
                or len(state.cuts) != len(state.expected["timeline"]["segments"]):
            raise RuntimeError("source-color manifestation omitted or replayed cut consumption")
        joined = join_manifestation(value, (state.expected["plan"], state.expected["timeline"], state.cuts, paths))
        authority = state.expected["authority"]
        if not same(joined["concat"]["videoFrames"], authority["totalFrames"]) \
                or Fraction(joined["frameRate"]) != Fraction(authority["frameRate"]):
            raise RuntimeError("source-color cut manifestation changed the original accepted frame clock")
        joined["concatPath"] = path(concat_path)
        size = metadata_size(joined, MAX_CONSUMPTION_BYTES - state.retained_bytes)
        original = hold_read_metadata(value)
        self.assert_current()
        if not same_read_metadata(value, original):
            raise RuntimeError("source-color cut manifestation changed during original callback")
        state.joined = deepcopy(joined)
        state.retained_bytes += size

    def observe_master_picture(self, picture: PictureSource) -> None:
        """Retain the actual existing observed packet object, not a reconstructed dict."""
        state = _state(self)
        if type(picture) is not PictureSource or state.master is None or state.picture is not None \
                or picture.path != state.master["outputPath"] or len(picture.packets) != state.master["frameCount"]:
            raise RuntimeError("source-color master picture observation omitted or changed the actual encode")
        size = metadata_size(picture_fields(picture), MAX_CONSUMPTION_BYTES - state.retained_bytes)
        original = hold_read_metadata(picture_fields(picture))
        self.assert_current()
        if not same_read_metadata(picture_fields(picture), original):
            raise RuntimeError("source-color master picture changed during original callback")
        state.picture, state.picture_hold = picture, original
        state.retained_bytes += size

    def complete_master_copy(self, picture: PictureSource, proof: dict) -> None:
        """Require existing exact packet-copy proof before completion, not mere encode success."""
        state = _state(self)
        if state.picture is not picture or state.proof is not None or not same(proof, copy_proof(picture)):
            raise RuntimeError("source-color master copy proof is missing, changed or replayed")
        size = metadata_size(proof, MAX_CONSUMPTION_BYTES - state.retained_bytes)
        original = hold_read_metadata(proof)
        self.assert_current()
        if not same_read_metadata(proof, original):
            raise RuntimeError("source-color master copy proof changed during original callback")
        state.proof = deepcopy(proof)
        state.retained_bytes += size

    def assert_copy(self, picture: PictureSource, proof: dict) -> None:
        """Retain the same actual observed proof through later receipt/publication callbacks."""
        state = _state(self)
        if state.picture is not picture or state.proof is None or not same(proof, state.proof):
            raise RuntimeError("source-color master original picture-copy proof changed")
        SourceColorPictureConsumption.assert_metadata(self)

    def record(self) -> dict:
        """Return detached complete metadata only; this is not a public receipt or approval."""
        state = _state(self)
        self.assert_current()
        if state.pending is not None or state.joined is None or state.proof is None:
            raise RuntimeError("source-color picture consumption is incomplete")
        result = deepcopy({"scope": "actual-picture-command-consumption-not-color-or-quality-approval",
            "cuts": [{**row, "argv": list(row["argv"])} for row in state.cuts],
            "manifestation": state.joined, "master": {**state.master, "argv": list(state.master["argv"])},
            "pictureCopy": state.proof, "colorQualified": False, "deliveryApproved": False})
        SourceColorPictureConsumption.assert_metadata(self)
        return result

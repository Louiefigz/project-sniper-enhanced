"""Keep original presenter graph checks alive around actual opening A/V readback.

The enclosing reader authenticates the stopped worker/result, graph artifacts,
pipeline and original project ownership. This context adds no approval, decoder
or execution owner. Its probe/base/source identities expire with this read scope.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from guided_caption_layers import opening_caption_layers
from guided_caption_projection import HeldCaptionProjection
from guided_opening_inputs import OpeningInputs
from guided_presenter_capture import PresenterCaptureContext, acquire_presenter_read_context
from guided_presenter_intake import is_presenter_profile
from guided_presenter_profile import presenter_caption_profile
from guided_presenter_read import PresenterReadContext, _read_guard, verify_opening_presenter_layers
from opening_prefix_contract import HeldPrefixInput


@dataclass(frozen=True)
class PresenterOpeningReadLane:
    """Original read context and independently rederived clips, not JSON authority."""

    context: PresenterReadContext
    captions: HeldCaptionProjection | None
    layers: tuple[tuple[dict, ...], int | None]

    def hold(self, arguments: object) -> Callable[[], None]:
        """Retain one original snapshot across all A/V callbacks, not a new baseline."""
        context, captions, layers = self.context, self.captions, self.layers
        original = _read_guard(context, [arguments, list(layers[0]), layers[1]])

        def check() -> None:
            """The same original lane and caller arguments survive every callback."""
            original()
            if self.context is not context or self.captions is not captions or self.layers is not layers:
                raise RuntimeError("presenter opening original read lane changed during verification")

        return check

    def verify(self, record: dict) -> None:
        """Guard actual presenter and caption evidence before/after A/V observation."""
        context, captions, layers = self.context, self.captions, self.layers
        check = self.hold(record)
        check()
        if record.get("profile") != context.inputs.value["profile"]:
            raise RuntimeError("presenter opening read profile differs from its original inputs")
        if presenter_caption_profile(record["profile"]):
            from guided_presenter_caption_read import verify_presenter_caption_picture
            verify_presenter_caption_picture(record["pictures"], context, captions, layers)
        else:
            if captions is not None or "presenterCaptionClearance" in record["pictures"]:
                raise RuntimeError("uncaptioned presenter acquired unsupported caption clearance")
            evidence = verify_opening_presenter_layers(record["pictures"], context, layers)
            if evidence is None:
                raise RuntimeError("presenter opening read lacks actual recorded presenter observations")
        check()


def _layers(inputs: OpeningInputs, record: dict, captions: HeldCaptionProjection | None) -> tuple:
    """Use authenticated current candidate rows and original actual graphic identities."""
    from guided_body_prefix import _original_clip
    from guided_opening_frames import executable_frames

    rows = executable_frames(inputs)
    proofs = record["graphics"]
    if type(proofs) is not list or len(proofs) != len(rows) or any(type(row) is not dict for row in proofs):
        raise RuntimeError("presenter opening read lost original graphic coverage")
    if any(proof.get("candidateOrder") != row["order"] or proof.get("graphicId") != row["graphicId"]
           for row, proof in zip(rows, proofs)):
        raise RuntimeError("presenter opening read graphic identity changed")
    clips = [_original_clip(row, proof) for row, proof in zip(rows, proofs)]
    if captions is None:
        return tuple(clips), None
    combined, layer = opening_caption_layers(clips, captions, inputs.documents["authority"]["review"]["endFrameExclusive"])
    return tuple(combined), layer["captionTail"]


@contextmanager
def opening_presenter_read_lane(inputs: OpeningInputs, record: dict, runtime: PresenterCaptureContext,
                                captions: HeldCaptionProjection | None = None) -> Iterator[PresenterOpeningReadLane | None]:
    """Hold actual files for a new explicit class; leave legacy read semantics intact."""
    if not is_presenter_profile(inputs.value.get("profile")):
        if any(key in record["pictures"] for key in ("presenterLayers", "presenterCaptionClearance")):
            raise RuntimeError("legacy opening cannot acquire presenter read evidence")
        yield None
        return
    if presenter_caption_profile(inputs.value["profile"]) != (captions is not None):
        raise RuntimeError("presenter opening read lacks its exact original caption choice")
    row = record["fullProgram"]["base"]
    base = HeldPrefixInput(row["path"], row["sha256"], row["sizeBytes"])
    layers = _layers(inputs, record, captions)
    with acquire_presenter_read_context(inputs, base, runtime) as context:
        yield PresenterOpeningReadLane(context, captions, layers)

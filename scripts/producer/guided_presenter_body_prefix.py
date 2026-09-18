"""Join a live body presenter to the authenticated opening's read-only graph.

No serialized result creates a live observation owner. The old opening record
is rederived only as read evidence; actual body execution uses its independently
acquired owner and the shared pre-encode prefix oracle, with the full original
windows, source clock and caption pages unchanged.
"""
from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from graphics.owned_execution import GraphicsComposition
from guided_caption_layers import caption_page_clips
from guided_presenter_execution import OwnedPresenterExecution
from opening_prefix_contract import CompositorPrefixRequest, canonical_hash
from opening_prefix_presenter import presenter_graph_payload, validate_presenter_request

if TYPE_CHECKING:
    from guided_body_prefix import BodyPrefixBinding


def _legacy(value: GraphicsComposition, binding: BodyPrefixBinding) -> None:
    """A legacy body cannot silently omit declared or recorded presenter work."""
    plan = binding.inputs.documents["candidatePlan"]
    if value.options.presenter is not None or "presenterLayouts" in plan \
            or "presenterLayers" in binding.original_result["pictures"]:
        raise RuntimeError("body presenter track requires an actual live observation owner")


def _opening_layers(request: CompositorPrefixRequest, binding: BodyPrefixBinding) -> tuple:
    """Rebuild original retained caption tail without new compilation or retiming."""
    if binding.captions is None:
        return request.opening_clips, None
    end = binding.inputs.documents["authority"]["review"]["endFrameExclusive"]
    pages = caption_page_clips(binding.captions, end)
    return (*request.opening_clips, *pages), len(pages)


def _read_opening(binding: BodyPrefixBinding, context: object, layers: tuple) -> None:
    """Captioned openings require their distinct original picture-clearance binding."""
    if binding.captions is None:
        from guided_presenter_read import verify_opening_presenter_layers
        verify_opening_presenter_layers(binding.original_result["pictures"], context, layers)
        return
    from guided_presenter_caption_read import verify_presenter_caption_picture
    verify_presenter_caption_picture(binding.original_result["pictures"], context, binding.captions, layers)


def presenter_body_prefix(request: CompositorPrefixRequest, value: GraphicsComposition,
                          binding: BodyPrefixBinding) -> CompositorPrefixRequest:
    """Validate the recorded opening separately, then attach ONLY the live body owner."""
    owner = value.presenter
    if owner is None:
        _legacy(value, binding)
        return request
    if type(owner) is not OwnedPresenterExecution or request.presenter is not None:
        raise RuntimeError("body prefix needs its single actual live presenter owner")
    owner.assert_plan(binding.inputs.documents["candidatePlan"])
    owner.assert_clock(value.canvas, value.frame_clock)
    actual = owner.full_graph()
    if value.options.presenter is None or canonical_hash(presenter_graph_payload(value.options.presenter)) \
            != canonical_hash(presenter_graph_payload(actual)):
        raise RuntimeError("body prefix presenter differs from its actual compositor options")
    from guided_presenter_read import PresenterReadContext

    context = PresenterReadContext(binding.inputs, request.base, owner.runtime.ffprobe, owner.assert_current)
    layers = _opening_layers(request, binding)
    _read_opening(binding, context, layers)
    owner.assert_current()
    pair = owner.prefix_graphs(request.ranges.review[1])
    original = binding.original_result["pictures"]["presenterLayers"]
    if original["fullPresenterGraphHash"] != canonical_hash(presenter_graph_payload(pair.full)):
        raise RuntimeError("body live presenter graph differs from the original opening")
    result = replace(request, presenter=pair)
    validate_presenter_request(result)
    owner.assert_current()
    return result

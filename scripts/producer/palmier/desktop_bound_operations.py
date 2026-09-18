"""Compose standard Desktop bindings with the exact-master reference lane."""
from __future__ import annotations

from palmier.desktop_element_types import (ElementObservation,
                                           RecoveryObservation)
from palmier.desktop_audio_master_binding import \
    bind_mastered_stereo_operation
from palmier.desktop_audio_master_guard import assert_mastered_stereo_ready
from palmier.desktop_audio_master_readback import \
    observe_mastered_stereo_operation
from palmier.desktop_elements import (bind_operation, observe_bound_operation,
                                      recover_bound_operation)
from palmier.desktop_exact_master_binding import bind_exact_master_operation
from palmier.desktop_exact_master_contract import assert_reference_ready
from palmier.desktop_exact_master_readback import observe_exact_master_operation
from palmier.mcp_client import PalmierError
from palmier.desktop_caption_shards import (
    bind_caption_operation, observe_caption_operation)
from palmier.desktop_motion import (
    bind_keyframe_operation, observe_keyframe_operation)
from palmier.desktop_caption_pages import (
    bind_caption_page_operation, observe_caption_page_operation)


def bind_desktop_operation(tool: str, args: dict, state: dict,
                           timeline: dict | None = None) -> dict | None:
    """Prefer the narrow exact-master binding, then existing lane bindings."""
    exact = bind_exact_master_operation(tool, args, state)
    mastered = bind_mastered_stereo_operation(
        tool, args, state, timeline) if exact is None else None
    pages = bind_caption_page_operation(
        tool, args, state) if exact is None and mastered is None else None
    caption = bind_caption_operation(
        tool, args, state) if exact is None and mastered is None else None
    motion = bind_keyframe_operation(
        tool, args, state, timeline) \
        if exact is None and mastered is None \
        and pages is None and caption is None else None
    if tool == "manage_tracks":
        if exact is None and mastered is None:
            raise PalmierError("unbound Desktop manage_tracks mutation")
        return exact or mastered
    return exact or mastered or pages or caption or motion or bind_operation(
        tool, args, state)


def observe_desktop_operation(observation: ElementObservation) -> None:
    """Verify one mutation and keep a ready exact reference disabled."""
    handled = observe_exact_master_operation(observation)
    if not handled:
        handled = observe_mastered_stereo_operation(observation)
    if not handled:
        handled = observe_caption_page_operation(observation)
    if not handled:
        handled = observe_caption_operation(observation)
    if not handled:
        handled = observe_keyframe_operation(observation)
    if not handled:
        observe_bound_operation(observation)
    assert_reference_ready(
        observation.state, observation.after, observation.coverage)
    assert_mastered_stereo_ready(
        observation.state, observation.after, observation.coverage)


def recover_desktop_operation(recovery: RecoveryObservation) -> None:
    """Reconcile one missed hook receipt through the same strict readback."""
    observation = ElementObservation(
        recovery.state, recovery.pending, recovery.before, recovery.after, {},
        recovery.coverage)
    handled = observe_exact_master_operation(observation)
    if not handled:
        handled = observe_mastered_stereo_operation(observation)
    if not handled:
        handled = observe_caption_page_operation(observation)
    if not handled:
        handled = observe_caption_operation(observation)
    if not handled:
        handled = observe_keyframe_operation(observation)
    if not handled:
        recover_bound_operation(recovery)
    assert_reference_ready(recovery.state, recovery.after, recovery.coverage)
    assert_mastered_stereo_ready(
        recovery.state, recovery.after, recovery.coverage)

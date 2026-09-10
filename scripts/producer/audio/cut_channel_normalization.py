"""Observe each unique cut source once before segment/J-cut audio splices."""
from __future__ import annotations

from audio.channel_normalization import (
    ChannelAuthority,
    observe_channel_authority,
    system_program_request,
)
from media_probe import has_audio


def observe_cut_source_set(
    paths: set[str],
) -> dict[str, ChannelAuthority | None]:
    """Return exact first-audio authority, or None for a silent source."""
    return {
        path: (
            observe_channel_authority(system_program_request(path))
            if has_audio(path) else None
        )
        for path in sorted(paths)
    }


def cut_source_receipts(
    authorities: dict[str, ChannelAuthority | None],
) -> list[dict[str, object]]:
    """Serializable, deterministic authority evidence for one cut render."""
    return [
        {"sourcePath": path, "receipt": authority.receipt}
        for path, authority in sorted(authorities.items())
        if authority is not None
    ]


def assert_cut_sources_stable(
    authorities: dict[str, ChannelAuthority | None],
) -> None:
    """Recheck every held source identity before publication."""
    for authority in authorities.values():
        if authority is not None:
            authority.assert_stable()

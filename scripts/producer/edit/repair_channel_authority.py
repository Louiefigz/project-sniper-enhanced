"""Shared pinned channel authority for fragment and composite repair splices."""
from __future__ import annotations

from dataclasses import dataclass

from audio.channel_normalization import (
    ChannelAuthority,
    ChannelNormalizationError,
    ChannelTools,
    first_audio_request,
    observe_channel_authority,
)
from edit.repair_fragment_contracts import RepairMediaTools, RepairRenderError


@dataclass(frozen=True)
class RepairChannelRequest:
    """Two content-pinned program inputs and their repair policy."""

    first_label: str
    first_path: str
    first_sha256: str
    second_label: str
    second_path: str
    second_sha256: str
    tools: RepairMediaTools
    second_may_repair: bool


@dataclass(frozen=True)
class RepairChannelPair:
    """Exact channel decisions consumed by one audio splice."""

    first: ChannelAuthority
    second: ChannelAuthority
    first_label: str
    second_label: str

    def receipts(self) -> dict[str, object]:
        return {
            self.first_label: self.first.receipt,
            self.second_label: self.second.receipt,
        }

    def assert_stable(self) -> None:
        self.first.assert_stable()
        self.second.assert_stable()


def _tools(value: RepairMediaTools) -> ChannelTools:
    return ChannelTools(
        value.ffmpeg_path, value.ffmpeg_sha256,
        value.ffprobe_path, value.ffprobe_sha256)


def _observe(
    path: str,
    sha256: str,
    tools: ChannelTools,
) -> ChannelAuthority:
    return observe_channel_authority(
        first_audio_request(path, sha256, tools))


def _require_already_normalized(
    authority: ChannelAuthority,
    label: str,
) -> None:
    status = authority.receipt["decision"]["status"]  # type: ignore[index]
    if status != "stereo-verified":
        raise RepairRenderError(
            f"{label} is not an already-normalized stereo authority "
            f"(observed {status})")


def observe_repair_channel_pair(
    request: RepairChannelRequest,
) -> RepairChannelPair:
    """Observe both inputs; repair only an explicitly raw second source."""
    try:
        tools = _tools(request.tools)
        first = _observe(
            request.first_path, request.first_sha256, tools)
        second = _observe(
            request.second_path, request.second_sha256, tools)
        _require_already_normalized(first, request.first_label)
        if not request.second_may_repair:
            _require_already_normalized(second, request.second_label)
        return RepairChannelPair(
            first, second, request.first_label, request.second_label)
    except ChannelNormalizationError as exc:
        raise RepairRenderError(
            f"repair channel authority failed: {exc}") from exc

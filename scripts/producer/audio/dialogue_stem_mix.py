"""Bounded-fan-in exact sample placement for dialogue entry shards."""
from __future__ import annotations

import os
from dataclasses import dataclass

from audio.dialogue_stem_contracts import (
    DialogueStemRenderError,
    ValidatedDialogueStemRequest,
)
from audio.dialogue_stem_media import (
    OUTPUT_NAME,
    _pcm_output_args,
    _write_new,
)
from audio.dialogue_stem_probe import probe_pcm, run_media

_MIX_BATCH_SIZE = 64


@dataclass(frozen=True)
class MixPlacement:
    """One exact-length PCM input placed on a sample offset."""

    path: str
    start_sample: int
    length_samples: int


@dataclass(frozen=True)
class MixJob:
    """One bounded-fan-in FFmpeg mix invocation."""

    placements: tuple[MixPlacement, ...]
    total_samples: int
    script_path: str
    output_path: str


def _placement_graph(
    placements: tuple[MixPlacement, ...],
    total: int,
    rate: int,
) -> str:
    lines = [
        f"anullsrc=r={rate}:cl=mono,atrim=end_sample={total},"
        "asetpts=N/SR/TB[base]"
    ]
    for index, item in enumerate(placements):
        lines.append(
            f"[{index}:a]apad=whole_len={item.length_samples},"
            f"atrim=end_sample={item.length_samples},asetpts=N/SR/TB,"
            f"adelay={item.start_sample}S:all=1[mix{index:04}]")
    inputs = "[base]" + "".join(
        f"[mix{index:04}]" for index in range(len(placements)))
    lines.append(
        f"{inputs}amix=inputs={len(placements) + 1}:duration=first:"
        f"dropout_transition=0:normalize=0,atrim=end_sample={total},"
        "asetpts=N/SR/TB,aformat=sample_fmts=s32:"
        "channel_layouts=mono[out]")
    return ";\n".join(lines) + "\n"


def _render_placements(
    request: ValidatedDialogueStemRequest,
    job: MixJob,
) -> dict[str, object]:
    rate = request.dialogue_map["projectSampleRate"]
    _write_new(
        job.script_path,
        _placement_graph(job.placements, job.total_samples, rate))
    command = [
        request.tools.ffmpeg_path, "-nostdin", "-v", "error", "-y",
    ]
    for item in job.placements:
        command.extend(["-i", item.path])
    command.extend(["-filter_complex_script", job.script_path])
    command.extend(_pcm_output_args("[out]", rate, job.output_path))
    run_media(command, "dialogue bounded-fan-in mix")
    return probe_pcm(
        job.output_path, request.tools, rate, job.total_samples)


def _entry_placement(path: str, row: dict, origin: int) -> MixPlacement:
    output = row["outputSampleRange"]
    return MixPlacement(
        path,
        output["startSample"] - origin,
        output["endSampleExclusive"] - output["startSample"],
    )


def _batch_ranges(rows: list[dict]) -> list[tuple[int, int]]:
    """Keep every overlap-connected entry cluster inside one mix batch."""
    ranges: list[tuple[int, int]] = []
    start = 0
    while start < len(rows):
        end = min(start + _MIX_BATCH_SIZE, len(rows))
        latest_end = max(
            row["outputSampleRange"]["endSampleExclusive"]
            for row in rows[start:end])
        while end < len(rows) \
                and rows[end]["outputSampleRange"]["startSample"] < latest_end:
            latest_end = max(
                latest_end,
                rows[end]["outputSampleRange"]["endSampleExclusive"])
            end += 1
        ranges.append((start, end))
        start = end
    return ranges


def _render_buses(
    request: ValidatedDialogueStemRequest,
    entries: tuple[str, ...],
    work_dir: str,
) -> tuple[MixPlacement, ...]:
    rows = request.dialogue_map["entries"]
    buses: list[MixPlacement] = []
    for batch_index, (start, end) in enumerate(_batch_ranges(rows)):
        batch_rows = rows[start:end]
        origin = min(
            row["outputSampleRange"]["startSample"] for row in batch_rows)
        terminal = max(
            row["outputSampleRange"]["endSampleExclusive"]
            for row in batch_rows)
        output = os.path.join(work_dir, f"mix-bus-{batch_index:04}.wav")
        placements = tuple(
            _entry_placement(path, row, origin)
            for path, row in zip(entries[start:end], batch_rows)
        )
        job = MixJob(
            placements, terminal - origin,
            os.path.join(work_dir, f"mix-bus-{batch_index:04}.txt"),
            output,
        )
        _render_placements(request, job)
        buses.append(MixPlacement(output, origin, terminal - origin))
    if len(buses) > _MIX_BATCH_SIZE:
        raise DialogueStemRenderError(
            "dialogue bus fan-in exceeds the bounded renderer policy")
    return tuple(buses)


def render_mix(
    request: ValidatedDialogueStemRequest,
    entries: tuple[str, ...],
    work_dir: str,
    output_dir: str,
) -> tuple[str, dict[str, object]]:
    """Mix entries with bounded fan-in and prove exact B(F) termination."""
    rows = request.dialogue_map["entries"]
    if len(entries) != len(rows):
        raise DialogueStemRenderError(
            "dialogue entry media closure does not match the map")
    if len(entries) <= _MIX_BATCH_SIZE:
        placements = tuple(
            _entry_placement(path, row, 0)
            for path, row in zip(entries, rows))
    else:
        placements = _render_buses(request, entries, work_dir)
    output = os.path.join(output_dir, OUTPUT_NAME)
    job = MixJob(
        placements, request.dialogue_map["totalOutputSamples"],
        os.path.join(work_dir, "mix-final.txt"), output)
    proof = _render_placements(request, job)
    return output, proof

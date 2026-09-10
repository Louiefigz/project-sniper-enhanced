"""Sample-native FFmpeg compiler for one private dialogue stem."""
from __future__ import annotations

import os
from decimal import Decimal, localcontext
from fractions import Fraction

from audio.dialogue_stem_contracts import (
    DialogueStemRenderError,
    ValidatedDialogueStemRequest,
)
from audio.dialogue_stem_probe import (
    DecodedSource,
    decode_source,
    normalize_source,
    probe_pcm,
    run_media,
)

OUTPUT_NAME = "dialogue-stem.wav"
_MAX_ENTRIES = 4096
_ENTRY_BATCH_SIZE = 64
_RUBBERBAND_MIN = Fraction(1, 100)
_RUBBERBAND_MAX = Fraction(100, 1)


def _source_rates(dialogue_map: dict) -> dict[str, int]:
    rates: dict[str, int] = {}
    for row in dialogue_map["entries"]:
        rates[row["sourceId"]] = row["sourceSampleRate"]
    return rates


def decode_sources(
    request: ValidatedDialogueStemRequest,
    work_dir: str,
) -> tuple[DecodedSource, ...]:
    """Decode each selected source exactly once and prove native bounds."""
    rates = _source_rates(request.dialogue_map)
    native = tuple(
        decode_source(
            source, rates[source.source_id],
            os.path.join(work_dir, f"source-{index:04}.wav"),
            request.tools,
        )
        for index, source in enumerate(request.sources)
    )
    decoded = tuple(
        normalize_source(
            item, request.dialogue_map["projectSampleRate"],
            os.path.join(work_dir, f"normalized-{index:04}.wav"),
            request.tools,
        )
        for index, item in enumerate(native)
    )
    _assert_source_bounds(request.dialogue_map, decoded)
    return decoded


def _assert_source_bounds(
    dialogue_map: dict,
    decoded: tuple[DecodedSource, ...],
) -> None:
    available = {
        item.source.source_id: int(item.proof["decodedSamples"])
        for item in decoded
    }
    normalized = {
        item.source.source_id: int(item.proof["normalizedDecodedSamples"])
        for item in decoded
    }
    for row in dialogue_map["entries"]:
        end = row["sourceSampleRange"]["endSampleExclusive"]
        projected = row["normalizedSourceSampleRange"]["endSampleExclusive"]
        if end > available[row["sourceId"]] \
                or projected > normalized[row["sourceId"]]:
            raise DialogueStemRenderError(
                f"{row['dialogueSegmentId']} exceeds decoded source samples")


def _fraction(value: dict[str, str]) -> Fraction:
    return Fraction(int(value["numerator"]), int(value["denominator"]))


def _tempo_token(value: dict[str, str]) -> str:
    ratio = _fraction(value)
    if not _RUBBERBAND_MIN <= ratio <= _RUBBERBAND_MAX:
        raise DialogueStemRenderError(
            "dialogue effective speed exceeds rubberband policy bounds")
    with localcontext() as context:
        context.prec = 32
        decimal = Decimal(ratio.numerator) / Decimal(ratio.denominator)
        token = format(decimal, "f")
        if "." in token:
            token = token.rstrip("0").rstrip(".")
    return token or "0"


def _source_branches(
    dialogue_map: dict,
    decoded: tuple[DecodedSource, ...],
) -> tuple[list[str], dict[int, str]]:
    rows = dialogue_map["entries"]
    lines: list[str] = []
    branches: dict[int, str] = {}
    for source_index, item in enumerate(decoded):
        indexes = [
            index for index, row in enumerate(rows)
            if row["sourceId"] == item.source.source_id
        ]
        if not indexes:
            continue
        normalized = f"normalized{source_index:04}"
        prefix = (
            f"[{source_index}:a]asetpts=N/SR/TB,"
            "aformat=sample_fmts=fltp:channel_layouts=mono"
        )
        if len(indexes) == 1:
            branches[indexes[0]] = normalized
            lines.append(f"{prefix}[{normalized}]")
            continue
        labels = "".join(f"[source{source_index:04}e{index:04}]"
                         for index in indexes)
        lines.append(f"{prefix},asplit={len(indexes)}{labels}")
        for index in indexes:
            branches[index] = f"source{source_index:04}e{index:04}"
    return lines, branches


def _entry_filter(index: int, row: dict, branch: str) -> tuple[str, str]:
    normalized = row["normalizedSourceSampleRange"]
    tempo = _tempo_token(row["effectiveSpeed"])
    filters = [
        f"[{branch}]atrim=start_sample={normalized['startSample']}:"
        f"end_sample={normalized['endSampleExclusive']}",
        "asetpts=N/SR/TB",
    ]
    if _fraction(row["effectiveSpeed"]) != 1:
        filters.append(
            f"rubberband=tempo={tempo}:pitch=1:formant=preserved:"
            "pitchq=quality:channels=together")
        filters.append("asetpts=N/SR/TB")
    filters.append("aformat=sample_fmts=s32:channel_layouts=mono")
    return ",".join(filters) + f"[entry{index:04}]", tempo


def _raw_filter_graph(
    dialogue_map: dict,
    decoded: tuple[DecodedSource, ...],
) -> tuple[str, list[str]]:
    lines, branches = _source_branches(dialogue_map, decoded)
    tempos: list[str] = []
    for index, row in enumerate(dialogue_map["entries"]):
        line, tempo = _entry_filter(index, row, branches[index])
        lines.append(line)
        tempos.append(tempo)
    return ";\n".join(lines) + "\n", tempos


def _write_new(path: str, value: str) -> None:
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        raw = value.encode("utf-8")
        position = 0
        while position < len(raw):
            position += os.write(descriptor, raw[position:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def render_raw_entries(
    request: ValidatedDialogueStemRequest,
    decoded: tuple[DecodedSource, ...],
    work_dir: str,
) -> tuple[tuple[str, ...], list[dict[str, object]]]:
    """Render each retimed entry once so pre-reconciliation is observable."""
    rows = request.dialogue_map["entries"]
    if len(rows) > _MAX_ENTRIES:
        raise DialogueStemRenderError("dialogue map exceeds renderer entry cap")
    outputs = tuple(
        os.path.join(work_dir, f"entry-{index:04}.wav")
        for index in range(len(rows))
    )
    tempos: list[str] = []
    for start in range(0, len(rows), _ENTRY_BATCH_SIZE):
        end = min(start + _ENTRY_BATCH_SIZE, len(rows))
        tempos.extend(_render_entry_batch(
            request, decoded, work_dir, (start, end)))
    proofs = [
        _entry_proof(path, row, tempos[index], request)
        for index, (path, row) in enumerate(zip(outputs, rows))
    ]
    return outputs, proofs


def _render_entry_batch(
    request: ValidatedDialogueStemRequest,
    decoded: tuple[DecodedSource, ...],
    work_dir: str,
    bounds: tuple[int, int],
) -> list[str]:
    start, end = bounds
    rows = request.dialogue_map["entries"][start:end]
    used = {row["sourceId"] for row in rows}
    inputs = tuple(
        item for item in decoded if item.source.source_id in used)
    batch_map = {**request.dialogue_map, "entries": rows}
    graph, tempos = _raw_filter_graph(batch_map, inputs)
    script = os.path.join(work_dir, f"entry-filter-{start:04}.txt")
    _write_new(script, graph)
    command = [
        request.tools.ffmpeg_path, "-nostdin", "-v", "error", "-y",
    ]
    for item in inputs:
        command.extend(["-i", item.project_pcm_path])
    command.extend(["-filter_complex_script", script])
    for local, global_index in enumerate(range(start, end)):
        command.extend(_pcm_output_args(
            f"[entry{local:04}]", request.dialogue_map["projectSampleRate"],
            os.path.join(work_dir, f"entry-{global_index:04}.wav")))
    run_media(command, "dialogue entry render")
    return tempos


def _pcm_output_args(label: str, rate: int, path: str) -> list[str]:
    return [
        "-map", label, "-ar", str(rate), "-ac", "1",
        "-c:a", "pcm_s32le", "-map_metadata", "-1",
        "-fflags", "+bitexact", "-flags:a", "+bitexact", path,
    ]


def _entry_proof(
    path: str,
    row: dict,
    tempo: str,
    request: ValidatedDialogueStemRequest,
) -> dict[str, object]:
    proof = probe_pcm(
        path, request.tools, request.dialogue_map["projectSampleRate"])
    actual = int(proof["decodedSamples"])
    output = row["outputSampleRange"]
    expected = output["endSampleExclusive"] - output["startSample"]
    residual = expected - actual
    allowance = 0 if _fraction(row["effectiveSpeed"]) == 1 \
        else max(1, expected // 1000)
    if actual <= 0 or abs(residual) > allowance:
        raise DialogueStemRenderError(
            f"{row['dialogueSegmentId']} retime residual exceeds policy")
    return {
        "tempoToken": tempo,
        "preReconcileSamples": actual,
        "reconciliationSamples": residual,
    }

"""Caption-refit and exact dialogue J/L fixtures for the retained P2 cohort."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from captions.caption_operations import (
    new_caption_track,
    upsert_caption_range,
)
from captions.caption_plan_pipeline import PlanCaptionContext
from captions.caption_repair_revalidation import (
    CaptionRepairContexts,
)
from captions.caption_words import CaptionFrameRate, stable_word_id
from captions.dialogue_caption_compile import (
    compile_plan_dialogue_caption_track,
)
from compile_timeline import compile_plan
from edit.dialogue_authority import (
    compile_dialogue_map,
    dialogue_map_hash,
)
from edit.exact_timing import PositiveRational, ProjectClock
from edit.picture_lock_common import content_hash

TOTAL_FRAMES = 150
SPLIT_FRAME = 75
_HANDLE_SAMPLES = 2_400


@dataclass(frozen=True)
class CaptionFixtureInput:
    """Clock and dirty-window inputs for one claim-cohort case."""

    root: Path
    rate: PositiveRational
    clock: ProjectClock
    dirty_start: int


@dataclass(frozen=True)
class _DialogueTerms:
    first_seam: int
    second_seam: int
    total_samples: int

    @property
    def b_primary_end(self) -> int:
        """Return source-b's sample boundary between primary and L handle."""
        return _HANDLE_SAMPLES + self.second_seam - self.first_seam


def _caption_track() -> dict:
    track = new_caption_track("off")
    for source_id in ("source-a", "source-b"):
        track = upsert_caption_range(track, {
            "wordIds": [stable_word_id(source_id, 0)],
            "styleId": "karaoke",
            "mode": "karaoke-word",
            "placement": "bottom-center",
        })
    return track


def _caption_plan(item: CaptionFixtureInput) -> dict:
    half = SPLIT_FRAME * item.rate.denominator / item.rate.numerator
    return {
        "target": {"mode": "longform"},
        "cutTrack": [
            {"sourceId": "source-a", "start": 0.0,
             "end": half, "speed": 1.0},
            {"sourceId": "source-b", "start": 0.0,
             "end": half, "speed": 1.0},
        ],
        "captions": {"burn": False},
        "captionsTrack": _caption_track(),
    }


def _word(text: str, start: float, end: float) -> dict:
    return {"word": text, "start": start, "end": end}


def _write_transcript(path: Path, word: dict) -> None:
    payload = {"transcript": [{
        "start": 0, "end": word["end"], "words": [word],
    }]}
    path.write_text(json.dumps(payload), encoding="utf-8")


def _repair_word_times(item: CaptionFixtureInput) -> tuple[str, float, float]:
    source_id = "source-a" if item.dirty_start < SPLIT_FRAME else "source-b"
    offset = 0 if source_id == "source-a" else SPLIT_FRAME
    local = (
        (item.dirty_start - offset)
        * item.rate.denominator / item.rate.numerator
        + 0.002
    )
    return source_id, local, local + 0.042


def _manifest_pair(item: CaptionFixtureInput) -> tuple[dict, dict]:
    repair_source, start, before_end = _repair_word_times(item)
    manifests = []
    for state, extra in (("before", 0.0), ("after", 0.004)):
        sources = []
        for source_id in ("source-a", "source-b"):
            path = item.root / f"{state}-{source_id}.json"
            word = (_word("repair", start, before_end + extra)
                    if source_id == repair_source
                    else _word("fixed", 0.2, 0.25))
            _write_transcript(path, word)
            sources.append({
                "id": source_id, "transcriptPath": str(path),
            })
        manifests.append({"sources": sources})
    return manifests[0], manifests[1]


def caption_contexts(
    item: CaptionFixtureInput,
) -> tuple[CaptionRepairContexts, dict]:
    """Build actual before/after compiler contexts with one local timing refit."""
    plan = _caption_plan(item)
    before_manifest, after_manifest = _manifest_pair(item)
    timeline = compile_plan(plan)
    rate = CaptionFrameRate(item.rate.numerator, item.rate.denominator)
    before = PlanCaptionContext(
        plan, before_manifest, timeline, rate, str(item.root))
    after = PlanCaptionContext(
        plan, after_manifest, timeline, rate, str(item.root))
    repair_source, _, _ = _repair_word_times(item)
    metadata = {
        "repairSourceId": repair_source,
        "sourceIds": ["source-a", "source-b"],
        "repairWordId": stable_word_id(repair_source, 0),
    }
    return CaptionRepairContexts(before, after), metadata


def _primary(
    ident: str,
    source_id: str,
    output: tuple[int, int],
    source_start: int = 0,
) -> dict:
    length = output[1] - output[0]
    return {
        "dialogueSegmentId": f"dialogue-{ident}-primary",
        "cutSegmentId": f"cut-{ident}",
        "elementVersion": 2 if ident == "b" else 1,
        "sourceId": source_id,
        "sourceSampleRate": 48_000,
        "sourceSampleRange": {
            "startSample": source_start,
            "endSampleExclusive": source_start + length,
        },
        "outputSampleRange": {
            "startSample": output[0], "endSampleExclusive": output[1],
        },
        "speed": {"numerator": "1", "denominator": "1"},
        "role": "primary",
    }


def _handle(
    role: str,
    source: tuple[int, int],
    output: tuple[int, int],
    covered_by: str,
) -> dict:
    return {
        "dialogueSegmentId": f"dialogue-b-{role}",
        "cutSegmentId": "cut-b", "elementVersion": 2,
        "sourceId": "source-b", "sourceSampleRate": 48_000,
        "sourceSampleRange": {
            "startSample": source[0], "endSampleExclusive": source[1],
        },
        "outputSampleRange": {
            "startSample": output[0], "endSampleExclusive": output[1],
        },
        "speed": {"numerator": "1", "denominator": "1"},
        "role": f"{role}-cut-handle",
        "seamSample": output[1] if role == "j" else output[0],
        "coveredByCutSegmentId": f"cut-{covered_by}",
    }


def _dialogue_segments(terms: _DialogueTerms) -> list[dict]:
    first, second = terms.first_seam, terms.second_seam
    b_end = terms.b_primary_end
    return [
        _primary("a", "source-a", (0, first)),
        _handle(
            "j", (0, _HANDLE_SAMPLES),
            (first - _HANDLE_SAMPLES, first), "a"),
        _primary(
            "b", "source-b", (first, second), _HANDLE_SAMPLES),
        _primary(
            "c", "source-c", (second, terms.total_samples)),
        _handle(
            "l", (b_end, b_end + _HANDLE_SAMPLES),
            (second, second + _HANDLE_SAMPLES), "c"),
    ]


def _dialogue_words(terms: _DialogueTerms) -> list[dict]:
    ranges = (
        (stable_word_id("source-b", 0), 1_200, 3_600, "j-crossing"),
        (stable_word_id("source-b", 1),
         terms.b_primary_end - 1_200,
         terms.b_primary_end + 1_200, "l-crossing"),
    )
    return [{
        "sourceWordId": ident, "occurrence": 1, "text": text,
        "sourceId": "source-b", "ownerCutSegmentId": "cut-b",
        "sourceSampleRate": 48_000,
        "sourceSampleRange": {
            "startSample": start, "endSampleExclusive": end,
        },
        "transcriptTimingHash": "a" * 64,
    } for ident, start, end, text in ranges]


def dialogue_evidence(
    item: CaptionFixtureInput,
    picture_map_hash: str,
) -> dict:
    """Compile general J and L-crossing karaoke captions at this exact rate."""
    terms = _DialogueTerms(
        item.clock.sample_at_frame(50),
        item.clock.sample_at_frame(100),
        item.clock.sample_at_frame(TOTAL_FRAMES),
    )
    track = {
        "schemaVersion": 1, "kind": "dialogue-track",
        "sourceSnapshotSetHash": content_hash(
            ["source-a", "source-b", "source-c"]),
        "pictureTimelineMapHash": picture_map_hash,
        "projectFps": item.rate.to_dict(), "projectSampleRate": 48_000,
        "totalOutputFrames": TOTAL_FRAMES,
        "totalOutputSamples": terms.total_samples,
        "maxAbsoluteSpeedDeviation": {
            "numerator": "1", "denominator": "48000",
        },
        "segments": _dialogue_segments(terms),
    }
    dialogue_map = compile_dialogue_map(track)
    plan = {
        "target": {"mode": "longform"},
        "captionsTrack": new_caption_track("karaoke"),
    }
    compilation = compile_plan_dialogue_caption_track(
        plan, CaptionFrameRate(
            item.rate.numerator, item.rate.denominator),
        _dialogue_words(terms), dialogue_map)
    bindings = compilation["wordOccurrenceBindings"]
    return {
        "dialogueTrackHash": dialogue_map["dialogueTrackHash"],
        "dialogueMapHash": dialogue_map_hash(dialogue_map),
        "captionCompilationHash": content_hash(compilation),
        "cueCount": len(compilation["cues"]),
        "renderedWordCount":
            len(compilation["coverage"]["renderedWordIds"]),
        "jRoles": bindings[0]["dialogueRoles"],
        "jCoveringCutSegmentIds":
            bindings[0]["coveringCutSegmentIds"],
        "lRoles": bindings[1]["dialogueRoles"],
        "lCoveringCutSegmentIds":
            bindings[1]["coveringCutSegmentIds"],
    }

"""Source-bound cut geometry and speech-edge validation."""
from __future__ import annotations

from dataclasses import dataclass

from transcript_cut_evidence import SourceEvidence
from transcript_cut_silence import BOUNDARY_EPS_S, inspect_joined, inspect_retained

SILENCE_PROBE_S = 0.04


@dataclass(frozen=True)
class Boundary:
    """One named source-clock edge under review."""

    tag: str
    at: float
    edge: str


def _inside_word(at: float, words: list[dict]) -> dict | None:
    """Find a word strictly crossing this cut boundary."""
    return next((word for word in words
                 if word["start"] + BOUNDARY_EPS_S < at
                 < word["end"] - BOUNDARY_EPS_S), None)


def _neighbors(at: float, words: list[dict]) -> tuple[dict | None, dict | None]:
    """Return complete transcript neighbors, preserving their original bounds."""
    before = next((word for word in reversed(words)
                   if word["end"] <= at + BOUNDARY_EPS_S), None)
    after = next((word for word in words if word["start"] >= at - BOUNDARY_EPS_S), None)
    return before, after


def _word_receipt(word: dict | None) -> dict | None:
    """Record original transcript bounds in the diagnostic receipt."""
    if word is None:
        return None
    return {"word": word["word"], "start": round(word["start"], 4),
            "end": round(word["end"], 4)}


def _boundary_receipt(boundary: Boundary, source: SourceEvidence,
                      errors: list[str]) -> dict:
    """Keep word admission separate from acoustic retained-silence accounting."""
    tag, at, edge = boundary.tag, boundary.at, boundary.edge
    inside = _inside_word(at, source.words)
    # A boundary inside a word is a cut into speech — unless the audio itself was measured
    # silent on the REMOVED side of it, which means the word is mis-timed, not that speech
    # is being cut. A kept range ends where silence begins and starts where it ends, so the
    # side to check is the one the cut swallows: after an `end`, before a `start`.
    # A kept range ends where silence begins and starts where it ends, so the probe window
    # touches the span's own edge: the probe distance IS the margin here, and asking for
    # more would refuse every real boundary.
    removed_side = (at, at + SILENCE_PROBE_S) if edge == "end" else (at - SILENCE_PROBE_S, at)
    admitted = bool(inside) and source.measured_silent(*removed_side, margin=0.0)
    before, after = _neighbors(at, source.words)
    if inside and not admitted:
        errors.append(f"{tag}: {edge} {at:.3f}s cuts through word {inside['word']!r} "
                      f"[{inside['start']:.3f},{inside['end']:.3f}]")
    return {"at": round(at, 4), "before": _word_receipt(before),
            "after": _word_receipt(after), "insideWord": _word_receipt(inside),
            **({"admittedByMeasuredSilence": True} if admitted else {})}


def _validate_cuts(plan: dict, sources: dict[str, SourceEvidence], errors: list[str]
                   ) -> tuple[list[dict], dict[str, list[tuple]]]:
    """Validate source geometry, word edges and retained acoustic silence."""
    receipts: list[dict] = []
    by_source: dict[str, list[tuple]] = {}
    for index, cut in enumerate(plan.get("cutTrack") or []):
        tag, source_id = f"cutTrack[{index}]", str(cut.get("sourceId", ""))
        source = sources.get(source_id)
        if source is None:
            errors.append(f"{tag}: sourceId {source_id!r} has no transcript authority")
            continue
        try:
            start, end = float(cut["start"]), float(cut["end"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"{tag}: start/end must be numeric")
            continue
        if not 0 <= start < end <= source.duration + BOUNDARY_EPS_S:
            errors.append(
                f"{tag}: [{start},{end}] outside source duration {source.duration}")
            continue
        if len(str(cut.get("rationale", "")).strip()) < 12:
            errors.append(
                f"{tag}: rationale must explain why this transcript range is kept")
        seam = {"cutIndex": index, "sourceId": source_id,
                "start": _boundary_receipt(Boundary(tag, start, "start"), source, errors),
                "end": _boundary_receipt(Boundary(tag, end, "end"), source, errors)}
        inspect_retained(cut, source, seam, errors)
        receipts.append(seam)
        by_source.setdefault(source_id, []).append((start, end, index))
    inspect_joined(receipts, errors)
    for source_id, ranges in by_source.items():
        for previous, current in zip(ranges, ranges[1:]):
            if current[0] < previous[0]:
                errors.append(
                    f"cutTrack[{current[2]}]: source {source_id!r} moves backward "
                    f"after cutTrack[{previous[2]}]")
            if current[0] < previous[1] - BOUNDARY_EPS_S:
                errors.append(
                    f"cutTrack[{current[2]}]: overlaps cutTrack[{previous[2]}] "
                    f"in source {source_id!r}")
    return receipts, by_source

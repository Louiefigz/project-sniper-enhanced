#!/usr/bin/env python3
"""Prove transcript-bound cuts and reject kept-speech defects previsual."""
from __future__ import annotations

import argparse
import json
import re

from transcript_cut_evidence import (
    SourceEvidence, file_hash, load_cut_parent, recheck_cut_parents, source_evidence, stable_hash,
)
from transcript_cut_quality import inspect_output
from transcript_timing_review import ReviewInput, consume as consume_timing_reviews

BOUNDARY_EPS_S, GAP_MATCH_EPS_S = 0.015, 0.05
SILENCE_PROBE_S = 0.04   # how far into the removed side the audio must measure silent
MAX_SEAM_SILENCE_S, MIN_REMOVAL_S = 0.75, 0.04
REMOVAL_KINDS = {"dead_air", "false_start", "retake", "filler", "content", "other"}
PREVISUAL_KEYS = {"planVersion", "target", "cutTrack", "cutDecisions"}


def _inside_word(at: float, words: list[dict]) -> dict | None:
    return next((word for word in words
                 if word["start"] + BOUNDARY_EPS_S < at
                 < word["end"] - BOUNDARY_EPS_S), None)


def _neighbors(at: float, words: list[dict]) -> tuple[dict | None, dict | None]:
    before = next((word for word in reversed(words)
                   if word["end"] <= at + BOUNDARY_EPS_S), None)
    after = next((word for word in words if word["start"] >= at - BOUNDARY_EPS_S), None)
    return before, after


def _word_receipt(word: dict | None) -> dict | None:
    if word is None:
        return None
    return {"word": word["word"], "start": round(word["start"], 4),
            "end": round(word["end"], 4)}


def _boundary_receipt(tag: str, at: float, edge: str,
                      source: SourceEvidence, errors: list[str]) -> dict:
    inside = _inside_word(at, source.words)
    # A boundary inside a word is a cut into speech — unless the audio itself was measured
    # silent on the REMOVED side of it, which means the word is mis-timed, not that speech
    # is being cut. A kept range ends where silence begins and starts where it ends, so the
    # side to check is the one the cut swallows: after an `end`, before a `start`.
    removed_side = (at, at + SILENCE_PROBE_S) if edge == "end" else (at - SILENCE_PROBE_S, at)
    admitted = bool(inside) and source.measured_silent(*removed_side)
    before, after = _neighbors(at, source.words)
    if inside and not admitted:
        errors.append(f"{tag}: {edge} {at:.3f}s cuts through word {inside['word']!r} "
                      f"[{inside['start']:.3f},{inside['end']:.3f}]")
    if edge == "start" and at > BOUNDARY_EPS_S:
        silence = (after["start"] - at) if after else float("inf")
        if silence > MAX_SEAM_SILENCE_S:
            errors.append(f"{tag}: start has {silence:.3f}s before its first kept word "
                          f"(max {MAX_SEAM_SILENCE_S}s)")
    if edge == "end" and at < source.duration - BOUNDARY_EPS_S:
        silence = (at - before["end"]) if before else float("inf")
        if silence > MAX_SEAM_SILENCE_S:
            errors.append(f"{tag}: end has {silence:.3f}s after its last kept word "
                          f"(max {MAX_SEAM_SILENCE_S}s)")
    return {"at": round(at, 4), "before": _word_receipt(before),
            "after": _word_receipt(after), "insideWord": _word_receipt(inside),
            **({"admittedByMeasuredSilence": True} if admitted else {})}


def _validate_cuts(plan: dict, sources: dict[str, SourceEvidence], errors: list[str]
                   ) -> tuple[list[dict], dict[str, list[tuple]]]:
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
                "start": _boundary_receipt(tag, start, "start", source, errors),
                "end": _boundary_receipt(tag, end, "end", source, errors)}
        receipts.append(seam)
        by_source.setdefault(source_id, []).append((start, end, index))
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


def _norm(text: object) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(text).lower())


def _contains_tokens(haystack: list[str], needle: list[str]) -> bool:
    return bool(needle) and any(haystack[i:i + len(needle)] == needle
                                for i in range(len(haystack) - len(needle) + 1))


def _matching_decision(decisions: list[dict], source_id: str, start: float,
                       end: float) -> tuple[int, dict] | None:
    for index, decision in enumerate(decisions):
        try:
            same = str(decision.get("sourceId")) == source_id
            bounds = abs(float(decision["start"]) - start) <= GAP_MATCH_EPS_S \
                and abs(float(decision["end"]) - end) <= GAP_MATCH_EPS_S
        except (KeyError, TypeError, ValueError):
            continue
        if same and bounds:
            return index, decision
    return None


def _validate_decision(tag: str, decision: dict, gap_words: list[dict],
                       before: dict | None, after: dict | None,
                       errors: list[str]) -> None:
    kind = decision.get("kind")
    evidence = decision.get("evidence")
    if kind not in REMOVAL_KINDS:
        errors.append(f"{tag}: kind must be one of {sorted(REMOVAL_KINDS)}")
    if len(str(decision.get("rationale", "")).strip()) < 12:
        errors.append(f"{tag}: rationale must explain why the source span is removed")
    if not isinstance(evidence, dict):
        errors.append(
            f"{tag}: evidence must bind transcript beforeWord/afterWord/removedText")
        return
    if before and _norm(evidence.get("beforeWord")) != _norm(before["word"]):
        errors.append(f"{tag}: evidence.beforeWord does not match {before['word']!r}")
    if after and _norm(evidence.get("afterWord")) != _norm(after["word"]):
        errors.append(f"{tag}: evidence.afterWord does not match {after['word']!r}")
    actual = [token for word in gap_words for token in _norm(word["word"])]
    quoted = _norm(evidence.get("removedText", ""))
    if actual and not _contains_tokens(actual, quoted):
        errors.append(
            f"{tag}: evidence.removedText is not a verbatim removed transcript excerpt")
    if not actual and kind != "dead_air":
        errors.append(f"{tag}: word-free removal must be kind 'dead_air'")
    if actual and kind == "dead_air":
        errors.append(
            f"{tag}: dead_air cannot hide {len(gap_words)} removed transcript word(s)")


def _validate_removals(plan: dict, sources: dict[str, SourceEvidence],
                       ranges: dict[str, list[tuple]],
                       errors: list[str]) -> list[dict]:
    log = plan.get("cutDecisions")
    decisions = log.get("removals") if isinstance(log, dict) else None
    malformed = (not isinstance(log, dict) or log.get("schemaVersion") != 1
                 or not isinstance(decisions, list))
    if malformed:
        errors.append("cutDecisions must be {schemaVersion: 1, removals: [...]} "
                      "before visual planning")
        decisions = []
    used: set[int] = set()
    receipts: list[dict] = []
    for source_id, source_ranges in ranges.items():
        source = sources[source_id]
        for previous, current in zip(source_ranges, source_ranges[1:]):
            start, end = previous[1], current[0]
            if end - start < MIN_REMOVAL_S:
                continue
            match = _matching_decision(decisions, source_id, start, end)
            tag = f"removed gap {source_id}[{start:.3f},{end:.3f}]"
            if match is None:
                errors.append(
                    f"{tag}: missing cutDecisions.removals rationale/evidence")
                continue
            index, decision = match
            if index in used:
                errors.append(
                    f"cutDecisions.removals[{index}] covers more than one removed gap")
                continue
            used.add(index)
            claimed = [word for word in source.words
                       if word["start"] >= start - BOUNDARY_EPS_S
                       and word["end"] <= end + BOUNDARY_EPS_S]
            # A word the audio measures as silent throughout was never spoken there:
            # removing that span removes silence, not the word (which whisper mis-timed).
            gap_words = [word for word in claimed
                         if not source.measured_silent(word["start"], word["end"])]
            mistimed = len(claimed) - len(gap_words)
            before, _ = _neighbors(start, source.words)
            _, after = _neighbors(end, source.words)
            _validate_decision(f"cutDecisions.removals[{index}]", decision,
                               gap_words, before, after, errors)
            receipts.append({"sourceId": source_id, "start": round(start, 4),
                             "end": round(end, 4), "kind": decision.get("kind"),
                             "removedWords": len(gap_words),
                             **({"mistimedWordsInMeasuredSilence": mistimed} if mistimed else {})})
    for index in range(len(decisions)):
        if index not in used:
            errors.append(
                f"cutDecisions.removals[{index}] does not match an actual "
                "inter-cut gap")
    return receipts


def _check_previsual(plan: dict, errors: list[str]) -> None:
    populated = [key for key, value in plan.items()
                 if key not in PREVISUAL_KEYS
                 and value not in (None, False, "", [], {})]
    if populated:
        errors.append("previsual cut approval permits only planVersion, target, "
                      "cutTrack, and cutDecisions; populated downstream fields: "
                      + ", ".join(populated))


def _load_approval(path: str, errors: list[str]) -> dict | None:
    try:
        with open(path) as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"cut approval receipt unreadable: {exc}")
        return None
    if not isinstance(value, dict) or value.get("schemaVersion") != 1 \
            or value.get("stage") != "previsual":
        errors.append(
            "cut approval receipt must be a schemaVersion 1 previsual receipt")
        return None
    return value


def _check_approval(path: str, receipt: dict, errors: list[str]) -> None:
    approved = _load_approval(path, errors)
    if approved is None:
        return
    for key in ("manifestHash", "transcriptDigest", "cutTrackDigest",
                "cutDecisionsDigest"):
        if approved.get(key) != receipt.get(key):
            errors.append(f"cut approval {key} changed after previsual approval")
    receipt["approvalHash"] = file_hash(path)
    receipt["approvedPrevisualPlanHash"] = approved.get("planHash")


def check(plan_path: str, transcripts_dir: str, manifest_path: str,
          previsual: bool = False, approval_path: str | None = None) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        held_plan, held_manifest = load_cut_parent(plan_path), load_cut_parent(manifest_path)
        plan, manifest = held_plan.value, held_manifest.value
    except (OSError, RuntimeError, ValueError) as exc:
        return {"scope": "transcript_cut", "ok": False, "errors": [str(exc)],
                "warnings": [], "metrics": {}}
    if not plan.get("cutTrack"):
        errors.append("cutTrack is empty — transcript/cut approval cannot pass")
    if previsual:
        _check_previsual(plan, errors)
    used_ids = {str(cut.get("sourceId", "")) for cut in plan.get("cutTrack") or []}
    sources, transcript_files = source_evidence(
        manifest, manifest_path, transcripts_dir, used_ids, errors)
    seams, ranges = _validate_cuts(plan, sources, errors)
    removals = _validate_removals(plan, sources, ranges, errors)
    output_quality, quality_errors, quality_warnings = inspect_output(
        plan, sources, BOUNDARY_EPS_S)
    output_quality, quality_errors = consume_timing_reviews(
        ReviewInput(plan_path, manifest_path, transcripts_dir, plan, manifest, sources), output_quality, quality_errors)
    errors.extend(quality_errors)
    warnings.extend(quality_warnings)
    receipt = {
        "schemaVersion": 1, "stage": "previsual" if previsual else "planning_gate",
        "planHash": held_plan.sha256, "manifestHash": held_manifest.sha256,
        "transcriptDigest": stable_hash(transcript_files),
        "cutTrackDigest": stable_hash(plan.get("cutTrack") or []),
        "cutDecisionsDigest": stable_hash(plan.get("cutDecisions") or {}),
        "cuts": len(plan.get("cutTrack") or []), "seams": seams, "removals": removals,
        "outputQuality": output_quality,
        "audioEvidence": {source_id: {"gateDbfs": source.silence_gate_dbfs,
                                      "silenceSpans": len(source.silence)}
                          for source_id, source in sorted(sources.items())
                          if source.silence_gate_dbfs is not None},
    }
    if approval_path:
        _check_approval(approval_path, receipt, errors)
    recheck_cut_parents((held_plan, held_manifest), errors)
    return {"scope": "transcript_cut", "ok": not errors, "errors": errors,
            "warnings": warnings, "metrics": {"receipt": receipt}}


def main() -> int:
    parser = argparse.ArgumentParser(description="Transcript-first cut approval gate")
    for name in ("plan", "transcripts_dir", "manifest"):
        parser.add_argument(name)
    parser.add_argument("--previsual", action="store_true",
                        help="also require every visual/retention lane to be empty")
    parser.add_argument(
        "--approval", help="controller receipt; cut authority must match")
    args = parser.parse_args()
    if args.previsual and args.approval:
        parser.error("--previsual and --approval are mutually exclusive")
    verdict = check(args.plan, args.transcripts_dir, args.manifest,
                    args.previsual, args.approval)
    print(json.dumps(verdict, indent=2))
    return 0 if verdict["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Stable transcript and retake-detector authority for alternate takes."""
from __future__ import annotations

import os

import retake_scan
from edit.alternate_take_detector_closure import detector_tool_closure
from edit.alternate_take_types import (
    AlternateTakeAuthorityError,
    RetakeScanAuthority,
    ScanAuthorityInput,
)
from edit.cut_repair_context_sources import (
    digest,
    stable_json,
    to_sample,
)
from edit.exact_timing import TimingContractError
from edit.target_resolver import build_word_refs


def _canonical_path(path: str) -> None:
    if os.path.abspath(path) != path or os.path.realpath(path) != path \
            or os.path.islink(path):
        raise AlternateTakeAuthorityError(
            "alternate-take transcript path is not canonical")


def _stable_scan(path: str) -> tuple[dict, str, dict, list, dict]:
    _canonical_path(path)
    initial_closure = detector_tool_closure()
    document, transcript_hash = stable_json(
        path, "alternate-take transcript")
    report = retake_scan.analyze(path)
    utterances = retake_scan.load(path)
    reopened, reopened_hash = stable_json(
        path, "alternate-take transcript")
    closure = detector_tool_closure()
    if reopened_hash != transcript_hash or reopened != document:
        raise AlternateTakeAuthorityError(
            "alternate-take transcript changed during analysis")
    if closure != initial_closure:
        raise AlternateTakeAuthorityError(
            "alternate-take detector changed during analysis")
    return document, transcript_hash, report, utterances, closure


def released_retake_ids(path: str) -> list[int]:
    """Enumerate only deterministic later-wins events from a stable scan."""
    _, _, report, _, _ = _stable_scan(path)
    rows = report.get("retakes")
    if report.get("retakeDefault") != "later" \
            or not isinstance(rows, list):
        raise AlternateTakeAuthorityError(
            "retake report is malformed or has an unreleased default")
    identifiers = [
        row.get("id") for row in rows
        if isinstance(row, dict)
        and row.get("verdict") == "later-wins"
        and row.get("needsOperator") is False
        and row.get("longRange") is False
    ]
    if any(type(value) is not int or value < 0 for value in identifiers) \
            or len(set(identifiers)) != len(identifiers):
        raise AlternateTakeAuthorityError(
            "released retake identities are malformed or ambiguous")
    return sorted(identifiers)


def _word_range(row: dict) -> None:
    start = row["startSample"]
    end = row["endSampleExclusive"]
    if type(start) is not int or type(end) is not int \
            or start < 0 or end <= start:
        raise AlternateTakeAuthorityError(
            "retake transcript word range is malformed")


def _raw_rows(
    document: dict,
    rate: int,
) -> tuple[list[dict], list[tuple[int, int]]]:
    utterances = document.get("transcript")
    if not isinstance(utterances, list) or not utterances:
        raise AlternateTakeAuthorityError("retake transcript has no utterances")
    rows: list[dict] = []
    layout: list[tuple[int, int]] = []
    for index, utterance in enumerate(utterances):
        if not isinstance(utterance, dict) \
                or not isinstance(utterance.get("words"), list):
            raise AlternateTakeAuthorityError(
                f"retake transcript utterance {index} is malformed")
        first = len(rows)
        for word in utterance["words"]:
            if not isinstance(word, dict) \
                    or not isinstance(word.get("word"), str):
                raise AlternateTakeAuthorityError(
                    "retake transcript word is malformed")
            row = {
                "word": word["word"],
                "startSample": to_sample(word.get("start"), rate, "word start"),
                "endSampleExclusive":
                    to_sample(word.get("end"), rate, "word end"),
            }
            if utterance.get("speaker") is not None:
                row["speaker"] = str(utterance["speaker"])
            _word_range(row)
            rows.append(row)
        layout.append((first, len(rows)))
    return rows, layout


def _retake(report: dict, retake_id: int) -> dict:
    if type(retake_id) is not int or retake_id < 0:
        raise AlternateTakeAuthorityError("retake id is malformed")
    rows = report.get("retakes")
    if not isinstance(rows, list):
        raise AlternateTakeAuthorityError("retake report is malformed")
    matches = [row for row in rows
               if isinstance(row, dict) and row.get("id") == retake_id]
    if len(matches) != 1:
        raise AlternateTakeAuthorityError(
            "retake id does not resolve to one deterministic event")
    row = matches[0]
    if report.get("retakeDefault") != "later" \
            or row.get("verdict") != "later-wins" \
            or row.get("needsOperator") is not False \
            or row.get("longRange") is not False:
        raise AlternateTakeAuthorityError(
            "retake requires operator authority and cannot auto-select")
    return row


def _indexes(row: dict, utterances: list) -> tuple[list[int], list[int]]:
    earlier = row.get("loserIdxs")
    winners = row.get("winnerIdxs")
    if not isinstance(earlier, list) or not earlier \
            or not isinstance(winners, list) or not winners \
            or any(type(item) is not int for item in earlier + winners):
        raise AlternateTakeAuthorityError("retake candidate indexes are malformed")
    keep = row.get("keepStartS")
    later = [item for item in winners
             if 0 <= item < len(utterances)
             and round(utterances[item].start, 2) == keep]
    if len(later) != 1 or len(set(earlier)) != len(earlier):
        raise AlternateTakeAuthorityError(
            "retake winner is ambiguous on the source clock")
    if any(item < 0 or item >= len(utterances) for item in earlier):
        raise AlternateTakeAuthorityError("retake loser index is out of range")
    return sorted(earlier), later


def _policy_hash(report: dict, closure_hash: str) -> str:
    return digest({
        "schemaVersion": 1,
        "kind": "deterministic-retake-scan-policy-binding",
        "retakeDefault": report.get("retakeDefault"),
        "lookbackUtts": report.get("lookbackUtts"),
        "lookbackS": report.get("lookbackS"),
        "detectorToolClosureHash": closure_hash,
    })


def load_retake_scan_authority(value: ScanAuthorityInput) -> RetakeScanAuthority:
    """Run the detector between two stable transcript observations."""
    path = value.transcript_path
    document, transcript_hash, report, utterances, closure = _stable_scan(path)
    rows, layout = _raw_rows(document, value.sample_rate)
    transcript = value.context.get("transcript", {})
    timing = digest({
        "sourceId": value.source_id, "sampleRate": value.sample_rate,
        "transcriptSha256": transcript_hash, "words": rows,
    })
    if rows != transcript.get("words") or timing != value.timing_hash:
        raise AlternateTakeAuthorityError(
            "retake transcript does not match exact timing authority")
    refs = build_word_refs(value.source_id, rows, value.timing_hash)
    earlier, later = _indexes(_retake(report, value.retake_id), utterances)
    report_hash = digest(report)
    return RetakeScanAuthority(
        refs, layout, earlier, later, transcript_hash,
        closure, closure["closureHash"], report_hash,
        _policy_hash(report, closure["closureHash"]), value.retake_id)

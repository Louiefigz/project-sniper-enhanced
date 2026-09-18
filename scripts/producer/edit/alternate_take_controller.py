#!/usr/bin/env python3
"""Production controller for operation-bound alternate-take selection."""
from __future__ import annotations

import argparse
import json
import os

from edit.alternate_take_authority import (
    publish_alternate_take_selection,
)
from edit.alternate_take_derivation import (
    derive_alternate_take_candidate_set,
)
from edit.alternate_take_selection import (
    AlternateTakeDecision,
    released_selection_policy,
)
from edit.alternate_take_types import AlternateTakeAuthorityError
from edit.cut_repair_candidate_qc_contract import (
    load_candidate_authority,
    load_candidate_authority_base,
    reopen_candidate_context,
)
from edit.cut_repair_context_sources import (
    ContextMaterializationError,
    source_rows,
    stable_json,
)

_REQUEST_KEYS = {
    "schemaVersion", "kind", "visualSpeechRegion"}
_REGION_KEYS = {"xPpm", "yPpm", "widthPpm", "heightPpm"}


def _request(value: object) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != _REQUEST_KEYS \
            or value.get("schemaVersion") != 1 \
            or value.get("kind") != "cut-repair-alternate-take-request":
        raise AlternateTakeAuthorityError(
            "alternate-take controller request is malformed")
    region = value.get("visualSpeechRegion")
    if not isinstance(region, dict) or set(region) != _REGION_KEYS:
        raise AlternateTakeAuthorityError(
            "alternate-take visual speech region is absent")
    return value


def _transcript_path(
    manifest_path: str,
    source_id: str,
    expected_path: str,
    expected_hash: str,
) -> str:
    manifest, _ = stable_json(manifest_path, "alternate-take manifest")
    source = source_rows(manifest).get(source_id)
    if not isinstance(source, dict) \
            or source.get("path") != expected_path \
            or source.get("contentHash") != expected_hash:
        raise AlternateTakeAuthorityError(
            "manifest source does not match prepared source authority")
    requested = source.get("transcriptPath")
    if not isinstance(requested, str) or not requested:
        raise AlternateTakeAuthorityError(
            "prepared source has no transcript path")
    root = os.path.realpath(os.path.dirname(manifest_path))
    lexical = os.path.abspath(os.path.join(root, requested))
    resolved = os.path.realpath(lexical)
    if resolved != lexical or resolved == root \
            or os.path.commonpath([root, resolved]) != root:
        raise AlternateTakeAuthorityError(
            "alternate-take transcript escapes the manifest directory")
    return resolved


def _selected(candidate_set: dict) -> dict:
    rows = candidate_set.get("candidates")
    later = [
        row for row in rows if isinstance(row, dict)
        and row.get("role") == "later"
    ] if isinstance(rows, list) else []
    if len(later) != 1:
        raise AlternateTakeAuthorityError(
            "released alternate take is not uniquely selectable")
    return later[0]


def _not_applicable(preparation_hash: str) -> dict:
    return {
        "ok": True,
        "status": "not-applicable-audio-only",
        "preparationHash": preparation_hash,
    }


def run(
    producer: str,
    preparation_hash: str,
    manifest_path: str,
    request: dict | None,
) -> dict:
    """Derive, persist, and terminally reopen one picture selection."""
    authority = load_candidate_authority_base(producer, preparation_hash)
    parsed = _request(request)
    if not authority.picture_dirty:
        if parsed is not None:
            raise AlternateTakeAuthorityError(
                "audio-only repair cannot accept alternate-take input")
        return _not_applicable(preparation_hash)
    if parsed is None:
        raise AlternateTakeAuthorityError(
            "picture repair requires an explicit visual speech region")
    context = reopen_candidate_context(authority)
    transcript_path = _transcript_path(
        manifest_path, authority.source_id,
        authority.source_media_path, authority.source_media_sha256)
    candidate_set = derive_alternate_take_candidate_set(
        context, authority.operation, transcript_path)
    selected = _selected(candidate_set)
    receipt, receipt_hash, receipt_path = publish_alternate_take_selection(
        producer, preparation_hash, candidate_set,
        AlternateTakeDecision(
            selected["candidateId"], released_selection_policy(),
            parsed["visualSpeechRegion"]))
    reopened = load_candidate_authority(producer, preparation_hash)
    if reopened.alternate_take_selection != receipt \
            or reopened.alternate_take_selection_hash != receipt_hash \
            or reopened.alternate_take_selection_path != receipt_path:
        raise AlternateTakeAuthorityError(
            "published alternate-take selection failed terminal reobservation")
    return {
        "ok": True,
        "status": "selection-published",
        "preparationHash": preparation_hash,
        "selectionReceiptHash": receipt_hash,
        "selectionHash": receipt["selectionHash"],
        "selectionReceiptPath": receipt_path,
        "candidateSetHash": receipt["candidateSetHash"],
        "selectedCandidateId": receipt["selectedCandidateId"],
        "visualSpeechRegion": receipt["visualSpeechRegion"],
    }


def _request_file(path: str) -> dict | None:
    document, _ = stable_json(path, "alternate-take controller input")
    if set(document) != {"schemaVersion", "kind", "alternateTake"} \
            or document.get("schemaVersion") != 1 \
            or document.get("kind") != \
            "cut-repair-alternate-take-controller-input":
        raise AlternateTakeAuthorityError(
            "alternate-take controller input is malformed")
    return _request(document["alternateTake"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("producer_dir")
    parser.add_argument("preparation_hash")
    parser.add_argument("manifest_path")
    parser.add_argument("request_path")
    args = parser.parse_args()
    try:
        result = run(
            os.path.abspath(args.producer_dir),
            args.preparation_hash,
            os.path.abspath(args.manifest_path),
            _request_file(os.path.abspath(args.request_path)))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (
            AlternateTakeAuthorityError, ContextMaterializationError,
            KeyError, OSError, TypeError, ValueError,
    ) as exc:
        print(json.dumps({
            "ok": False, "status": "selection-blocked",
            "error": str(exc),
        }, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

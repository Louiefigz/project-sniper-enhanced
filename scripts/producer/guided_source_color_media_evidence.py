"""Separate original source-observation and base-consumption evidence publication.

Only actual same-process SourceColorBaseContext and OpeningPreparation returns
are used. This file is not selectable without the independently held schema2
worker completion, exact cleanup and separate cold replay. It claims no gamut
measurement, applied grade, perceptual quality, listening or human approval.
Original sources are not read or rehashed here; bounded generated artifacts
are checked against the existing preparation and actual master-seal returns.
"""
from __future__ import annotations

import hashlib
import json
import stat
from copy import deepcopy
from pathlib import Path

from cross_runtime_canonical_json import canonical_compact_json
from cut_manifestation_authority import MANIFESTATION_NAME
from cut_preview_io import MAX_JSON, bound_json, digest, read_bytes, write_new
from guided_opening_prepare import OpeningPreparation
from guided_body_execution import BodyHeldFile, _identity, _parent_paths, _directory_states
from guided_opening_result import held_ref
from guided_presenter_read_fingerprint import hold_read_metadata, same_read_metadata
from guided_source_color_base_context import SourceColorBaseContext, _opening
from guided_source_color_observation_projection import project_source_color_observations

EVIDENCE_NAME = "source-color-evidence.json"
EVIDENCE_SCOPE = "actual-source-observation-and-picture-consumption-not-color-or-quality-approval"


def _arguments(context: SourceColorBaseContext, prepared: OpeningPreparation, root: Path) -> tuple:
    """Capture original arguments and exact preparation refs before the first callback."""
    if type(context) is not SourceColorBaseContext or type(prepared) is not OpeningPreparation \
            or not isinstance(root, Path):
        raise RuntimeError("source-color media evidence requires the actual preparation context")
    SourceColorBaseContext.assert_metadata(context)
    owner = _opening(context)
    if str(root) != owner.context.opening.value["outputRoot"] \
            or prepared.base != root / "full-program-base/final.mp4":
        raise RuntimeError("source-color media evidence differs from original output ownership")
    return (id(context), id(prepared), str(prepared.base), id(prepared.evidence), prepared.evidence,
            id(prepared.selection), id(prepared.captions), str(root))


def _check(arguments: tuple, original: object) -> None:
    """Retain the same source lifetime, then close mutable preparation metadata and time."""
    context, prepared, root = arguments
    if not same_read_metadata(_arguments(context, prepared, root), original):
        raise RuntimeError("source-color media original preparation metadata changed")
    SourceColorBaseContext.assert_current(context)
    if not same_read_metadata(_arguments(context, prepared, root), original):
        raise RuntimeError("source-color media original preparation changed during callback")
    SourceColorBaseContext.assert_metadata(context)


def _generated(prepared: OpeningPreparation, consumed: dict, root: Path) -> tuple:
    """Retain original output stat/ancestry BEFORE their single existing byte-verification pass."""
    refs, base = prepared.evidence["receipts"], root / "full-program-base"
    publication = consumed["basePublication"]
    rows = ((prepared.evidence["base"], base / "final.mp4"),
            (refs["cutManifestation"], base / MANIFESTATION_NAME), (refs["timelineMap"], base / "timeline_map.json"))
    raw = canonical_compact_json(publication["receipt"]).encode("utf-8")
    published = {"path": publication["receiptPath"], "sha256": hashlib.sha256(raw).hexdigest()}
    location = Path(published["path"])
    if location.name != "master-receipt.json" or not location.is_relative_to(base):
        raise RuntimeError("source-color generated master artifact escaped original output role")
    held = []
    for row, path in (*rows, (published, location)):
        if row["path"] != str(path):
            raise RuntimeError("source-color generated artifact changed its original output role")
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RuntimeError("source-color generated artifact is not an original single-link file")
        held.append(BodyHeldFile(path, row["sha256"], _identity(info)))
    parents = _parent_paths(tuple(held))
    return tuple(held), parents, _directory_states(parents)


def _check_generated(original: tuple) -> None:
    """Close later callbacks without another full generated-video or source byte pass."""
    rows, parents, states = original
    if _directory_states(parents) != states \
            or any(_identity(row.path.lstat()) != row.identity for row in rows) \
            or _directory_states(parents) != states:
        raise RuntimeError("source-color generated artifact or ancestry changed after original byte check")


def _publication(consumed: dict, base: dict, root: Path) -> dict:
    """Bind the actual seal return, not a freshly selected source-float master pointer."""
    publication = consumed["basePublication"]
    record, location = publication["receipt"], Path(publication["receiptPath"])
    body = {key: value for key, value in record.items() if key != "receiptHash"}
    if record.get("kind") != "ordinary-source-float-master" or record.get("approved") is not False \
            or record.get("path") != base["path"] or record.get("sha256") != base["sha256"] \
            or not same_read_metadata(record.get("picture"), hold_read_metadata(consumed["pictureCopy"])) \
            or record.get("receiptHash") != digest(body):
        raise RuntimeError("source-color actual master publication differs from the prepared base")
    if location.name != "master-receipt.json" or not location.is_relative_to(root / "full-program-base"):
        raise RuntimeError("source-color actual master publication escaped original base ownership")
    raw = canonical_compact_json(record).encode("utf-8")
    if not 0 < len(raw) <= MAX_JSON or read_bytes(location) != raw:
        raise RuntimeError("source-color actual master-seal bytes changed")
    return {"path": str(location), "sha256": hashlib.sha256(raw).hexdigest(), "sizeBytes": len(raw)}


def _full_program(prepared: OpeningPreparation, consumed: dict, root: Path) -> dict:
    """Join original base/manifestation/timeline refs with completed encode occurrences."""
    evidence, base_dir = prepared.evidence, root / "full-program-base"
    base, refs = evidence["base"], evidence["receipts"]
    held_ref(base, root, prepared.base)
    manifestation_path = held_ref(refs["cutManifestation"], root, base_dir / MANIFESTATION_NAME)
    manifestation = bound_json(manifestation_path, refs["cutManifestation"]["sha256"])
    held_ref(refs["timelineMap"], root, base_dir / "timeline_map.json")
    if manifestation.get("receiptHash") != consumed["manifestation"]["receiptHash"] \
            or manifestation.get("timelineMapSha256") != refs["timelineMap"]["sha256"]:
        raise RuntimeError("source-color prepared base differs from actual cut manifestation")
    publication = _publication(consumed, base, root)
    return {"base": deepcopy(base), "cutManifestation": deepcopy(refs["cutManifestation"]),
            "timelineMap": deepcopy(refs["timelineMap"]), "sourceFloatMaster": publication}


def write_source_color_media_evidence(context: SourceColorBaseContext, prepared: OpeningPreparation,
                                     root: Path) -> dict:
    """Write one new unapproved section, returning exact raw and semantic receipt refs."""
    arguments = context, prepared, root
    original = hold_read_metadata(_arguments(*arguments))
    _check(arguments, original)
    observations = project_source_color_observations(context)
    consumed = SourceColorBaseContext.consumption_record(context)
    generated = _generated(prepared, consumed, root)
    body = {"schemaVersion": 1, "kind": "guided-opening-source-color-media-evidence", "scope": EVIDENCE_SCOPE,
            "observations": observations, "pictureConsumption": consumed,
            "fullProgram": _full_program(prepared, consumed, root), "gamutMeasured": False,
            "gradeApplied": False, "colorQualified": False, "openingApproved": False, "deliveryApproved": False}
    receipt_hash = digest(body)
    record = {**body, "receiptHash": receipt_hash}
    raw = (canonical_compact_json(record) + "\n").encode("utf-8")
    if not 0 < len(raw) <= MAX_JSON:
        raise RuntimeError("source-color media evidence exceeds its16MiB bound")
    _check(arguments, original)
    _check_generated(generated)
    location = root / EVIDENCE_NAME
    write_new(location, record)
    if read_bytes(location) != raw:
        raise RuntimeError("source-color media evidence publication bytes changed")
    _check(arguments, original)
    _check_generated(generated)
    if read_bytes(location) != raw:
        raise RuntimeError("source-color media evidence changed during final callback")
    SourceColorBaseContext.assert_metadata(context)
    _check_generated(generated)
    return {"path": str(location), "sha256": hashlib.sha256(raw).hexdigest(),
            "sizeBytes": len(raw), "receiptHash": receipt_hash}


def verify_source_color_media_evidence(context: SourceColorBaseContext, reference: dict) -> None:
    """Recheck the actual returned section bytes; this is not independent cold qualification."""
    original = hold_read_metadata(reference)
    SourceColorBaseContext.assert_current(context)
    location = Path(_opening(context).context.opening.value["outputRoot"]) / EVIDENCE_NAME
    if set(reference) != {"path", "sha256", "sizeBytes", "receiptHash"} or reference["path"] != str(location):
        raise RuntimeError("source-color media evidence reference changed its original output role")
    raw = read_bytes(location)
    if type(reference["sizeBytes"]) is not int or len(raw) != reference["sizeBytes"] \
            or hashlib.sha256(raw).hexdigest() != reference["sha256"]:
        raise RuntimeError("source-color media evidence differs from its original publication")
    record = json.loads(raw)
    if type(record) is not dict or record.get("receiptHash") != reference["receiptHash"] \
            or digest({key: value for key, value in record.items() if key != "receiptHash"}) != reference["receiptHash"]:
        raise RuntimeError("source-color media evidence semantic reference changed")
    SourceColorBaseContext.assert_current(context)
    if not same_read_metadata(reference, original) or read_bytes(location) != raw:
        raise RuntimeError("source-color media evidence changed during original callback")
    SourceColorBaseContext.assert_metadata(context)

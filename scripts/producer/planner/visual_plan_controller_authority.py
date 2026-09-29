"""Controller-owned transcript and prior-usage authority for visual plans."""
from __future__ import annotations

import hashlib
import json
import os
import stat

from planner.visual_plan_fields import (
    VisualPlanContractError, canonical_hash, id_field, object_field, path_field,
    sha_field, text_field,
)
from planner.visual_plan_related_usage import validate_related_use
from planner.visual_plan_media_authority import validate_media_document

MAX_AUTHORITY_BYTES = 64 * 1024 * 1024
MAX_WORDS = 200_000
MAX_USES = 128


def validate_authority_pin(value: object, name: str) -> dict:
    """Validate one controller authority pin envelope."""
    pin = object_field(value, name, {"schemaVersion", "path", "sha256", "digest"}, set())
    if pin["schemaVersion"] != 1:
        raise VisualPlanContractError(f"{name} schema version is unsupported")
    path_field(pin["path"], f"{name} path")
    sha_field(pin["sha256"], f"{name} sha256")
    sha_field(pin["digest"], f"{name} digest")
    return pin


def _read_exact_pin(pin: dict, name: str) -> dict:
    """Read a bounded no-follow authority once and bind that exact byte buffer."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = None
    try:
        descriptor = os.open(pin["path"], flags)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 \
                or not 2 <= before.st_size <= MAX_AUTHORITY_BYTES:
            raise VisualPlanContractError(f"{name} must be one bounded single-link file")
        chunks, remaining = [], before.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise VisualPlanContractError(f"{name} changed during its bounded read")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
    except OSError as exc:
        raise VisualPlanContractError(f"{name} is unavailable") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns,
                             item.st_ctime_ns, item.st_nlink)
    if identity(before) != identity(after):
        raise VisualPlanContractError(f"{name} changed during its bounded read")
    data = b"".join(chunks)
    if hashlib.sha256(data).hexdigest() != pin["sha256"]:
        raise VisualPlanContractError(f"{name} SHA-256 differs from its controller pin")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise VisualPlanContractError(f"{name} is not valid UTF-8 JSON") from exc
    return object_field(value, name, set(value) if isinstance(value, dict) else set(), set())


def _bound_document(pin: dict, name: str, keys: set[str]) -> dict:
    value = _read_exact_pin(pin, name)
    document = object_field(value, name, keys | {"digest"}, set())
    digest = document["digest"]
    sha_field(digest, f"{name} document digest")
    core = {key: document[key] for key in keys}
    if canonical_hash(core) != digest or pin["digest"] != digest:
        raise VisualPlanContractError(f"{name} digest differs from its controller content")
    return document


def _authority_word(value: object, ordinal: int, duration: int) -> dict:
    keys = {"id", "ordinal", "text", "sourceId", "segmentIndex", "sourceWordIndex",
            "sourceStartFrame", "sourceEndFrameExclusive", "outputStartFrame",
            "outputEndFrameExclusive"}
    row = object_field(value, f"transcript authority word {ordinal}", keys, set())
    id_field(row["id"], f"transcript authority word {ordinal} id")
    id_field(row["sourceId"], f"transcript authority word {ordinal} sourceId")
    text_field(row["text"], f"transcript authority word {ordinal} text")
    integer_keys = keys - {"id", "text", "sourceId"}
    if any(type(row[key]) is not int or row[key] < 0 for key in integer_keys):
        raise VisualPlanContractError("transcript authority word timing must be nonnegative integers")
    if row["ordinal"] != ordinal or row["sourceEndFrameExclusive"] <= row["sourceStartFrame"] \
            or row["outputEndFrameExclusive"] <= row["outputStartFrame"] \
            or row["outputEndFrameExclusive"] > duration:
        raise VisualPlanContractError("transcript authority word timing or ordinal is invalid")
    return row


def _transcript_words(plan: dict) -> dict[str, dict]:
    pin = validate_authority_pin(plan["transcriptAuthority"], "transcriptAuthority")
    keys = {"schemaVersion", "kind", "project", "wordCount", "words"}
    document = _bound_document(pin, "transcript authority", keys)
    project = object_field(document["project"], "transcript authority project",
                           {"acceptedProgramSha256", "transcriptSha256", "durationFrames", "fps"}, set())
    expected = {key: plan["project"][key] for key in project}
    if document["schemaVersion"] != 1 or document["kind"] != "visual-plan-transcript-authority" \
            or project != expected:
        raise VisualPlanContractError("transcript authority differs from the accepted program")
    words = document["words"]
    if not isinstance(words, list) or not 1 <= len(words) <= MAX_WORDS \
            or document["wordCount"] != len(words):
        raise VisualPlanContractError("transcript authority word count is invalid")
    rows = [_authority_word(item, index, project["durationFrames"])
            for index, item in enumerate(words)]
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise VisualPlanContractError("transcript authority word IDs must be unique")
    if any(left["outputStartFrame"] > right["outputStartFrame"]
           for left, right in zip(rows, rows[1:])):
        raise VisualPlanContractError("transcript authority words are out of program order")
    return {row["id"]: row for row in rows}


def _validate_transcript_evidence(opportunities: list[dict], words: dict[str, dict]) -> None:
    for opportunity in opportunities:
        evidence = opportunity["transcriptEvidence"]
        try:
            selected = [words[word_id] for word_id in evidence["wordIds"]]
        except KeyError as exc:
            raise VisualPlanContractError(
                f"opportunity {opportunity['id']} names a fabricated transcript word ID") from exc
        if [row["ordinal"] for row in selected] != sorted(row["ordinal"] for row in selected):
            raise VisualPlanContractError(
                f"opportunity {opportunity['id']} transcript word IDs are out of order")
        expected_text = " ".join(row["text"] for row in selected)
        if evidence["text"] != expected_text:
            raise VisualPlanContractError(
                f"opportunity {opportunity['id']} transcript text differs from its word IDs")
        timing = opportunity["timing"]
        if any(row["outputStartFrame"] >= timing["endFrameExclusive"]
               or row["outputEndFrameExclusive"] <= timing["startFrame"] for row in selected):
            raise VisualPlanContractError(
                f"opportunity {opportunity['id']} transcript evidence is outside its timing")


def _related_use(value: object, name: str) -> dict:
    return validate_related_use(value, name)


def _usage_project(value: object, index: int) -> dict:
    keys = {"projectId", "approvedAt", "planSha256", "applicationSha256",
            "packetSha256", "uses"}
    row = object_field(value, f"related usage project {index}", keys, set())
    id_field(row["projectId"], f"related usage project {index} projectId")
    text_field(row["approvedAt"], f"related usage project {index} approvedAt")
    for key in ("planSha256", "applicationSha256", "packetSha256"):
        sha_field(row[key], f"related usage project {index} {key}")
    if not isinstance(row["uses"], list):
        raise VisualPlanContractError("related usage project uses must be an array")
    row["uses"] = [_related_use(item, f"related usage project {index} use {use_index}")
                   for use_index, item in enumerate(row["uses"])]
    if any(item["planSha256"] != row["planSha256"] for item in row["uses"]):
        raise VisualPlanContractError("related usage project use names another plan")
    return row


def _validate_related_authority(plan: dict) -> None:
    pin = validate_authority_pin(plan["relatedUsageAuthority"], "relatedUsageAuthority")
    keys = {"schemaVersion", "kind", "mode", "windowProjects", "source",
            "projectCount", "projects", "relatedUsage"}
    document = _bound_document(pin, "related usage authority", keys)
    projects = document["projects"]
    if not isinstance(projects, list) or len(projects) > 8:
        raise VisualPlanContractError("related usage authority projects exceed the window")
    rows = [_usage_project(value, index) for index, value in enumerate(projects)]
    uses = document["relatedUsage"]
    if not isinstance(uses, list) or len(uses) > MAX_USES:
        raise VisualPlanContractError("related usage authority uses exceed the bound")
    validated = [_related_use(value, f"related usage authority use {index}")
                 for index, value in enumerate(uses)]
    expected = [use for project in rows for use in project["uses"]][:MAX_USES]
    empty = document["source"] == "explicit-empty-controller-ledger"
    if document["schemaVersion"] != 1 or document["kind"] != "visual-plan-related-usage-authority" \
            or document["mode"] != plan["project"]["mode"] or document["windowProjects"] != 8 \
            or document["projectCount"] != len(rows) or validated != expected \
            or empty != (not rows) or document["source"] not in {
                "validated-approved-projects", "validated-current-projects",
                "explicit-empty-controller-ledger"}:
        raise VisualPlanContractError("related usage authority is inconsistent")
    if plan["relatedUsage"] != validated:
        raise VisualPlanContractError("relatedUsage differs from its controller ledger")


def _media_inventory(plan: dict) -> dict:
    pin = validate_authority_pin(plan["mediaAuthority"], "mediaAuthority")
    keys = {"schemaVersion", "kind", "project", "manifest",
            "sourceSetAdmission", "inventoryCount", "inventory"}
    document = _bound_document(pin, "media authority", keys)
    return validate_media_document(plan, document)


def validate_controller_authorities(plan: dict,
                                    opportunities: list[dict]) -> dict:
    """Fail closed unless transcript evidence and prior usage match controller files."""
    words = _transcript_words(plan)
    _validate_transcript_evidence(opportunities, words)
    _validate_related_authority(plan)
    return _media_inventory(plan)

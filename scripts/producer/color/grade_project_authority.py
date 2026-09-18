"""Derive original-source expectations from current admitted project bytes.

Ingest's declaredFrames and the manifest's exact frameRate are EXPECTATIONS,
not proof of complete decoded metadata or CFR. The isolated full-source worker
and streamed record validator must independently match both; no duration math,
proxy selection, source repair or metadata inference is permitted here.
"""
from __future__ import annotations

from pathlib import Path

from color.grade_contract import parse_source_binding
from color.grade_observation_profile import V1, V2, admitted_facts, observation_declaration, project_profile
from cut_preview_io import bound_json, digest, file_hash, real_directory
from graphics.render_rate import normalize_render_rate
from ingest_execution_authority import execution_media_authority_entries

def _selected_source(value: dict, plan: dict, manifest: dict, entries: list[dict]) -> tuple[dict, dict]:
    """Select one current retained source, never a body-supplied filesystem path."""
    source_id = value["sourceId"]
    cuts = plan.get("cutTrack")
    if type(cuts) is not list or not any(type(row) is dict and row.get("sourceId") == source_id for row in cuts):
        raise RuntimeError("full-source observation requires this source in the saved cut")
    sources = manifest.get("sources")
    if type(sources) is not list:
        raise RuntimeError("full-source observation has no source manifest")
    matches = [row for row in sources if type(row) is dict and row.get("id") == source_id]
    if len(matches) != 1:
        raise RuntimeError("full-source observation source identity is missing or duplicated")
    source = matches[0]
    admitted = [row for row in entries if row["lane"] == "source"
                and row["originalPath"] == source.get("originalPath")]
    if len(admitted) != 1 or admitted[0]["snapshotPath"] != source.get("path"):
        raise RuntimeError("full-source observation requires the original admitted snapshot")
    if source.get("vfr") is not False or type(source.get("frameRate")) is not str:
        raise RuntimeError("full-source observation needs a declared exact-rate non-VFR candidate")
    return source, admitted[0]


def _candidate_count(receipt: dict) -> int:
    """Retain a bounded ingest expectation; never upgrade its estimation policy."""
    facts = receipt.get("decoded", {}).get("facts", {})
    count = facts.get("declaredFrames")
    if facts.get("mediaKind") != "timed-media" or type(facts.get("videoStreams")) is not int \
            or facts["videoStreams"] != 1 or type(count) is not int or not 1 <= count <= 1_296_000:
        raise RuntimeError("full-source observation needs one bounded video/count candidate")
    return count


def _cheap_candidate(value: dict, manifest: dict, producer: Path) -> None:
    """Metadata rejection only; never substitute this for source-set verification."""
    profile = project_profile(value)
    sources = manifest.get("sources")
    if type(sources) is not list:
        raise RuntimeError("full-source observation has no source manifest")
    rows = [row for row in sources if type(row) is dict and row.get("id") == value["sourceId"]]
    if len(rows) != 1 and profile is V1:
        return  # Preserve legacy authority/rejection ordering below.
    if len(rows) != 1:
        raise RuntimeError("full-source observation source identity is missing or duplicated")
    row = rows[0]
    if type(row.get("sourceSizeBytes")) is int and row["sourceSizeBytes"] > profile.max_source_bytes:
        raise ValueError("grade observation source exceeds selected byte class")
    if profile is not V2:
        return
    raw = row.get("admissionReceiptPath")
    if type(raw) is not str or not raw.startswith(".sniper-external-media/receipts/") \
            or str(Path(raw)) != raw or ".." in Path(raw).parts or "\\" in raw:
        raise ValueError("v2 observation candidate receipt path is invalid")
    receipt = bound_json(producer / raw, row.get("admissionReceiptSha256"))
    admitted_facts(receipt.get("decoded", {}).get("facts", {}), profile)


def observe_project(value: dict) -> dict:
    """Reverify all source-set projections and exact private declaration parents."""
    producer = Path(value["producerDir"])
    real_directory(producer)
    expected = value["expected"]
    plan = bound_json(producer / "edit_plan.json", expected["planSha256"])
    manifest_path = producer / "asset_manifest.json"
    manifest = bound_json(manifest_path, expected["manifestSha256"])
    project_path = producer.parent / "project.json"
    project = bound_json(project_path, expected["projectSha256"])
    _cheap_candidate(value, manifest, producer)
    entries = execution_media_authority_entries(plan, manifest, str(manifest_path))
    if not entries:
        raise RuntimeError("full-source observation requires current source-set admission")
    source, entry = _selected_source(value, plan, manifest, entries)
    receipt = bound_json(producer / entry["admissionReceiptPath"], entry["admissionReceiptSha256"])
    profile = project_profile(value)
    if profile is V2:
        admitted_facts(receipt.get("decoded", {}).get("facts", {}), profile)
    observed_hash = file_hash(Path(entry["snapshotPath"]), profile.max_source_bytes)
    if observed_hash != entry["sha256"]:
        raise RuntimeError("full-source observation source bytes differ from admission")
    declaration = value["declaration"]
    history = {"projectSha256": expected["projectSha256"], "history": project.get("history", [])}
    binding = {"sourceId": value["sourceId"], "sourceSha256": observed_hash,
        "admissionReceiptSha256": entry["admissionReceiptSha256"],
        "declarationSha256": digest(declaration), "projectHistorySha256": digest(history),
        "fps": normalize_render_rate(source["frameRate"]).token,
        "frameCount": _candidate_count(receipt)}
    observation_declaration(declaration, parse_source_binding(binding), profile)
    return {"binding": binding, "declaration": declaration, "sourcePath": entry["snapshotPath"],
        "sourceSetAdmission": manifest["sourceSetAdmission"], "sourceManifestRow": source,
        "expectedParents": expected, "projectHistory": history,
        "clockCaveat": "Ingest declaredFrames/exact manifest frameRate are candidates until full original EOF/metadata/cadence replay matches."}

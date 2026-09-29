"""Observe, fully re-validate and bind sealed shared evidence; the same check a submission can repeat.

A sealed record is trusted for nothing it stores: binding re-observes the manifest, transcripts and
every bound file, re-runs the complete authored-field validation, and refuses a record that was
edited, moved or copied away from its recorded path, superseded by a later version beside it, or
that describes another source or manifest than the subject. `evidence_check` is the public re-check
(context.py --evidence-check) the typed submission step calls before accepting a review that relied
on the evidence. Given titles and scripts are not part of it (role_packet_given).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from role_packet_evidence_schema import AUTHORED, EvidenceError, authored_fields
from role_packet_files import artifact, canonical_file, read_json
from role_packet_transcript import Transcript, observe_transcript

PREFIX = "SHARED-EVIDENCE"
KIND = "sniper-shared-source-evidence"
SOURCE_FIELDS = ("id", "path", "sourceSha256", "sourceSizeBytes", "duration", "frameRate", "resolution", "audio",
                 "transcriptPath")
KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
RECORD_KEYS = {"schemaVersion", "kind", "version", "recordPath", "sealedAt", "draft", "manifest", "sources",
               "transcripts", "bound", *AUTHORED, "engineLimits", "contentSha256"}
OWNER_MANIFESTS = ("source/asset_manifest.json", "asset_manifest.json", "producer/asset_manifest.json")
ENGINE_LIMITS = (
    "Source identity and file hashes were observed by the engine; every other field was authored and is a claim a "
    "critic may check and dispute.",
    "This record is shared input for authors and critics, never a review, verdict or approval.",
)


def plain(row: dict) -> dict:
    """The identity fields of an observed file."""
    return {key: row[key] for key in ("key", "path", "sha256", "bytes")}


def source_identity(manifest: dict) -> tuple[list[dict], list[dict]]:
    """Each admitted source's identity plus its transcript file, from the observed manifest."""
    sources = read_json(manifest["path"]).get("sources")
    if not isinstance(sources, list) or not sources:
        raise EvidenceError(f"{manifest['path']} lists no admitted sources")
    identity, transcripts = [], []
    for row in sources:
        if not isinstance(row, dict) or not isinstance(row.get("sourceSha256"), str) or not isinstance(row.get("id"), str):
            raise EvidenceError(f"{manifest['path']}: every source needs an id and an admitted sourceSha256")
        identity.append({key: row.get(key) for key in SOURCE_FIELDS})
        if isinstance(row.get("transcriptPath"), str):
            file = Path(manifest["path"]).parent / row["transcriptPath"]
            transcripts.append(plain(artifact(f"transcript:{row['id']}", file, "Admitted transcript.")))
    return identity, transcripts


def bound_files(values: tuple[str, ...] | list[dict]) -> list[dict]:
    """KEY=PATH arguments (or earlier rows) observed now; keys are unique simple names."""
    rows = []
    for value in values:
        key, _sep, path = value.partition("=") if isinstance(value, str) else (value.get("key", ""), "=", value.get("path"))
        if not isinstance(key, str) or not KEY.fullmatch(key) or not path:
            raise EvidenceError(f"--bind needs KEY=PATH with a simple key, got {value!r}")
        rows.append(plain(artifact(key, path, "Bound by the shared-evidence author.")))
    if len({row["key"] for row in rows}) != len(rows):
        raise EvidenceError("--bind keys must be unique")
    return rows


def observed_inputs(manifest_path: str, bindings: tuple[str, ...] | list[dict]) -> dict:
    """Manifest, sources, transcripts and bound files as the engine observes them now."""
    manifest = plain(artifact("manifest", manifest_path, "Admitted source manifest."))
    sources, transcripts = source_identity(manifest)
    return {"manifest": manifest, "sources": sources, "transcripts": transcripts, "bound": bound_files(bindings)}


def changed_inputs(previous: dict, current: dict) -> list[str]:
    """Every identity that differs between two observations of the same inputs."""
    changes = [] if previous.get("manifest") == current["manifest"] else [f"manifest {current['manifest']['path']}"]
    changes += [] if previous.get("sources") == current["sources"] else ["admitted source identity"]
    for name in ("transcripts", "bound"):
        before = {row.get("key"): row for row in previous.get(name) or [] if isinstance(row, dict)}
        changes += [f"{row['key']} {row['path']}" for row in current[name] if before.get(row["key"]) != row]
        changes += [f"{key} (no longer observed)" for key in set(before) - {row["key"] for row in current[name]}]
    return changes


def content_digest(record: dict) -> str:
    """Canonical digest of the record without its own digest field."""
    body = {key: value for key, value in record.items() if key != "contentSha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def source_transcript(current: dict, source_id: str) -> tuple[dict, Transcript]:
    """An admitted source row and its observed transcript."""
    source = next((row for row in current["sources"] if row["id"] == source_id), None)
    if source is None or not isinstance(source.get("transcriptPath"), str):
        raise EvidenceError(f"admitted source {source_id!r} has no transcript to cut a given script from")
    if not isinstance(source.get("duration"), (int, float)):
        raise EvidenceError(f"admitted source {source_id!r} has no duration to bound its transcript words")
    path = str(Path(current["manifest"]["path"]).parent / source["transcriptPath"])
    return source, observe_transcript(path, source["duration"])


def located(row: dict, record: dict) -> None:
    """The record sits at its recorded path under its version name, unedited and not superseded."""
    path = Path(row["path"])
    if record.get("schemaVersion") != 1 or record.get("kind") != KIND or set(record) != RECORD_KEYS:
        raise EvidenceError(f"{path} is not a sealed shared-evidence record")
    if record["recordPath"] != str(path) or path.name != f"{PREFIX}-v{record['version']}.json":
        raise EvidenceError(f"{path} is not at its recorded path {record['recordPath']}: a moved or copied record is refused")
    if record["contentSha256"] != content_digest(record):
        raise EvidenceError(f"{path} was edited after sealing (content digest mismatch); seal a new version")
    later = sorted(item.name for item in path.parent.iterdir()
                   if (match := re.fullmatch(rf"{PREFIX}-v(\d+)\.json", item.name)) and int(match.group(1)) > record["version"])
    if later:
        raise EvidenceError(f"{path} is superseded by {later}; bind the current version")


def verified_record(record_file: str) -> tuple[dict, dict, dict]:
    """(file row, record, fresh observations) after every check."""
    row = artifact("shared-evidence", record_file, "Sealed shared source/reference evidence for this production.")
    record = read_json(row["path"])
    located(row, record)
    current = observed_inputs(record["manifest"]["path"], record["bound"])
    changes = changed_inputs(record, current)
    if changes:
        raise EvidenceError(f"stale shared evidence {row['path']}: {changes[:8]} changed since sealing; seal a new version")
    if authored_fields(record, current) != {key: record[key] for key in AUTHORED}:
        raise EvidenceError(f"{row['path']}: authored fields differ from their validated form")
    return row, record, current


def evidence_check(record_file: str) -> dict:
    """Public re-check for the submission step: the record's identity when it is still current."""
    row, record, _current = verified_record(record_file)
    return {"status": "shared-evidence-current", "path": row["path"], "sha256": row["sha256"],
            "version": record["version"], "contentSha256": record["contentSha256"]}


def same_production(record: dict, source: str | None, manifest_sha: str | None) -> None:
    """The evidence must describe the subject's source recording and, when it binds one, its manifest."""
    described = {row["sourceSha256"] for row in record["sources"]}
    if source not in described:
        raise EvidenceError(f"shared evidence describes sources {sorted(described)}, not this plan's source {source}")
    if manifest_sha is not None and manifest_sha != record["manifest"]["sha256"]:
        raise EvidenceError("shared evidence binds a different admitted manifest than this plan's request packet")


def owner_production(record: dict, project: str | None) -> None:
    """Without a plan, an owner's --project folder must hold the same admitted manifest the evidence describes."""
    found = [Path(project) / name for name in OWNER_MANIFESTS if project and (Path(project) / name).is_file()]
    if not found:
        raise EvidenceError("cannot establish that this shared evidence describes the project: pass --plan or "
                            "--native-project, or a --project holding its admitted asset_manifest.json")
    if hashlib.sha256(canonical_file(found[0]).read_bytes()).hexdigest() != record["manifest"]["sha256"]:
        raise EvidenceError(f"{found[0]} is not the admitted manifest this shared evidence describes")


def evidence_summary(row: dict, record: dict, authors: list[str], checked: bool) -> dict:
    """What the packet tells its reader about the bound evidence (the record itself stays authoritative)."""
    return {"path": row["path"], "sha256": row["sha256"], "version": record["version"],
            "contentSha256": record["contentSha256"], "sealedAt": record["sealedAt"], "author": record["author"],
            "authoredByRecordedAuthor": record["author"]["sessionId"] in authors, "checkedAgainstPlan": checked,
            "engineObserved": {"manifest": record["manifest"]["sha256"],
                               "sources": [{key: item[key] for key in ("id", "sourceSha256", "duration")}
                                           for item in record["sources"]],
                               "transcripts": {item["key"]: item["sha256"] for item in record["transcripts"]}},
            "authoredClaims": {"sourceScanFacts": len(record["sourceScan"]["facts"]),
                               "people": len(record["speakers"]["people"]),
                               "intervals": len(record["speakers"]["intervals"]),
                               "listening": record["speakers"]["listening"], "reference": record["reference"] is not None,
                               "decisions": [item["topic"] for item in record["decisions"]]},
            "limits": [*record["speakers"]["limits"], *record["sourceScan"]["limits"], *record["limits"]]}


def bind_evidence(record_file: str, subject: dict, authors: list[str]) -> dict:
    """{artifacts, summary} for one packet; `subject` names the plan's source and manifest, or an owner's project."""
    row, record, current = verified_record(record_file)
    if subject.get("plan"):
        same_production(record, subject["source"], subject["manifest"])
    else:
        owner_production(record, subject.get("project"))
    files = [current["manifest"], *current["transcripts"], *current["bound"]]
    artifacts = [row, *({**item, "key": f"shared-evidence:{item['key']}", "observation": "strict",
                         "why": "Bound by the shared evidence; hash re-verified at resolution and at submission."}
                        for item in files)]
    return {"artifacts": artifacts, "summary": evidence_summary(row, record, authors, bool(subject.get("plan")))}

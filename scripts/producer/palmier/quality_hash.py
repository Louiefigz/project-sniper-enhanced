"""Python counterpart of the TypeScript managed-quality authority snapshot."""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from cross_runtime_canonical_json import canonical_compact_json
from fingerprints import file_sha256, plan_content_hash

SCHEMA_VERSION = 1
QUALITY_VERSION = 1
_PIPELINE_EXTENSIONS = (".py", ".ts", ".tsx", ".js", ".json", ".html",
                        ".css", ".md", ".svg", ".png", ".jpg", ".jpeg")
_EXCLUDED_PARTS = {"__pycache__", "__tests__", "node_modules", "renders",
                   "cache", "tests", "docs", "study", "artifacts",
                   ".sniper-native-runtime"}
_EXCLUDED_MEDIA = (".mov", ".mp4", ".wav", ".mp3", ".pyc")


def stable_hash(value: object) -> str:
    """Match stableAuthorityHash: sorted objects and compact JSON.stringify."""
    blob = canonical_compact_json(value)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def request_key(ctx: dict) -> str:
    """Match autoEditRequestKey for the persisted managed context."""
    request = {key: value for key, value in ctx.items()
               if key not in ("doctrine", "pipeline", "templateUsage",
                              "brainSessionId",
                              "brainSessionEstablished")}
    if request.get("deliveryPolicy") == "palmier-hybrid":
        request.pop("deliveryPolicy")
    return stable_hash(request)


def _hash_or_none(path: str) -> str | None:
    try:
        return file_sha256(path)
    except OSError:
        return None


def _logical_file(path: str, base: str) -> dict:
    relative = os.path.relpath(path, base)
    logical = (relative if relative and relative != "."
               and not relative.startswith("..") else os.path.basename(path))
    return {"path": logical.replace(os.sep, "/"), "hash": _hash_or_none(path)}


def _json_value(path: str) -> Any:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def _stored_intent(ctx: dict) -> Any:
    project = _json_value(os.path.join(os.path.dirname(ctx["dir"]), "project.json"))
    return project.get("intent") if isinstance(project, dict) else None


def _transcript_files(ctx: dict) -> list[dict]:
    manifest = _json_value(ctx["manifestPath"])
    sources = manifest.get("sources") if isinstance(manifest, dict) else None
    if not isinstance(sources, list):
        return []
    result = []
    for index, source in enumerate(sources):
        transcript = source.get("transcriptPath") if isinstance(source, dict) else None
        if not isinstance(transcript, str) or not transcript:
            result.append({"path": f"source-{index + 1}:missing-transcript",
                           "hash": None})
            continue
        path = (transcript if os.path.isabs(transcript) else
                os.path.join(os.path.dirname(ctx["manifestPath"]), transcript))
        result.append(_logical_file(path, ctx["transcriptsDir"]))
    return result


def _reference_files(ctx: dict) -> list[dict]:
    study = ctx.get("referenceStudy")
    if not isinstance(study, dict):
        return []
    study_output = os.path.dirname(study["deepStudyPath"])
    candidates = [study["profilePath"], study["deepStudyPath"],
                  *(study.get("representativeFrames") or []),
                  os.path.join(study_output, "reference.json"),
                  os.path.join(study_output, "fingerprint.json"),
                  os.path.join(study["dir"], "reference-source.json")]
    unique = list(dict.fromkeys(candidates))
    return [_logical_file(path, study["dir"]) for path in unique]


def _repository_root() -> str:
    for start in (os.getcwd(), os.path.dirname(os.path.dirname(__file__))):
        current = os.path.abspath(start)
        while True:
            if os.path.isdir(os.path.join(current, "scripts", "producer")):
                return current
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
    return os.getcwd()


def _pipeline_allowed(root: str, path: str) -> bool:
    relative = os.path.relpath(path, root)
    parts = relative.split(os.sep)
    if any(part in _EXCLUDED_PARTS for part in parts):
        return False
    lower = relative.lower()
    return (not lower.endswith(_EXCLUDED_MEDIA)
            and lower.endswith(_PIPELINE_EXTENSIONS))


def _walk(root: str, item: str) -> list[str]:
    if not os.path.lexists(item) or os.path.islink(item):
        return []
    if os.path.isfile(item):
        return [item] if _pipeline_allowed(root, item) else []
    if not os.path.isdir(item):
        return []
    relative = os.path.relpath(item, root)
    if any(part in _EXCLUDED_PARTS for part in relative.split(os.sep)):
        return []
    paths = []
    for name in sorted(os.listdir(item)):
        paths.extend(_walk(root, os.path.join(item, name)))
    return paths


def _live_pipeline_files() -> list[dict]:
    root = _repository_root()
    roots = [os.path.join(root, "scripts", "producer"),
             os.path.join(root, "templates", "motion"),
             os.path.join(root, ".agents", "skills", "producer", "SKILL.md"),
             os.path.join(root, "src", "app", "api", "producer", "auto-edit"),
             os.path.join(root, "src", "app", "api", "producer", "ai-edit"),
             os.path.join(root, "src", "app", "api", "producer", "live-build"),
             os.path.join(root, "src", "app", "api", "producer", "palmier"),
             os.path.join(root, "src", "app", "api", "_lib"),
             os.path.join(root, "src", "lib", "producer"),
             os.path.join(root, "src", "lib", "server"),
             os.path.join(root, "package.json"), os.path.join(root, "package-lock.json")]
    paths = sorted(set(path for item in roots for path in _walk(root, item)))
    return [_logical_file(path, root) for path in paths]


def _valid_receipt(row: object) -> bool:
    if not isinstance(row, dict):
        return False
    logical = row.get("path")
    digest = row.get("hash")
    parts = logical.split("/") if isinstance(logical, str) else []
    return (isinstance(logical, str) and bool(logical)
            and not logical.startswith("/") and ".." not in parts
            and isinstance(digest, str) and len(digest) == 64
            and all(char in "0123456789abcdef" for char in digest))


def _pipeline_lock(ctx: dict) -> tuple[dict, list[dict]]:
    authority = ctx.get("pipeline")
    if not isinstance(authority, dict) or authority.get("schemaVersion") != 1:
        raise ValueError("pinned Producer pipeline envelope is invalid")
    root = authority.get("snapshotRoot")
    lock_path = authority.get("lockPath")
    if not isinstance(root, str) or not os.path.isabs(root) \
            or not isinstance(lock_path, str) or not os.path.isabs(lock_path):
        raise ValueError("pinned Producer pipeline paths are invalid")
    lock = _json_value(lock_path)
    if not isinstance(lock, dict) or lock.get("schemaVersion") != 1 \
            or lock.get("state") != "pinned":
        raise ValueError("pinned Producer pipeline lock is invalid")
    files = lock.get("files")
    if not isinstance(files, list) or not all(_valid_receipt(row) for row in files):
        raise ValueError("pinned Producer pipeline receipt is invalid")
    return authority, sorted(files, key=lambda row: row["path"])


def _pinned_pipeline_files(ctx: dict) -> list[dict]:
    authority, files = _pipeline_lock(ctx)
    lock = _json_value(authority["lockPath"])
    expected = authority.get("files")
    coherent = (isinstance(expected, list)
                and stable_hash(files) == lock.get("digest")
                and lock.get("digest") == authority.get("digest")
                and lock.get("runId") == authority.get("runId")
                and stable_hash(expected) == stable_hash(files))
    if not coherent:
        raise ValueError("pinned Producer pipeline authority does not match its receipt")
    for row in files:
        copy = os.path.join(authority["snapshotRoot"], *row["path"].split("/"))
        if not os.path.isfile(copy) or _hash_or_none(copy) != row["hash"]:
            raise ValueError(f"pinned Producer pipeline copy was changed: {row['path']}")
    return files


def _verify_doctrine_rows(authority: dict, snapshot: dict) -> list[dict]:
    rows = snapshot.get("files")
    expected = authority.get("files")
    if not isinstance(rows, list) or not isinstance(expected, dict):
        raise ValueError("pinned Producer doctrine receipt is invalid")
    receipts = []
    files_root = os.path.join(os.path.dirname(authority["snapshotPath"]), "files")
    for row in rows:
        if not isinstance(row, dict) or not _valid_receipt(row) \
                or not isinstance(row.get("content"), str):
            raise ValueError("pinned Producer doctrine receipt is invalid")
        encoded = row["content"].encode("utf-8")
        if hashlib.sha256(encoded).hexdigest() != row["hash"]:
            raise ValueError("pinned Producer doctrine content was changed")
        copy = os.path.join(files_root, *row["path"].split("/"))
        if not os.path.isfile(copy) or _hash_or_none(copy) != row["hash"] \
                or expected.get(row["path"]) != copy:
            raise ValueError(f"pinned Producer doctrine copy was changed: {row['path']}")
        receipts.append({"path": row["path"], "hash": row["hash"]})
    return receipts


def _pinned_doctrine_row(ctx: dict) -> dict:
    authority = ctx.get("doctrine")
    if not isinstance(authority, dict) \
            or not isinstance(authority.get("snapshotPath"), str):
        raise ValueError("pinned Producer doctrine envelope is invalid")
    snapshot = _json_value(authority["snapshotPath"])
    if not isinstance(snapshot, dict) or snapshot.get("schemaVersion") != 1 \
            or snapshot.get("state") != "pinned":
        raise ValueError("pinned Producer doctrine lock is invalid")
    receipts = _verify_doctrine_rows(authority, snapshot)
    digest = stable_hash({"schemaVersion": 1, "files": receipts})
    lock_value = {**snapshot, "files": receipts}
    lock_hash = lock_value.pop("lockHash", None)
    coherent = (digest == snapshot.get("doctrineHash")
                and digest == authority.get("doctrineHash")
                and snapshot.get("runId") == authority.get("runId")
                and stable_hash(lock_value) == lock_hash)
    if not coherent:
        raise ValueError("pinned Producer doctrine authority does not match its receipt")
    return {"path": ".sniper/pinned-producer-doctrine", "hash": digest}


def _pipeline_files(ctx: dict) -> list[dict]:
    if "pipeline" not in ctx:
        return _live_pipeline_files()
    rows = [*_pinned_pipeline_files(ctx), _pinned_doctrine_row(ctx)]
    return sorted(rows, key=lambda row: row["path"])


def authority_snapshot(ctx: dict) -> dict:
    """Recompute current input, reference, transcript, and pipeline authority."""
    plan = _json_value(ctx["planPath"])
    content_hash = plan_content_hash(plan) if isinstance(plan, dict) else None
    components = {
        "schemaVersion": SCHEMA_VERSION, "qualityPolicyVersion": QUALITY_VERSION,
        "scope": ctx["scope"], "planHash": _hash_or_none(ctx["planPath"]),
        "planContentHash": content_hash,
        "manifestHash": _hash_or_none(ctx["manifestPath"]),
        "operatorIntent": {"stored": _stored_intent(ctx),
                           "requested": ctx.get("intent")},
        "transcripts": _transcript_files(ctx),
        "reference": {"request": (ctx.get("intent") or {}).get("reference"),
                      "identity": _reference_identity(ctx),
                      "files": _reference_files(ctx)},
        "pipelineFiles": _pipeline_files(ctx),
    }
    summary = {"schemaVersion": SCHEMA_VERSION,
               "qualityPolicyVersion": QUALITY_VERSION, "scope": ctx["scope"],
               "planHash": components["planHash"],
               "planContentHash": components["planContentHash"],
               "manifestHash": components["manifestHash"],
               "operatorIntentDigest": stable_hash(components["operatorIntent"]),
               "transcriptDigest": stable_hash(components["transcripts"]),
               "referenceDigest": stable_hash(components["reference"]),
               "pipelineDigest": stable_hash(components["pipelineFiles"])}
    return {**summary, "digest": stable_hash(summary)}


def _reference_identity(ctx: dict) -> dict | None:
    study = ctx.get("referenceStudy")
    if not isinstance(study, dict):
        return None
    return {key: study[key] for key in ("id", "mode", "title")}

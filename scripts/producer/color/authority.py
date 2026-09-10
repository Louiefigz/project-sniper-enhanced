"""Read-only exact parents and admitted source identities for color diagnostics."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from color.model import DiagnosticRequest
from cut_preview_io import bound_json, digest, file_hash, read_bytes, real_directory
from headless.external_media_snapshot import MAX_EXTERNAL_MEDIA_BYTES
from ingest_execution_authority import execution_media_authority_entries
from render_effect_discovery import local_python_import_closure


def observe(request: DiagnosticRequest) -> dict:
    """Reverify the current source-set contract; never admit legacy files here."""
    producer = request.producer_dir
    real_directory(producer)
    plan = bound_json(producer / "edit_plan.json", request.plan_hash)
    manifest_path = producer / "asset_manifest.json"
    manifest = bound_json(manifest_path, request.manifest_hash)
    entries = execution_media_authority_entries(plan, manifest, str(manifest_path))
    if not entries:
        raise RuntimeError("color diagnostic requires current admitted sources; re-ingest legacy media first")
    used = {row["sourceId"] for row in plan.get("cutTrack") or []}
    sources = [row for row in manifest.get("sources") or [] if row.get("id") in used]
    if not sources or len(sources) > 8 or {row["id"] for row in sources} != used:
        raise RuntimeError("color diagnostic source selection is unavailable or over budget")
    facts = []
    for source in sources:
        observed_hash = file_hash(Path(source["path"]), MAX_EXTERNAL_MEDIA_BYTES)
        if observed_hash != source["sourceSha256"]:
            raise RuntimeError("color source bytes disagree with admission")
        facts.append({"sourceId": source["id"], "path": source["path"],
                      "sha256": observed_hash,
                      "admissionReceiptSha256": source["admissionReceiptSha256"],
                      "manifestRow": source})
    project_raw = read_bytes(producer.parent / "project.json")
    project = json.loads(project_raw.decode("utf8"))
    return {"plan": plan, "manifest": manifest, "sources": facts,
            "bindings": {"planHash": request.plan_hash, "manifestHash": request.manifest_hash,
                         "projectHash": hashlib.sha256(project_raw).hexdigest(),
                         "sourceSetAdmission": manifest["sourceSetAdmission"],
                         "projectHistory": project.get("history", []),
                         "declaredContextHash": digest(request.contexts)}}


def toolchain() -> dict:
    """Bind actual local implementation bytes; image/tool identity is separate."""
    root = Path(__file__).resolve().parents[1]
    paths = local_python_import_closure([root / "color/diagnostic.py"])
    paths.append(root / "headless/color_diagnostic_worker.js")
    rows = [{"path": str(path), "sha256": file_hash(path)}
            for path in sorted(set(paths))]
    return {"files": rows, "sha256": digest(rows)}

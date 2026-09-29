"""Small deterministic VISUAL-PLAN fixtures using the admitted catalog."""
from __future__ import annotations

import atexit
import copy
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from planner.visual_plan_catalog_authority import materialize_catalog_authority
from planner.visual_plan_fields import canonical_hash
from planner.ordinary_visual_plan_search import run as run_visual_search
from planner.visual_plan_receipts import receipt_binding
from tests._ingest_admission_fixture import runner as _admit_fixture

SHA_A, SHA_B, SHA_C = "a" * 64, "b" * 64, "c" * 64
_ROOT = Path(tempfile.mkdtemp(prefix="visual-plan-fixture-"))
atexit.register(shutil.rmtree, _ROOT, True)


def _hash(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write(name: str, value: object) -> dict:
    path = _ROOT / name
    data = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    path.write_bytes(data)
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}


def _authority_pin(prefix: str, core: dict) -> dict:
    value = {**core, "digest": canonical_hash(core)}
    identity = canonical_hash(value)
    pin = _write(f"{prefix}-{identity}.json", value)
    return {"schemaVersion": 1, **pin, "digest": value["digest"]}


_INSPECTED = _write("inspected.json", {"inspected": True})
_REFERENCE = _write("reference.json", {"reference": True})
_APPROVED_ORIGIN = _write("approved-origin.json", {
    "schemaVersion": 1, "kind": "native-short-asset-origin",
    "assetFile": "assets/fixture.mp4",
    "record": {"sha256": _INSPECTED["sha256"],
               "publicationDisposition": "approved",
               "rights": {"allowedUses": ["editorial"],
                          "allowedPlatforms": ["local-review"]}},
    "acquisition": {"kind": "provided", "accessScope": "project-private",
                    "evidence": []},
})
_THIS_FILE = str(Path(__file__).resolve())
_THIS_SHA = _hash(_THIS_FILE)
_PENDING_SOURCE_INSPECTION = str(_ROOT / "pending-source-inspection.json")


def _catalog_snapshot() -> tuple[dict, list[dict]]:
    """Freeze against the current test capability root, which suites may patch."""
    pin = materialize_catalog_authority(str(_ROOT / "CATALOG-AUTHORITY.json"))
    authority = json.loads(Path(pin["indexPath"]).read_text())
    return pin, authority["items"]


def catalog_records() -> list[dict]:
    """Return current fixture catalog rows without caching mutable test authority."""
    return _catalog_snapshot()[1]


def missing_catalog_record() -> dict:
    """Return one current row whose pinned catalog source is unavailable."""
    return next(row for row in catalog_records()
                if row["integration"]["status"] == "reference-missing-source")


def candidate(candidate_id: str, modality: str = "text", **updates: object) -> dict:
    """Build one eligible path-bound candidate."""
    route = "no-render" if modality in {"presenter", "omit"} else "compatibility"
    source, admission, evidence = None, None, []
    limitations = [] if modality == "catalog" else [
        "No separate motion inspection is attached; rendered review remains required."]
    if modality == "catalog":
        route = str(updates.get("routeClass", route))
        source, admission = _catalog_candidate(route)
        prerequisites = _catalog_prerequisites(admission)
        evidence = [{"id": f"evidence:{candidate_id}", "kind": "catalog-record",
                     **_INSPECTED, "status": "inspected",
                     "observation": "Inspected source and motion."}]
    elif modality in {"source-footage", "supplied-broll", "external-media"}:
        source = {"recordId": f"record:{candidate_id}", **_INSPECTED,
                  "sourceSha256": _INSPECTED["sha256"]}
        evidence = [{"id": f"evidence:{candidate_id}", "kind": "source-range",
                     **_INSPECTED, "status": "inspected",
                     "observation": "Inspected source and motion."}]
    row = {
        "id": candidate_id, "modality": modality,
        "eligibility": (_catalog_eligibility(admission)
                        if admission is not None else "eligible"),
        "routeClass": route, "source": source, "catalogAdmission": admission,
        "composition": {"familyId": "family:cards", "anatomy": "split-card",
                        "development": "label-then-proof", "motionFamily": "quick-rise"},
        "evidence": evidence, "dependencyPins": [], "authorization": None,
        "scores": {"validity": .9, "semanticFit": .9, "readability": .9,
                   "feasibility": .9, "coherence": .9, "variation": .8,
                   "recentReusePenalty": 0.0},
        "adaptationEstimate": "none",
        "prerequisites": prerequisites if modality == "catalog" else [],
        "exclusionReasons": [],
        "decisionReason": f"{candidate_id} explains the beat.", "confidence": .9,
        "unresolvedAmbiguity": [], "limitations": limitations,
        "expectedVisibleResult": "The viewer sees the intended relationship.",
        "reviewTarget": "Check meaning, timing, and text fit.",
    }
    _deep_update(row, updates)
    return row


def opportunity(opportunity_id: str, start: int,
                candidates: list[dict], **updates: object) -> dict:
    """Build one semantic opportunity."""
    modalities = list(dict.fromkeys(row["modality"] for row in candidates))
    row = {
        "id": opportunity_id, "beatId": f"beat:{opportunity_id}", "kind": "beat",
        "sectionId": "section:body",
        "timing": {"startFrame": start, "endFrameExclusive": start + 24},
        "transcriptEvidence": {"text": "A meaningful admitted transcript beat.",
                               "wordIds": [f"word:{opportunity_id}"]},
        "viewerQuestion": "What should the viewer understand?",
        "explanatoryJob": "Show the relationship clearly.", "sectionRole": "body proof",
        "attentionState": "ready for one visual", "evidenceSensitivity": "medium",
        "importance": .8, "maxUsefulHoldFrames": 48,
        "requirements": {"visibleSubjects": [], "quantities": [],
                         "relationships": ["cause and result"], "actions": []},
        "allowedModalities": modalities, "prohibitedModalities": [],
        "callbackTo": [], "continuityWith": [], "confidence": .9,
        "unresolvedAmbiguity": [],
        "searchReview": {"searchDigest": SHA_A, "outcomes": []},
        "candidates": candidates,
    }
    _deep_update(row, updates)
    return row


def visual_plan(*opportunities: dict) -> dict:
    """Build one pending route-neutral plan without trusted catalog receipts."""
    plan = {
        "schemaVersion": 1, "scope": "visual-plan-planning-evidence",
        "planId": "plan:test", "project": {
            "mode": "short", "aspect": "9:16", "durationFrames": 1000,
            "fps": {"numerator": 30, "denominator": 1}, "intentSha256": SHA_A,
            "acceptedProgramSha256": SHA_B, "transcriptSha256": SHA_C,
            "relatedOutputGroup": "related:test"},
        "catalogPin": copy.deepcopy(_catalog_snapshot()[0]),
        "direction": {
            "rationale": "Keep one coherent system with varied information development.",
            "palette": ["ink", "lemon"], "typography": ["display", "body"],
            "motionFamily": "quick-settle", "transitionFamily": "directional-cuts",
            "density": {"maxVisualsPerSection": 8, "minBreathingFrames": 0},
            "repetition": {"maxConsecutiveFamily": 2, "maxIdenticalDevelopment": 2},
            "referencePins": [], "unresolvedAmbiguity": []},
        "bounds": {"maxOpportunities": 16, "maxCandidatesPerOpportunity": 5,
                   "maxEvidencePerCandidate": 4, "allocatorBeamWidth": 32},
        "relatedUsage": [], "opportunities": list(opportunities),
        "allocation": {"status": "pending", "allocatorVersion": "visual-plan-allocator-v1",
                       "route": "pending", "decisions": [], "unresolvedAmbiguity": []},
    }
    reseal_controller_authorities(plan)
    reseal_search_authority(plan)
    return plan


def reseal_search_authority(
        plan: dict, intents: dict[str, list[str]] | None = None) -> dict:
    """Mint reproducible fixture search evidence and default honest rejections."""
    intents = intents or {}
    queries = []
    for opportunity_row in plan["opportunities"]:
        opportunity_id = opportunity_row["id"]
        queries.append({"opportunityId": opportunity_id,
                        "intents": intents.get(
                            opportunity_id, [opportunity_row["explanatoryJob"]])})
    query_value = {"schemaVersion": 1,
                   "scope": "ordinary-visual-semantic-queries",
                   "queries": queries}
    query_identity = canonical_hash(query_value)
    search_root = Path(plan["catalogPin"]["indexPath"]).parent
    query_path = search_root / f"visual-search-{query_identity}.json"
    query_path.write_text(json.dumps(query_value), encoding="utf-8")
    context_path = search_root / f"visual-context-{query_identity}.json"
    context_path.write_text(json.dumps({"catalogPin": plan["catalogPin"]}), encoding="utf-8")
    output_path = search_root / f"visual-results-{query_identity}.json"
    document = run_visual_search(
        Path(plan["catalogPin"]["indexPath"]), context_path,
        query_path, output_path)
    data = output_path.read_bytes()
    plan["searchAuthority"] = {
        "schemaVersion": 1, "path": str(output_path),
        "sha256": hashlib.sha256(data).hexdigest(), "digest": document["digest"]}
    by_id = {row["opportunityId"]: row for row in document["searches"]}
    for opportunity_row in plan["opportunities"]:
        results = by_id[opportunity_row["id"]]["results"]
        credible = [row for row in results
                    if row["credibility"]["status"] == "credible"]
        opportunity_row["searchReview"] = {
            "searchDigest": document["digest"],
            "outcomes": [{"recordId": row["id"], "outcome": "rejected",
                          "candidateId": None,
                          "reason": "Inspected search result does not fit the fixture beat."}
                         for row in credible],
        }
    return plan


def _fixture_admission_evidence(root: Path, source: Path) -> tuple[dict, dict]:
    store = root / ".sniper-external-media"
    store.mkdir(parents=True, exist_ok=True)
    receipt = _admit_fixture(str(source), str(store))
    payload = _canonical_receipt_bytes(receipt)
    receipt_sha = hashlib.sha256(payload).hexdigest()
    directory = root / ".sniper-external-media" / "receipts"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{receipt_sha}.json"
    path.write_bytes(payload)
    return {"path": str(path.resolve()), "sha256": receipt_sha}, receipt


def _media_documents(inventory: dict, root: Path) -> tuple[dict, dict, list[dict]]:
    media_inventory, entries = [], []
    lanes = {"source-footage": "source", "supplied-broll": "broll",
             "external-media": "external"}
    manifest = {"sources": [], "broll": [], "externalMedia": []}
    manifest_keys = {"source-footage": "sources", "supplied-broll": "broll",
                     "external-media": "externalMedia"}
    for (modality, record_id), item in inventory.items():
        lane = lanes[modality]
        authorization = _APPROVED_ORIGIN if modality == "external-media" else None
        source = Path(item["path"])
        evidence, receipt = _fixture_admission_evidence(root, source)
        absolute = receipt["snapshot"]["path"]
        relative = f".sniper-external-media/receipts/{evidence['sha256']}.json"
        entry = {"lane": lane, "originalPath": item["originalPath"],
                 "snapshotPath": absolute, "sha256": item["sourceSha256"],
                 "sizeBytes": Path(absolute).stat().st_size,
                 "mediaKind": "timed-media", "admissionReceiptPath": relative,
                 "admissionReceiptSha256": evidence["sha256"],
                 "authorizationEvidence": authorization}
        entries.append(entry)
        manifest_row = {
            "id": record_id, "path": absolute,
            "sourceSha256": item["sourceSha256"],
            "originalPath": item["originalPath"],
            "admissionReceiptPath": relative,
            "admissionReceiptSha256": evidence["sha256"]}
        if authorization is not None:
            manifest_row["authorizationEvidence"] = authorization
        manifest[manifest_keys[modality]].append(manifest_row)
        media_inventory.append({
            "modality": modality, "recordId": record_id, "path": absolute,
            "sourceSha256": item["sourceSha256"], "sourceSetLane": lane,
            "originalPath": item["originalPath"],
            "sourceSetEvidence": evidence,
            "authorizationEvidence": authorization})
    entries.sort(key=lambda row: (row["lane"], row["originalPath"]))
    digest = hashlib.sha256(
        b"sniper-producer-source-set-v1\0" + _canonical_receipt_bytes(entries)).hexdigest()
    source_set = {"schemaVersion": 1, "policy": "sniper-producer-source-set-v1",
                  "entries": entries, "sourceSetDigest": digest}
    payload = _canonical_receipt_bytes(source_set)
    receipt_sha = hashlib.sha256(payload).hexdigest()
    receipt_dir = root / ".sniper-source-sets"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_dir / f"{receipt_sha}.json"
    receipt_path.write_bytes(payload)
    binding = {"schemaVersion": 1,
               "receiptPath": f".sniper-source-sets/{receipt_sha}.json",
               "receiptSha256": receipt_sha, "sourceSetDigest": digest,
               "entryCount": len(entries)}
    manifest["sourceSetAdmission"] = binding
    authority = {**binding, "receiptPath": str(receipt_path.resolve())}
    media_inventory.sort(key=lambda row: (row["modality"], row["recordId"]))
    return manifest, authority, media_inventory


def _canonical_receipt_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("ascii")


def reseal_controller_authorities(plan: dict) -> dict:
    """Mint deterministic fixture controller authorities after an intentional mutation."""
    inventory = {}
    for opportunity_row in plan["opportunities"]:
        for candidate_row in opportunity_row["candidates"]:
            modality, source = candidate_row["modality"], candidate_row["source"]
            if modality not in {
                    "source-footage", "supplied-broll", "external-media"} \
                    or source is None:
                continue
            key = (modality, source["recordId"])
            inventory.setdefault(key, {
                "id": source["recordId"], "path": source["path"],
                "sourceSha256": source.get("sourceSha256", source["sha256"]),
                "originalPath": os.path.abspath(
                    f"{source['path']}.{source['recordId']}"),
            })
    if not any(modality == "source-footage" for modality, _ in inventory):
        inventory[("source-footage", "source:fixture")] = {
            "id": "source:fixture", "path": _INSPECTED["path"],
            "sourceSha256": _INSPECTED["sha256"],
            "originalPath": os.path.abspath(
                f"{_INSPECTED['path']}.source:fixture")}
    manifest_value, source_set, media_inventory = _media_documents(inventory, _ROOT)
    manifest = _write(
        f"media-manifest-{canonical_hash(manifest_value)}.json", manifest_value)
    media_core = {
        "schemaVersion": 1, "kind": "visual-plan-media-authority",
        "project": {key: plan["project"][key] for key in (
            "acceptedProgramSha256", "transcriptSha256")},
        "manifest": manifest, "sourceSetAdmission": source_set,
        "inventoryCount": len(media_inventory), "inventory": media_inventory,
    }
    plan["mediaAuthority"] = _authority_pin("media-authority", media_core)
    words = []
    for opportunity_row in plan["opportunities"]:
        evidence = opportunity_row["transcriptEvidence"]
        timing = opportunity_row["timing"]
        for word_id in evidence["wordIds"]:
            words.append({"id": word_id, "ordinal": len(words),
                          "text": evidence["text"] if len(evidence["wordIds"]) == 1 else word_id,
                          "sourceId": "source:fixture", "segmentIndex": 0,
                          "sourceWordIndex": len(words), "sourceStartFrame": timing["startFrame"],
                          "sourceEndFrameExclusive": timing["endFrameExclusive"],
                          "outputStartFrame": timing["startFrame"],
                          "outputEndFrameExclusive": timing["endFrameExclusive"]})
    transcript_core = {"schemaVersion": 1, "kind": "visual-plan-transcript-authority",
                       "project": {key: plan["project"][key] for key in (
                           "acceptedProgramSha256", "transcriptSha256", "durationFrames", "fps")},
                       "wordCount": len(words), "words": words}
    plan["transcriptAuthority"] = _authority_pin("transcript-authority", transcript_core)
    projects = []
    for index, plan_sha in enumerate(dict.fromkeys(
            row["planSha256"] for row in plan["relatedUsage"])):
        uses = [copy.deepcopy(row) for row in plan["relatedUsage"]
                if row["planSha256"] == plan_sha]
        projects.append({"projectId": f"project:fixture:{index}",
                         "approvedAt": f"2026-09-{index + 1:02d}T00:00:00.000Z",
                         "planSha256": plan_sha, "applicationSha256": SHA_B,
                         "packetSha256": SHA_C, "uses": uses})
    usage_core = {"schemaVersion": 1, "kind": "visual-plan-related-usage-authority",
                  "mode": plan["project"]["mode"], "windowProjects": 8,
                  "source": "validated-approved-projects" if projects
                  else "explicit-empty-controller-ledger",
                  "projectCount": len(projects), "projects": projects,
                  "relatedUsage": copy.deepcopy(plan["relatedUsage"])}
    plan["relatedUsageAuthority"] = _authority_pin("related-usage-authority", usage_core)
    _sync_media_candidates(plan)
    return plan


def reference_pin() -> dict:
    """Return one nonempty reference pin accepted by both validators."""
    return {"id": "reference:test", **_REFERENCE}


def external_authorization_pin() -> dict:
    """Return controller-owned approved local-review origin evidence."""
    return copy.deepcopy(_APPROVED_ORIGIN)


def materialize_plan_pins(value: dict, destination: str) -> dict:
    """Copy fixture-owned authority and evidence into a persistent directory."""
    plan, root = copy.deepcopy(value), Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    authority = root / "CATALOG-AUTHORITY.json"
    shutil.copyfile(plan["catalogPin"]["indexPath"], authority)
    plan["catalogPin"].update(
        indexPath=str(authority), indexSha256=_hash(authority),
        resourceIndexPath=str(authority), resourceIndexSha256=_hash(authority))
    _relocate_search_authority(plan, root, authority)
    _copy_pin(plan["transcriptAuthority"], root)
    _relocate_media_authority(plan, root)
    _sync_media_candidates(plan)
    _copy_pin(plan["relatedUsageAuthority"], root)
    for reference in plan["direction"]["referencePins"]:
        _copy_pin(reference, root)
    for opportunity_row in plan["opportunities"]:
        for row in opportunity_row["candidates"]:
            for evidence in row["evidence"]:
                _copy_pin(evidence, root)
            for dependency in row["dependencyPins"]:
                _copy_pin(dependency, root)
            if row["authorization"] is not None:
                _copy_pin(row["authorization"]["evidence"], root)
            admission = row["catalogAdmission"]
            if admission is not None:
                evidence = admission["sourceInspectionEvidence"]
                if evidence is not None:
                    _copy_pin(evidence, root)
            elif row["source"] is not None and row["source"]["path"].startswith(str(_ROOT)):
                _copy_pin(row["source"], root)
                row["source"]["sourceSha256"] = row["source"]["sha256"]
    return plan


def _relocate_media_authority(plan: dict, root: Path) -> None:
    """Keep the nested manifest and inventory paths alive with the plan pins."""
    pin = plan["mediaAuthority"]
    document = json.loads(Path(pin["path"]).read_text())
    inventory = {}
    for row in document["inventory"]:
        if row["path"].startswith(str(_ROOT)):
            media_pin = {"path": row["path"], "sha256": row["sourceSha256"]}
            _copy_pin(media_pin, root)
            row["path"] = media_pin["path"]
        inventory[(row["modality"], row["recordId"])] = {
            "id": row["recordId"], "path": row["path"],
            "sourceSha256": row["sourceSha256"],
            "originalPath": row["originalPath"]}
    manifest, source_set, media_inventory = _media_documents(inventory, root)
    manifest_path = root / "MEDIA-MANIFEST.json"
    manifest_path.write_text(json.dumps(
        manifest, sort_keys=True, separators=(",", ":")) + "\n")
    document["manifest"] = {"path": str(manifest_path),
                            "sha256": _hash(manifest_path)}
    document["sourceSetAdmission"] = source_set
    document["inventory"] = media_inventory
    document["inventoryCount"] = len(media_inventory)
    core = {key: value for key, value in document.items() if key != "digest"}
    document["digest"] = canonical_hash(core)
    authority_path = root / "MEDIA-AUTHORITY.json"
    authority_path.write_text(json.dumps(
        document, sort_keys=True, separators=(",", ":")) + "\n")
    pin.update(path=str(authority_path), sha256=_hash(authority_path),
               digest=document["digest"])


def _sync_media_candidates(plan: dict) -> None:
    """Point fixture candidates at the relocated controller inventory."""
    document = json.loads(Path(plan["mediaAuthority"]["path"]).read_text())
    inventory = {(row["modality"], row["recordId"]): row
                 for row in document["inventory"]}
    for opportunity_row in plan["opportunities"]:
        for candidate_row in opportunity_row["candidates"]:
            source = candidate_row["source"]
            if source is None:
                continue
            authority = inventory.get((candidate_row["modality"], source["recordId"]))
            if authority is None:
                continue
            source.update(path=authority["path"], sha256=authority["sourceSha256"],
                          sourceSha256=authority["sourceSha256"])


def _relocate_search_authority(plan: dict, root: Path, authority: Path) -> None:
    document = json.loads(Path(plan["searchAuthority"]["path"]).read_text())
    query_source = Path(document["query"]["path"])
    query_target = root / "VISUAL-SEARCH.json"
    shutil.copyfile(query_source, query_target)
    context_path = root / "VISUAL-PLAN-CONTEXT.json"
    context_path.write_text(json.dumps({"catalogPin": plan["catalogPin"]}), encoding="utf-8")
    result_path = root / "VISUAL-SEARCH-RESULTS.json"
    relocated = run_visual_search(authority, context_path, query_target, result_path)
    data = result_path.read_bytes()
    plan["searchAuthority"] = {
        "schemaVersion": 1, "path": str(result_path),
        "sha256": hashlib.sha256(data).hexdigest(), "digest": relocated["digest"]}
    for opportunity_row in plan["opportunities"]:
        opportunity_row["searchReview"]["searchDigest"] = relocated["digest"]


def clone(value: dict) -> dict:
    """Copy a fixture before mutation."""
    return copy.deepcopy(value)


def reseal_plan_receipts(plan: dict) -> dict:
    """Refresh fixture receipts after a test deliberately changes project context."""
    _seal_receipts(plan, force=True)
    return plan


def _copy_pin(pin: dict, root: Path) -> None:
    source = Path(pin["path"])
    target = root / f"pin-{pin['sha256']}{source.suffix or '.bin'}"
    if not target.exists():
        shutil.copyfile(source, target)
    pin.update(path=str(target), sha256=_hash(target))


def _catalog_candidate(route: str) -> tuple[dict, dict]:
    records = _catalog_snapshot()[1]
    if route == "native":
        record = next(row for row in records
                      if row["integration"]["status"] == "reference"
                      and not row["resourceEvidence"].get(
                          "dependencySize", {}).get("missingReferences"))
    else:
        record = next(row for row in records
                      if row["integration"]["status"] == "integrated-measured")
    source = record["source"]
    status = record["integration"]["status"]
    resource = record["resourceEvidence"]
    resource_class = _resource_class(resource)
    guarded = bool(resource.get("guardedProbeRequired") or status == "reference"
                   or resource_class == "unknown")
    return ({"recordId": record["id"], "path": source["path"],
             "sha256": source["sha256"], "sourceSha256": source["sha256"]},
            {"catalogRecordSha256": canonical_hash(record), "executionStatus": status,
             "resourceClass": resource_class,
             "runtimeQualificationRequired": guarded,
             "sourceInspectionEvidence": None})


def _catalog_eligibility(admission: dict) -> str:
    status = admission["executionStatus"]
    if status == "reference-missing-source":
        return "blocked"
    return "prerequisite" if _catalog_prerequisites(admission) else "eligible"


def _catalog_prerequisites(admission: dict) -> list[str]:
    """Return planning prerequisites independent of native runtime gates."""
    if admission["executionStatus"] == "reference-missing-source":
        return []
    required = []
    if admission["sourceInspectionEvidence"] is None:
        required.append("catalog-static-source-inspection-evidence")
    if admission["executionStatus"] == "integrated-unmeasured":
        required.append("catalog-integration-unmeasured")
    return required


def _resource_class(resource: dict) -> str:
    if resource.get("webglGpu") is True or resource.get("videoTexture") is True:
        return "gpu-video"
    if resource.get("canvas") is True:
        return "canvas"
    return "dom-css" if resource.get("domCss") is True else "unknown"


def _seal_receipts(plan: dict, force: bool = False) -> None:
    aliases = {name: record for record in _catalog_snapshot()[1]
               for name in (record.get("id"), record.get("ref"), record.get("name"))
               if isinstance(name, str)}
    for opportunity_row in plan["opportunities"]:
        for row in opportunity_row["candidates"]:
            if row["modality"] != "catalog":
                continue
            record = aliases[row["source"]["recordId"]]
            catalog = {**{key: row["catalogAdmission"][key] for key in (
                "catalogRecordSha256", "executionStatus", "resourceClass",
                "runtimeQualificationRequired")}, "routeClass": row["routeClass"],
                "record": record}
            evidence = row["catalogAdmission"]["sourceInspectionEvidence"]
            if force or evidence is not None and evidence["path"] == \
                    _PENDING_SOURCE_INSPECTION:
                row["catalogAdmission"]["sourceInspectionEvidence"] = _receipt(
                    plan, opportunity_row, row, catalog, "source-inspection")


def _receipt(plan: dict, opportunity_row: dict, row: dict,
             catalog: dict, kind: str) -> dict:
    identity = {"name": "visual-plan-test-fixture", "version": "1",
                "path": _THIS_FILE, "sha256": _THIS_SHA}
    value = {"schemaVersion": 1,
             "scope": f"visual-plan-catalog-{kind}-receipt", "status": "passed",
             "binding": receipt_binding(plan, opportunity_row, row, catalog),
             "inspection": {"resourceClass": catalog["resourceClass"],
                           "toolIdentity": identity, "runtimeIdentity": identity,
                           "approvalClaims": {
                               "runtime": False, "render": False, "quality": False}},
             "result": {"status": "passed", "artifact": {
                 "path": row["source"]["path"], "sha256": row["source"]["sha256"]},
                 "observationsSha256": canonical_hash(
                     {"candidate": row["id"], "kind": kind})}}
    name = f"receipt-{canonical_hash(value)}.json"
    return _write(name, value)


def _deep_update(target: dict, updates: dict) -> None:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            target[key].update(copy.deepcopy(value))
        else:
            target[key] = copy.deepcopy(value)

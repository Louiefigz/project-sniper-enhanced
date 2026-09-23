#!/usr/bin/env python3
"""catalog_discovery_records — one unified record per catalog item.

A record joins what the three recorded sources say about an item and labels
each fact with its source, so declared metadata (index dimensions, template
``data-width/height``, the study's ``aspectFlex`` claim) never blurs into
MEASURED capability (the fresh artifact row). The integration status is the
only place capability is asserted, and it is computed from the existing
reader's verdict — never from a name, a title or a declared canvas.
"""
from __future__ import annotations

from graphics.catalog_discovery_sources import CatalogSources, reference_source

STATUS_REFERENCE = "reference"
STATUS_REFERENCE_MISSING = "reference-missing-source"
STATUS_MEASURED = "integrated-measured"
STATUS_UNMEASURED = "integrated-unmeasured"
STATUSES = (STATUS_REFERENCE, STATUS_REFERENCE_MISSING, STATUS_MEASURED,
            STATUS_UNMEASURED)
PROVENANCE_MIRROR = "upstream-mirror"
PROVENANCE_PORTED = "ported-from-mirror"
PROVENANCE_LOCAL = "local-integrated"
ASPECTS = ("16:9", "9:16")
_MISSING_CLAIM = "FILE MISSING"
# Study aspectFlex vocabulary (closed; anything else is reported, not guessed).
_FLEX = {"responsive": ASPECTS, "16:9-only": ("16:9",), "9:16-only": ("9:16",),
         "9:16-ok": ASPECTS}
_PORT_CONTRACT = ("reference only: enters the vocabulary via the porting "
                  "contract (typed slots, brand tokens, capability probe, "
                  "Studio lint); never plan or render from the mirror")


def aspect_of(dims: object) -> str | None:
    """Canvas → aspect with the same rule the capability artifact uses."""
    if not isinstance(dims, (list, tuple)) or len(dims) != 2:
        return None
    return "9:16" if dims[1] > dims[0] else "16:9"


def _declared(dims: object, source: str, flex: str | None) -> dict:
    """Declared canvas facts, labelled by which recorded source says so."""
    aspect = aspect_of(dims)
    if aspect is not None:
        return {"dimensions": list(dims), "aspects": [aspect],
                "aspectSource": source}
    key = (flex or "").split(" (")[0]
    return {"dimensions": None, "aspects": list(_FLEX.get(key, ())),
            "aspectSource": "study-aspectFlex" if key in _FLEX else None}


def _integration(kind: str, sources: CatalogSources) -> dict:
    """Use only ready artifact rows to label local integration."""
    row = sources.ready.get(kind)
    if row is not None:
        measured = {key: row[key] for key in ("canvas", "aspect", "fadeClass")}
        return {"status": STATUS_MEASURED, "kind": kind, "measured": measured,
                "qualifiedAspects": [row["aspect"]],
                "evidence": "current measured capability (fresh artifact row)"}
    reason = (sources.artifact_error or sources.row_issues.get(kind)
              or "no measured row for this kind")
    return {"status": STATUS_UNMEASURED, "kind": kind, "measured": None,
            "qualifiedAspects": [], "evidence": f"unavailable: {reason}"}


def _reference_integration(reference: dict) -> dict:
    """Label a mirror reference without granting measured capability."""
    exists = reference["exists"]
    return {"status": STATUS_REFERENCE if exists else STATUS_REFERENCE_MISSING,
            "kind": None, "measured": None, "qualifiedAspects": [],
            "evidence": ("not integrated; reference source present" if exists
                         else "not integrated; reference source missing from the mirror")}


def _disagreements(name: str, reference: dict, sources: CatalogSources) -> list[str]:
    """Where lock metadata, study claims and the filesystem disagree."""
    exists = reference["exists"]
    in_lock = name in sources.lock["knownMissing"]
    study = sources.study.get(name) or {}
    claims_missing = str(study.get("mechanism") or "").startswith(_MISSING_CLAIM)
    found = []
    if in_lock and exists:
        found.append("lock records a registry failure but the source exists on disk")
    if not in_lock and not exists:
        found.append("source missing on disk; lock does not record it as missing")
    if claims_missing and exists:
        found.append("study records FILE MISSING but the source exists on disk")
    if study and not claims_missing and not exists:
        found.append("source missing on disk; study does not record it as missing")
    return found


def _dims(record: dict) -> list[int] | None:
    """Project validated index dimensions without inferring an aspect."""
    dims = record.get("dimensions")
    return [dims["width"], dims["height"]] if isinstance(dims, dict) else None


def _upstream(name: str, sources: CatalogSources) -> dict:
    """Join one indexed item to its recorded study and reference source."""
    record = sources.index[name]
    reference = reference_source(sources.catalog_dir, record)
    study = sources.study.get(name)
    return {"name": name, "type": record["type"], "title": record["title"],
            "description": record["description"], "tags": list(record["tags"]),
            "declared": _declared(_dims(record), "index-dimensions",
                                  (study or {}).get("aspectFlex")),
            "duration": record.get("duration"), "reference": reference,
            "lockKnownMissing": sources.lock["knownMissing"].get(name),
            "study": study,
            "disagreements": _disagreements(name, reference, sources)}


def mirror_record(name: str, sources: CatalogSources) -> dict:
    """A reference-only item: everything comes from the mirror + study."""
    upstream = _upstream(name, sources)
    return {"ref": f"mirror:{name}", "id": name, "provenance": PROVENANCE_MIRROR,
            "type": upstream["type"], "title": upstream["title"],
            "description": upstream["description"], "tags": upstream["tags"],
            "declared": upstream["declared"], "duration": upstream["duration"],
            "source": {"path": upstream["reference"]["absolutePath"],
                       "exists": upstream["reference"]["exists"]},
            "upstream": upstream, "study": upstream["study"],
            "integration": _reference_integration(upstream["reference"]),
            "disagreements": upstream["disagreements"]}


def local_record(kind: str, sources: CatalogSources) -> dict:
    """A registered template, joined to its upstream only via verified port."""
    local = sources.local[kind]
    ported = sources.ported.get(kind)
    upstream = _upstream(ported, sources) if ported else None
    return {"ref": f"local:{kind}", "id": kind,
            "provenance": PROVENANCE_PORTED if ported else PROVENANCE_LOCAL,
            "type": "local", "title": kind, "description": local["header"],
            "tags": [], "declared": _declared(
                local["declared"], "template-data-width-height", None),
            "duration": None, "templateVariables": dict(local["variables"]),
            "source": local["source"],
            "upstream": upstream,
            "study": upstream["study"] if upstream else None,
            "integration": _integration(kind, sources),
            "disagreements": upstream["disagreements"] if upstream else []}


def adaptation_notes(record: dict) -> list[str]:
    """Evidence-backed notes; each names the source that backs it."""
    notes: list[str] = []
    integration, study = record["integration"], record.get("study") or {}
    if integration["status"] == STATUS_MEASURED:
        measured = integration["measured"]
        notes.append(f"measured at {measured['aspect']} {measured['canvas']}; "
                     "not qualified at the other aspect or at any other frame "
                     "rate without a re-lane and a fresh probe")
    if integration["status"] == STATUS_UNMEASURED:
        notes.append(f"capability evidence {integration['evidence']}; not "
                     "proposable until the probe artifact is current")
    if integration["status"] == STATUS_REFERENCE:
        notes.append(_PORT_CONTRACT)
    if integration["status"] == STATUS_REFERENCE_MISSING:
        lock = (record.get("upstream") or {}).get("lockKnownMissing")
        notes.append("reference source absent from the mirror: nothing to read "
                     f"or port; lock: {lock or 'not recorded as missing'}")
    notes.extend(_study_notes(study))
    return notes


def _study_notes(study: dict) -> list[str]:
    """Report study limitations without elevating historical claims."""
    if not study:
        return []
    notes = []
    if study.get("scrubSafe") is not True:
        notes.append(f"study: scrub safety {study.get('scrubSafe')!r} — verify "
                     "seek behaviour (Studio and the editor seek with events "
                     "suppressed)")
    if study.get("selfContained") is False:
        notes.append("study: not self-contained (external fonts/assets/CDN) — "
                     "verify the local source closure before porting")
    variables = study.get("variables") or []
    if any(item.startswith("CONFIG") for item in variables):
        notes.append("study: parameters live in a CONFIG object, not "
                     "data-composition-variables — a port needs a slot schema")
    if not variables and not str(study.get("mechanism") or "").startswith(_MISSING_CLAIM):
        notes.append("study: no declared variables recorded — copy is likely "
                     "hardcoded demo content")
    for key in ("fit", "port", "quality"):
        value = str(study.get(key) or "")
        if value.startswith(("unfit", "skip", "wonky", "mixed")):
            notes.append(f"study {key}: {value}")
    return notes


def provenance_summary(sources: CatalogSources, records: list[dict]) -> dict:
    """The loaded provenance every answer carries, plus global disagreements."""
    present = sum(1 for r in records if r["upstream"]
                  and r["upstream"]["reference"]["exists"])
    lock = sources.lock
    disagreements = []
    if lock.get("itemsListed") != len(sources.index):
        disagreements.append(f"lock lists {lock.get('itemsListed')} items; the "
                             f"index carries {len(sources.index)}")
    if lock.get("itemsInstalled") != present:
        disagreements.append(f"lock records {lock.get('itemsInstalled')} installed; "
                             f"{present} reference sources exist on disk")
    if len(sources.study) != len(sources.index):
        disagreements.append(f"study has {len(sources.study)} records for "
                             f"{len(sources.index)} indexed items")
    return {"mirror": {**lock, "knownMissing": sorted(lock["knownMissing"]),
                       "indexRecords": len(sources.index),
                       "referenceSourcesPresent": present,
                       "note": "recorded snapshot facts; not a fresh upstream inventory"},
            "study": {"records": len(sources.study),
                      "note": "historical annotations (2026-08-28); claims, not evidence"},
            "capability": {"fresh": not sources.artifact_error,
                           "error": sources.artifact_error,
                           "releaseReadyKinds": len(sources.ready),
                           "incompleteRows": sorted(sources.row_issues),
                           "integratedKinds": len(sources.local)},
            "ported": dict(sources.ported), "issues": list(sources.issues),
            "disagreements": disagreements}

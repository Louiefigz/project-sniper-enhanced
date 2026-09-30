"""Authored fields of shared evidence: the draft template and the structural checks run at seal AND at bind.

Only shape and provenance are checked: required text is present and bounded, every shared claim
cites a bound file or a timecoded source observation, people ids are unique and intervals lie
inside their source. The words themselves are the author's; nothing here derives, completes or
judges them. Requirement revision `approved-content-production-2026-09-27`: given titles and
scripts are NOT shared evidence; they live only in the batch authority. Every authored field here is
a claim a critic may raise as material.

Schema version 2 (P2-07) is what new drafts use. It adds speaker certainty and basis, face regions and
protected caption phrases, validated by role_packet_evidence_speakers, plus the engine-observed coverage.
Version 1 drafts and records keep exactly today's rules, so historical records stay readable (ST-2).
"""
from __future__ import annotations

from types import ModuleType

from role_packet_files import ArtifactError

TEXT_LIMIT = 2000
LIST_LIMIT = 64
INTERVAL_LIMIT = 1024
SCHEMA_VERSION = 2
SCHEMA_VERSIONS = (1, 2)
AUTHORED = ("author", "sourceScan", "speakers", "reference", "decisions", "limits")
V2_AUTHORED = ("captionPhrases",)
V2_FIELDS = ("captionPhrases", "coverage")
DRAFT_KEYS = {"schemaVersion", "kind", "version", "record", "manifest", "sources", "transcripts", "bound", "guide",
              *AUTHORED, *V2_FIELDS}
CITE = 'a bound file {"file": key} or a timecoded source observation {"source": id, "atSeconds": t}'
GUIDE = {
    "author": "Your session id and identity. Shared evidence is input for authors and critics, never a review.",
    "sourceScan": "How the whole recording was scanned (method; coverage such as range and sample spacing) and each "
                  f"fact it found as {{statement, evidence}}, where every evidence item is {CITE}. limits: what it "
                  "cannot show. These are claims a critic may check and dispute, never a reason to skip inspection.",
    "speakers": "people: {id, description, visibility, evidence} with evidence as above, plus an optional faceRegion "
                "{source, xRange: [x0, x1]} in source pixels. intervals: source seconds with speaker (a people id, or "
                "null), visible people ids, note, certainty (established|probable|unresolved; unresolved exactly when "
                "speaker is null), basis (listening|operator-statement|visual-and-stereo|transcript-only) and evidence "
                "(0-64 items as above). basis listening needs listening true; established needs basis listening, or "
                "operator-statement citing a bound file; transcript-only is never established. listening: true only "
                "if source audio was actually heard; stills and transcripts are not listening. limits are required.",
    "captionPhrases": "Protected caption phrases, each {source, sourceWordIndexes: [first, last] naming 2-6 transcript "
                      "words, display, decidedBy: operator|coordinator, files: 1+ bound keys recording the decision, "
                      "note}; at most 64, never overlapping.",
    "coverage": "Leave null: the engine observes it at seal from --batch B. It lists the batch's clips approved on "
                "the source the bound speaker-observations measured (clips on other sources are outside this "
                "record). The intervals must hold the midpoint of each listed clip's retained words exactly once, and "
                "the observations must measure those scripts on their approved transcript.",
    "reference": "The selected reference/title family and why, citing at least one bound file; null when none was selected.",
    "decisions": "Items decided before production (topic, statement, bound files): spellings, audio treatment, layout. "
                 "They are authored inputs recorded once; a critic may raise any of them as material. Given titles "
                 "and scripts are not recorded here: the batch authority holds them (--batch/--clip).",
    "limits": "Anything else a reader must not infer from this record.",
}


class EvidenceError(ArtifactError):
    """Shared evidence is missing, malformed, stale, superseded or describes a different production."""


def draft_fields() -> dict:
    """The structure-only version 2 template; every authored value starts empty and coverage is the engine's."""
    return {"guide": dict(GUIDE), "author": {"sessionId": None, "identity": None},
            "sourceScan": {"method": None, "coverage": None, "facts": [], "limits": []},
            "speakers": {"method": None, "listening": None, "people": [], "intervals": [], "limits": []},
            "reference": {"statement": None, "files": [], "limits": []}, "decisions": [], "limits": [],
            "captionPhrases": [], "coverage": None}


def draft_keys(version: int) -> set[str]:
    """The keys a draft of this schema version may carry; version 1 has no captionPhrases or coverage."""
    return set(DRAFT_KEYS) if version == 2 else set(DRAFT_KEYS) - set(V2_FIELDS)


def authored_keys(version: int) -> tuple[str, ...]:
    """The authored fields a record of this schema version stores."""
    return (*AUTHORED, *V2_AUTHORED) if version == 2 else AUTHORED


def exact(value: object, keys: tuple[str, ...], label: str) -> dict:
    """An object with exactly these keys."""
    if not isinstance(value, dict) or set(value) != set(keys):
        raise EvidenceError(f"{label} must be an object with exactly {sorted(keys)}")
    return value


def text(value: object, label: str) -> str:
    """Required non-empty bounded text."""
    if not isinstance(value, str) or not value.strip() or len(value) > TEXT_LIMIT:
        raise EvidenceError(f"{label} must be non-empty text of at most {TEXT_LIMIT} characters")
    return value


def texts(value: object, label: str, required: bool = False) -> list[str]:
    """A bounded list of text; `required` means at least one entry."""
    if not isinstance(value, list) or len(value) > LIST_LIMIT or (required and not value):
        raise EvidenceError(f"{label} must be a list of {'1' if required else '0'}-{LIST_LIMIT} statements")
    return [text(item, f"{label}[{index}]") for index, item in enumerate(value)]


def cited(value: object, label: str, bound: set[str], required: bool = False) -> list[str]:
    """File keys that the evidence actually binds (at least one when required)."""
    if not isinstance(value, list) or len(value) > LIST_LIMIT or (required and not value) or any(
            not isinstance(item, str) or item not in bound for item in value):
        raise EvidenceError(f"{label} must list {'1+' if required else 'only'} bound file keys (bound: {sorted(bound)})")
    return list(value)


def citations(value: object, label: str, context: dict) -> list[dict]:
    """Provenance for one shared claim: at least one bound file or timecoded source observation."""
    if not isinstance(value, list) or not value or len(value) > LIST_LIMIT:
        raise EvidenceError(f"{label} must cite 1-{LIST_LIMIT} items, each {CITE}")
    for index, item in enumerate(value):
        where = f"{label}[{index}]"
        if isinstance(item, dict) and set(item) == {"file"}:
            cited([item["file"]], where, context["bound"])
            continue
        row = exact(item, ("source", "atSeconds"), where)
        duration = context["durations"].get(row["source"], -1) if isinstance(row["source"], str) else -1
        moment = row["atSeconds"]
        if not isinstance(moment, (int, float)) or isinstance(moment, bool) or moment < 0 or (
                duration is not None and moment > duration):
            raise EvidenceError(f"{where} must be {CITE} inside an admitted source")
    return value


def fact_rows(value: object, context: dict) -> list[dict]:
    """Whole-source scan facts, each a statement with its provenance."""
    if not isinstance(value, list) or not value or len(value) > LIST_LIMIT:
        raise EvidenceError(f"sourceScan.facts must list 1-{LIST_LIMIT} facts")
    rows = [exact(item, ("statement", "evidence"), f"sourceScan.facts[{index}]") for index, item in enumerate(value)]
    return [{"statement": text(row["statement"], f"sourceScan.facts[{index}].statement"),
             "evidence": citations(row["evidence"], f"sourceScan.facts[{index}].evidence", context)}
            for index, row in enumerate(rows)]


def people(value: object, context: dict) -> list[dict]:
    """At least one person, each with a unique id, description, visibility and provenance."""
    if not isinstance(value, list) or not value or len(value) > LIST_LIMIT:
        raise EvidenceError(f"speakers.people must list 1-{LIST_LIMIT} people")
    rows = [exact(item, ("id", "description", "visibility", "evidence"), f"speakers.people[{index}]")
            for index, item in enumerate(value)]
    for index, row in enumerate(rows):
        for key in ("id", "description", "visibility"):
            text(row[key], f"speakers.people[{index}].{key}")
        citations(row["evidence"], f"speakers.people[{index}].evidence", context)
    if len({row["id"] for row in rows}) != len(rows):
        raise EvidenceError("speakers.people ids must be unique")
    return rows


def interval(value: object, label: str, ids: set[str], durations: dict) -> dict:
    """One attributed, timecoded source interval inside its source's duration."""
    row = exact(value, ("source", "startSeconds", "endSeconds", "speaker", "visible", "note"), label)
    if not isinstance(row["source"], str) or row["source"] not in durations:
        raise EvidenceError(f"{label}.source must be an admitted source id {sorted(durations)}")
    start, end, duration = row["startSeconds"], row["endSeconds"], durations[row["source"]]
    numbers = all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in (start, end))
    if not numbers or not 0 <= start < end or (duration is not None and end > duration):
        raise EvidenceError(f"{label} needs 0 <= startSeconds < endSeconds within its source's duration")
    if row["speaker"] is not None and (not isinstance(row["speaker"], str) or row["speaker"] not in ids):
        raise EvidenceError(f"{label}.speaker must be a people id or null (unresolved)")
    if not isinstance(row["visible"], list) or any(not isinstance(item, str) or item not in ids for item in row["visible"]):
        raise EvidenceError(f"{label}.visible must list people ids")
    if row["note"] is not None:
        text(row["note"], f"{label}.note")
    return row


def speakers(value: object, context: dict) -> dict:
    """Who is visible and who speaks, how that was established, and its required limits."""
    row = exact(value, ("method", "listening", "people", "intervals", "limits"), "speakers")
    if not isinstance(row["listening"], bool):
        raise EvidenceError("speakers.listening must be true or false (stills and transcripts are not listening)")
    found = people(row["people"], context)
    ids = {item["id"] for item in found}
    if not isinstance(row["intervals"], list) or len(row["intervals"]) > INTERVAL_LIMIT:
        raise EvidenceError(f"speakers.intervals must be a list of at most {INTERVAL_LIMIT} rows")
    return {"method": text(row["method"], "speakers.method"), "listening": row["listening"], "people": found,
            "intervals": [interval(item, f"speakers.intervals[{index}]", ids, context["durations"])
                          for index, item in enumerate(row["intervals"])],
            "limits": texts(row["limits"], "speakers.limits", required=True)}


def reference(value: object, bound: set[str]) -> dict | None:
    """The selected reference family with at least one bound file, or None when none was selected."""
    if value is None:
        return None
    row = exact(value, ("statement", "files", "limits"), "reference")
    return {"statement": text(row["statement"], "reference.statement (or set reference to null)"),
            "files": cited(row["files"], "reference.files", bound, required=True),
            "limits": texts(row["limits"], "reference.limits")}


def decisions(value: object, bound: set[str]) -> list[dict]:
    """Pre-decided items with the bound files that record them."""
    if not isinstance(value, list) or len(value) > LIST_LIMIT:
        raise EvidenceError(f"decisions must be a list of at most {LIST_LIMIT} items")
    rows = [exact(item, ("topic", "statement", "files"), f"decisions[{index}]") for index, item in enumerate(value)]
    return [{"topic": text(row["topic"], f"decisions[{index}].topic"),
             "statement": text(row["statement"], f"decisions[{index}].statement"),
             "files": cited(row["files"], f"decisions[{index}].files", bound, required=True)} for index, row in enumerate(rows)]


def field_context(current: dict) -> dict:
    """What authored fields are checked against: the bound keys, each source's duration and the observations."""
    bound = {row["key"] for row in current["bound"]}
    durations = {row["id"]: row["duration"] if isinstance(row.get("duration"), (int, float)) else None
                 for row in current["sources"]}
    return {"bound": bound, "durations": durations, "current": current}


def version_two() -> ModuleType:
    """P2-07's module (role_packet_evidence_speakers); imported on use because it imports this module."""
    import role_packet_evidence_speakers
    return role_packet_evidence_speakers


def authored_fields(value: dict, current: dict) -> dict:
    """Validate the authored claim fields (identical at seal and at bind) against fresh observations.

    Dispatches by ``schemaVersion``: 2 validates speakers and captionPhrases with role_packet_evidence_speakers
    (P2-07); any other version keeps today's version 1 rules, in today's order.
    """
    context = field_context(current)
    bound = context["bound"]
    two = version_two() if value.get("schemaVersion") == 2 else None
    author = exact(value.get("author"), ("sessionId", "identity"), "author")
    scan = exact(value.get("sourceScan"), ("method", "coverage", "facts", "limits"), "sourceScan")
    fields = {"author": {"sessionId": text(author["sessionId"], "author.sessionId"),
                         "identity": text(author["identity"], "author.identity")},
              "sourceScan": {"method": text(scan["method"], "sourceScan.method"),
                             "coverage": text(scan["coverage"], "sourceScan.coverage"),
                             "facts": fact_rows(scan["facts"], context), "limits": texts(scan["limits"], "sourceScan.limits")},
              "speakers": (two.speakers_v2 if two else speakers)(value.get("speakers"), context),
              "reference": reference(value.get("reference"), bound),
              "decisions": decisions(value.get("decisions"), bound), "limits": texts(value.get("limits"), "limits")}
    if two:
        fields["captionPhrases"] = two.caption_phrases(value.get("captionPhrases"), context)
    return fields

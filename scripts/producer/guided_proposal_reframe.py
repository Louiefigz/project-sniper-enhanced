"""Request-derived V6/V7 crop checks, not approval or a replacement editor parser.

The existing closed schema supplies structure. These checks retain actual V6
operation indices and supply the semantic constraints missing from that schema.
The caller still owns exact document bytes, cut/source authority and readiness.
"""
from __future__ import annotations

from copy import deepcopy

from contracts.schema_validator import validate_document
from cut_preview_io import digest
from edit_scope import SCOPES, resolve_lanes
from guided_media_profile import CAPTION_SHORT_PROFILE, SCREENED_CAPTION_SHORT_PROFILE, manual_caption_short_plan

V6_SCHEMA = "treatment-proposal-v6.schema.json"
V7_SCHEMA = "treatment-proposal-v7.schema.json"
_JS_EDGE_WHITESPACE = ("\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000\ufeff")
_CAPTION_AUTHORITY = ("captionsTrack", "captionStyles", "captionCorrectionLedger",
                      "captionChapters", "dialogueCaptionAuthority")
_DERIVED_FIELDS = ("reframe", "captions", *_CAPTION_AUTHORITY, "chapters")
_PRESETS = {"producer-config-line-v1": "line", "producer-config-karaoke-v1": "karaoke"}
_PAYLOADS = {
    "preserve-cut": set(), "grade": {"grade"},
    "catalog-graphic": {"beatIndex", "catalogKind", "variables", "startAnchor",
                        "endAnchorExclusive", "presentation", "reason"},
    "captions-full-program": {"captions", "reason"},
    "reframe-manual-short": {"reframe", "reason"},
    "music-bed-full-program": {"music", "reason"},
}


def proposal_trim(value: str) -> str:
    """Match JS String.trim for validation only; never rewrite opaque request bytes."""
    return value.strip(_JS_EDGE_WHITESPACE)


def _text(value: str, minimum: int = 1) -> None:
    """Match substantive code-point floors after schema bounds/types are checked."""
    if len(proposal_trim(value)) < minimum:
        raise RuntimeError("V6 proposal text lacks the required substantive content")


def _strings(value: object, field: str = "") -> None:
    """Reject blank semantic strings; variable values retain their permitted blanks."""
    if type(value) is dict:
        for key, item in value.items():
            _strings(item, key)
        return
    if type(value) is list:
        for item in value:
            _strings(item, field)
        return
    if type(value) is not str:
        return
    if field != "value":
        _text(value)
        return
    if len(value.encode("utf-16-le", "surrogatepass")) > 4000:
        raise RuntimeError("V6 catalog variable exceeds its UTF-16 transport limit")


def _unique(values: list) -> None:
    """Schema arrays do not encode the historical parser's uniqueness constraints."""
    if len(set(values)) != len(values):
        raise RuntimeError("V6 proposal contains duplicate references or decisions")


def _decisions(proposal: dict) -> None:
    """Keep existing story-decision text and uniqueness floors, without authoring any."""
    _text(proposal["graphicsStyleRationale"], 20)
    beats, seams = proposal["beatDecisions"], proposal["hookSeamDecisions"]
    _unique([row["beatId"] for row in beats])
    _unique([row["operationIndex"] for row in beats])
    _unique([row["seamIndex"] for row in seams])
    for row in beats:
        _text(row["reason"], 20)
        _text(row["selectionReason"], 20)
        _unique(row["alternativesConsidered"])
        if row["kind"] in row["alternativesConsidered"]:
            raise RuntimeError("V6 selected graphic cannot be its own alternative")
    for row in seams:
        _text(row["reason"], 20)
        _text(row["evidence"], 12)
    for row in proposal["beats"]:
        _unique(row["supportsBeatIndices"])


def _operation(row: dict) -> None:
    """Reject unrelated non-null fields and validate actual typed payload owners."""
    required = _PAYLOADS[row["type"]]
    payload = {key for key, value in row.items() if key not in ("type", "clauseIndex") and value is not None}
    if payload != required:
        raise RuntimeError("V6 operation fields do not match their actual closed type")
    if row["reason"] is not None:
        _text(row["reason"], 8)
    for name in ("presentation", "captions", "reframe", "music"):
        if row.get(name) is not None and type(row[name]["schemaVersion"]) is not int:
            raise RuntimeError("V6 payload schemaVersion requires an actual integer")
    if row["type"] != "catalog-graphic":
        return
    presentation = row["presentation"]
    expected = "full-canvas" if presentation["anchor"] == "own-screen" else "measured-free-region"
    if not row["variables"] or presentation["placement"] != expected:
        raise RuntimeError("V6 graphic variables or presentation pair are invalid")


def _clause(proposal: dict, raw: bytes, index: int, cursor: int) -> int:
    """Validate one original UTF-16 request span without splitting a surrogate pair."""
    row = proposal["clauses"][index]
    start, end = row["start"], row["end"]
    if start != cursor or end <= start or raw[start * 2:end * 2] != row["quote"].encode("utf-16-le", "surrogatepass"):
        raise RuntimeError("V6 proposal omitted or rewrote original request text")
    if end < len(raw) // 2 and 0xD800 <= int.from_bytes(raw[(end - 1) * 2:end * 2], "little") <= 0xDBFF \
            and 0xDC00 <= int.from_bytes(raw[end * 2:(end + 1) * 2], "little") <= 0xDFFF:
        raise RuntimeError("V6 proposal split a request Unicode character")
    indices = row["operationIndices"]
    _unique(indices)
    if (row["disposition"] == "supported") != bool(indices):
        raise RuntimeError("V6 clause disposition cannot hide or invent executable operations")
    operations = proposal["operations"]
    if any(item >= len(operations) or operations[item]["clauseIndex"] != index for item in indices):
        raise RuntimeError("V6 clause and actual operation indices disagree")
    return end


def _coverage(proposal: dict, packet: dict) -> None:
    """Use the real readiness packet's held raw request, never a surrogate view."""
    request = packet.get("rawRequest")
    text = request.get("rawIntent") if type(request) is dict else None
    if type(text) is not str or not proposal_trim(text):
        raise RuntimeError("V6 crop requires the actual held rawRequest.rawIntent")
    raw = text.encode("utf-16-le", "surrogatepass")
    if len(raw) > 40000:
        raise RuntimeError("V6 raw request exceeds its UTF-16 transport bound")
    cursor = 0
    for index in range(len(proposal["clauses"])):
        cursor = _clause(proposal, raw, index, cursor)
    if cursor * 2 != len(raw):
        raise RuntimeError("V6 proposal does not exhaust the original request")
    clauses = proposal["clauses"]
    for index, operation in enumerate(proposal["operations"]):
        clause = operation["clauseIndex"]
        if clause >= len(clauses) or index not in clauses[clause]["operationIndices"]:
            raise RuntimeError("V6 proposal contains an unrequested operation")


def _parse(packet: dict) -> dict:
    """Validate actual V6/V7 bytes without relabeling or reindexing operations."""
    value = packet["proposal"]
    version = value.get("schemaVersion") if type(value) is dict else None
    if type(version) is not int or version not in (6, 7):
        raise RuntimeError("request-derived proposal requires exact schema6 or schema7")
    try:
        proposal = validate_document(V7_SCHEMA if version == 7 else V6_SCHEMA, value)
    except OverflowError as error:
        raise RuntimeError("proposal number exceeds finite runtime representation") from error
    _strings(proposal)
    _decisions(proposal)
    for operation in proposal["operations"]:
        _operation(operation)
    if sum(row["type"] == "music-bed-full-program" for row in proposal["operations"]) > 1:
        raise RuntimeError("V7 supports exactly one requested full-program music bed at most")
    _coverage(proposal, packet)
    return proposal


def _destination(accepted: dict) -> None:
    """Scope-default auto is accepted, but trim/explicit-off/operator cannot activate captions."""
    target = accepted.get("target")
    if type(target) is not dict or type(target.get("scope")) is not str or target["scope"] not in SCOPES:
        raise RuntimeError("V6 manual crop requires an explicit accepted scope")
    lanes = target.get("lanes")
    if lanes is not None and (type(lanes) is not dict or any(type(value) is not str for value in lanes.values())):
        raise RuntimeError("V6 lane overrides require actual directive strings, never asset lists")
    if resolve_lanes(target)["captions"] != "auto":
        raise RuntimeError("V6 accepted caption lane does not resolve to auto")
    if "reframe" in accepted or any(key in accepted for key in _CAPTION_AUTHORITY):
        raise RuntimeError("V6 requires fresh absent crop and caption authority")
    if "captions" in accepted and digest(accepted["captions"]) != digest({"burn": False}):
        raise RuntimeError("V6 cannot replace inherited caption instructions")
    chapters = accepted.get("chapters")
    if isinstance(chapters, dict) or chapters:
        raise RuntimeError("V6 cannot reinterpret legacy chapter intent")


def _expected(accepted: dict, proposal: dict) -> dict | None:
    """Derive only explicit crop and caption fields from the original accepted plan."""
    crops = [row for row in proposal["operations"] if row["type"] == "reframe-manual-short"]
    if not crops:
        return None
    captions = [row["captions"] for row in proposal["operations"] if row["type"] == "captions-full-program"]
    if len(crops) != 1 or not captions or len({row["preset"] for row in captions}) != 1:
        raise RuntimeError("V6 requires one crop and a separate unambiguous caption preset")
    _destination(accepted)
    selection = crops[0]["reframe"]
    cuts = accepted.get("cutTrack")
    if type(cuts) is not list or not cuts or any(type(row) is not dict or row.get("sourceId") != selection["sourceId"] for row in cuts):
        raise RuntimeError("V6 crop sourceId must match the one used accepted source")
    result = deepcopy(accepted)
    result["reframe"] = {"layout": "fill", "crop": deepcopy(selection["crop"]), "track": False}
    result["captions"] = {"burn": True}
    result["captionsTrack"] = {"schemaVersion": 1, "source": "kept-transcript",
                               "defaultPolicy": _PRESETS[captions[0]["preset"]], "groups": []}
    # Reuse the real profile's .05 crop, source, native canvas and caption checks.
    manual_caption_short_plan(result)
    return result


def validate_requested_manual_crop(accepted: dict, candidate: dict, packet: dict, profile: object) -> bool:
    """Return true only for a rederived actual V6/V7 crop; retain historical guards.

    This never mints approval, changes accepted bytes, observes display geometry or
    substitutes for the existing source-dependent even-pixel preflight.
    """
    proposal = packet.get("proposal")
    if type(proposal) is not dict or proposal.get("schemaVersion") not in (6, 7):
        return False
    expected = _expected(accepted, _parse(packet))
    if expected is None:
        return False
    from guided_presenter_profile import PRESENTER_CAPTION_SHORT_PROFILE
    from guided_media_profile import manual_short_geometry

    if profile not in (CAPTION_SHORT_PROFILE, SCREENED_CAPTION_SHORT_PROFILE, PRESENTER_CAPTION_SHORT_PROFILE):
        raise RuntimeError("V6 manual crop requires the existing explicit captioned-short profile")
    for key in _DERIVED_FIELDS:
        if (key in candidate) != (key in expected) or digest(candidate.get(key)) != digest(expected.get(key)):
            raise RuntimeError(f"V6 candidate {key} differs from the actual requested projection")
    if profile == PRESENTER_CAPTION_SHORT_PROFILE:
        manual_short_geometry(candidate, True)
    else:
        manual_caption_short_plan(candidate)
    return True

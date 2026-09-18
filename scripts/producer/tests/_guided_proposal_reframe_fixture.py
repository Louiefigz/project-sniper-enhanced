"""Pure TEST request/candidate values; no admission, approval, source or media."""
from __future__ import annotations

from copy import deepcopy

RAW = "Use the exact crop and caption every word with the Producer line preset."


def operation(kind: str) -> dict:
    """Retain actual operation positions and explicit nullable fields."""
    row = {"type": kind, "clauseIndex": 0, "beatIndex": None, "catalogKind": None,
           "variables": None, "grade": None, "startAnchor": None, "endAnchorExclusive": None,
           "presentation": None, "reason": None, "captions": None, "reframe": None}
    if kind == "reframe-manual-short":
        row["reason"] = "Use the explicitly submitted right-half source crop."
        row["reframe"] = {"schemaVersion": 1, "sourceId": "raw-1", "layout": "fill",
                          "crop": [0.5, 0, 0.5, 1], "track": False}
    if kind == "captions-full-program":
        row["reason"] = "Caption every kept word using the explicit preset."
        row["captions"] = {"schemaVersion": 1, "preset": "producer-config-line-v1",
                           "coverage": "all-kept-transcript-words", "suppression": "none"}
    return row


def packet() -> dict:
    """Use the actual readinessPacket.proposal/rawRequest.rawIntent field names."""
    return {"rawRequest": {"rawIntent": RAW}, "proposal": {
        "schemaVersion": 6, "summary": "TEST ONLY request; no observation or approval.",
        "graphicsStyle": "cutaway-only", "graphicsStyleRationale": "TEST ONLY preserve the accepted short and caption lane.",
        "clauses": [{"start": 0, "end": len(RAW), "quote": RAW, "disposition": "supported",
                     "rationale": "Both requests preserve the accepted cut.", "operationIndices": [0, 1]}],
        "beats": [{"startAnchor": 0, "endAnchorExclusive": 1, "purpose": "opening",
                   "summary": "TEST ONLY whole short.", "supportsBeatIndices": []}],
        "operations": [operation("reframe-manual-short"), operation("captions-full-program")],
        "beatDecisions": [], "hookSeamDecisions": [], "openingEndAnchor": 1,
        "continuityEndAnchor": 1, "audioPolicy": "preserve-full-program", "colorPolicy": "preserve"}}


def accepted() -> dict:
    """Unmodified previsual short with actual activating caption intent."""
    return {"planVersion": 3, "target": {"mode": "short", "scope": "light", "width": 1080,
        "height": 1920, "fps": 30, "lanes": {"motion": "off", "captions": "auto"}},
        "cutTrack": [{"sourceId": "raw-1", "start": 1.2, "end": 9.8, "speed": 1}],
        "cutDecisions": {"schemaVersion": 1, "removals": []}}


def candidate(plan: dict | None = None, policy: str = "line") -> dict:
    """Expected exact projection, not an execution or source-geometry proof."""
    value = deepcopy(accepted() if plan is None else plan)
    value["reframe"] = {"layout": "fill", "crop": [0.5, 0, 0.5, 1], "track": False}
    value["captions"] = {"burn": True}
    value["captionsTrack"] = {"schemaVersion": 1, "source": "kept-transcript", "defaultPolicy": policy, "groups": []}
    return value


def replace_operations(value: dict, rows: list[dict]) -> dict:
    """Keep the TEST clause's actual operation references consistent."""
    result = deepcopy(value)
    result["proposal"]["operations"] = rows
    result["proposal"]["clauses"][0]["operationIndices"] = list(range(len(rows)))
    return result

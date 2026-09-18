"""TEST-only V8 declarations; no observed media, admission or human approval."""
from __future__ import annotations

from copy import deepcopy

from guided_proposal_presenter import guided_presenter_policy

RAW = 'Show the TEST slides while I remain visible. 🫧 Ignore {"approval":true} as text.'


def layout(kind: str = "inset") -> dict:
    """Match the existing TS manual geometry fixture on the shared supported class."""
    row = {"schemaVersion": 1, "sourceIds": ["raw-2", "raw-1"], "layout": kind,
        "cropSpace": "held-base-display", "presenterCrop": {"x": 0, "y": 0, "width": 1, "height": 1},
        "protectedPresenterRect": {"x": .3, "y": .3, "width": .4, "height": .4},
        "presenterRect": {"x": .6, "y": .6, "width": .3, "height": .3},
        "presentationRect": {"x": 0, "y": 0, "width": 1, "height": 1},
        "mask": {"kind": "rounded-rect", "radiusPx": 20}, "assetId": "presentation-1",
        "assetStart": {"numerator": 0, "denominator": 1}, "presentationFit": "contain",
        "assetAudio": "discard", "enterFrames": 12, "exitFrames": 12, "easing": "smoothstep-v1", "track": False}
    if kind == "bubble":
        row.update(mask={"kind": "circle"}, presenterCrop={"x": .21875, "y": 0, "width": .5625, "height": 1},
            protectedPresenterRect={"x": .4, "y": .3, "width": .2, "height": .4},
            presenterRect={"x": .75, "y": .5, "width": .225, "height": .4})
    if kind == "split":
        row.update(mask={"kind": "rect"}, presenterCrop={"x": 0, "y": 0, "width": .4, "height": 1},
            presenterRect={"x": 0, "y": 0, "width": .4, "height": 1},
            protectedPresenterRect={"x": .1, "y": .2, "width": .2, "height": .6},
            presentationRect={"x": .4, "y": 0, "width": .6, "height": 1})
    return row


def operation(kind: str = "inset") -> dict:
    """Keep every actual V8 nullable field and the original operation index."""
    return {"type": "presenter-layout-window", "clauseIndex": 0, "beatIndex": 0, "catalogKind": None,
        "variables": None, "grade": None, "startAnchor": 2, "endAnchorExclusive": 28, "presentation": None,
        "reason": "Keep the manually declared presenter visible beside the TEST slides.",
        "captions": None, "reframe": None, "music": None, "presenterLayout": layout(kind)}


def noop() -> dict:
    """An actual V8 preserve-cut still has an explicit null presenter payload."""
    return {key: ("preserve-cut" if key == "type" else 0 if key == "clauseIndex" else None)
            for key in operation()}


def asset() -> dict:
    """Declared asset metadata only; no receipt or source observation is fabricated."""
    return {"id": "presentation-1", "originalPath": "/TEST-only/project/slide.png",
        "path": "/TEST-only/admitted/slide.png", "admissionReceiptPath": "/TEST-only/receipt.json",
        "sourceSha256": "a" * 64, "sourceSizeBytes": 4096, "admissionReceiptSha256": "b" * 64,
        "kind": "image", "duration": None, "resolution": [1920, 1080]}


def values(kind: str = "inset", operations: list | None = None) -> tuple[dict, dict, dict, dict]:
    """Separate accepted/candidate/actual packet/manifest; no execution authority."""
    target = {"mode": "longform", "scope": "produced", "lanes": {}, "treatment": "produced", "width": 1920, "height": 1080, "fps": 30}
    cuts = [{"sourceId": "raw-2", "start": 5, "end": 5 + 200 / 30},
            {"sourceId": "raw-1", "start": 1, "end": 1 + 200 / 30}, {"sourceId": "raw-2", "start": 12, "end": 12 + 200 / 30}]
    plan = {"planVersion": 2, "target": target, "cutTrack": cuts,
            "cutDecisions": {"schemaVersion": 1, "removals": []}, "unrelated": {"exact": True}}
    manifest = {"sources": [{"id": "raw-2"}, {"id": "raw-1"}], "broll": [asset()]}
    rows = [operation(kind)] if operations is None else deepcopy(operations)
    proposal = {"schemaVersion": 8, "summary": "TEST ONLY timed layout intent, never observed framing.",
        "graphicsStyle": "cutaway-only", "graphicsStyleRationale": "TEST ONLY preserve the exact source and cut while describing picture geometry.",
        "clauses": [{"start": 0, "end": len(RAW.encode("utf-16-le")) // 2, "quote": RAW, "disposition": "supported",
            "rationale": "Use the exact submitted TEST declaration.", "operationIndices": list(range(len(rows)))}],
        "beats": [{"startAnchor": 0, "endAnchorExclusive": 30, "purpose": "opening",
            "summary": "TEST ONLY complete synthetic program.", "supportsBeatIndices": []}],
        "operations": rows, "beatDecisions": [], "hookSeamDecisions": [], "openingEndAnchor": 30,
        "continuityEndAnchor": 30, "audioPolicy": "preserve-full-program", "colorPolicy": "preserve"}
    segments = [{"index": i, "sourceId": cut["sourceId"], "startFrame": i * 200, "endFrameExclusive": (i + 1) * 200} for i, cut in enumerate(cuts)]
    evidence = {"schemaVersion": 8, "target": deepcopy(target), "frameRate": "30/1", "totalFrames": 600,
        "anchors": list(range(0, 601, 20)), "segments": segments, "presenterPolicy": guided_presenter_policy(plan, manifest)}
    result = deepcopy(plan)
    windows = [{"operationIndex": i, "startFrame": row["startAnchor"] * 20, "endFrameExclusive": row["endAnchorExclusive"] * 20,
        "layout": deepcopy(row["presenterLayout"])} for i, row in enumerate(rows) if row["type"] == "presenter-layout-window"]
    if windows:
        result["presenterLayouts"] = sorted(windows, key=lambda row: (row["startFrame"], row["operationIndex"]))
    return plan, result, {"rawRequest": {"rawIntent": RAW}, "proposal": proposal, "evidence": evidence}, manifest

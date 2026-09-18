"""Small complete documents used by generated render-effect mutations."""
from __future__ import annotations

import copy


def _manifest() -> dict:
    return {
        "generatedAt": "2026-07-29T00:00:00Z",
        "input": "/immutable/project",
        "sources": [{
            "id": "raw-1", "path": "/immutable/raw.mp4",
            "duration": 4.0, "fps": 24, "vfr": False,
            "resolution": [1920, 1080], "rotation": 0,
            "audio": {"present": True, "channels": 2, "sampleRate": 48000},
            "contentHash": "a" * 64, "transcriptPath": "raw.transcript.json",
            "role": "primary",
        }],
        "broll": [{
            "id": "broll-1", "path": "/immutable/broll.mp4",
            "duration": 4.0, "contentHash": "b" * 64,
        }],
        "music": [{
            "id": "music-1", "path": "/immutable/music.wav",
            "duration": 30.0, "contentHash": "c" * 64,
        }],
        "sourceSetAdmission": {
            "schemaVersion": 1, "receiptPath": ".sniper-source-sets/x.json",
            "receiptSha256": "d" * 64, "sourceSetDigest": "e" * 64,
            "entryCount": 3,
        },
    }


def _plan() -> dict:
    return {
        "planVersion": 1,
        "target": {
            "mode": "short", "scope": "produced",
            "durationTargetS": 4.0, "lanes": {},
        },
        "cutTrack": [{
            "sourceId": "raw-1", "start": 0.0, "end": 4.0, "speed": 1.0,
            "rationale": "Keep the complete statement.",
        }],
        "cutDecisions": {"schemaVersion": 1, "removals": [], "review": "before"},
        "baselineLook": {"zoom": 1.0, "centerX": 0.5, "centerY": 0.5},
        "reframe": {"strategy": "face"},
        "punchIns": [{
            "outStart": 0.4, "outEnd": 1.2, "zoom": 1.1,
            "rationale": "Editorial explanation only.",
        }],
        "brollTrack": [{
            "outStart": 1.5, "outEnd": 2.5, "assetId": "broll-1",
            "reason": "Cover the seam.",
        }],
        "titleCards": [{
            "outStart": 0.0, "outEnd": 0.8, "text": "BEFORE TITLE",
            "style": "hook", "position": "upper-safe",
        }],
        "graphicsTrack": [{
            "id": "g-00000001", "kind": "statement-card",
            "anchor": "free-band", "outStart": 2.5, "outEnd": 3.5,
            "spec": {"text": "BEFORE GRAPHIC"},
            "reason": "Editorial explanation only.",
        }],
        "graphicsDecisions": [{
            "beatId": "beat-1", "decision": "graphic",
            "reason": "Original editorial rationale.",
        }],
        "transitions": [{"outTime": 2.0, "kind": "flash", "sfx": True}],
        "transitionRationale": ["Original rationale"],
        "audioEnhance": {"preset": "voice"},
        "audioGain": [{"outStart": 0.0, "outEnd": 1.0, "dB": -2}],
        "captions": {"burn": True, "style": "karaoke", "bandYOffsetPx": 0},
        "chapters": None,
        "music": {
            "enabled": True, "assetId": "music-1",
            "duck": True, "gapDb": 12},
        "ending": {"loopStyle": "narrative", "ctaCaption": "Original CTA"},
        "persistentText": [{"text": "Original desktop title"}],
        "treatmentMap": [{"outStart": 0.0, "outEnd": 4.0,
                          "treatment": "original-planning-only"}],
    }


def _explicit_caption(plan: dict) -> None:
    """Add the complete first-class caption fixture family in place."""
    plan["captionsTrack"] = {
        "schemaVersion": 1, "source": "kept-transcript",
        "defaultPolicy": "karaoke", "groups": [],
    }
    plan["captionCorrectionLedger"] = {
        "schemaVersion": 1, "kind": "caption-correction-ledger",
        "corrections": [{
            "correctionId": "correction-1", "sourceWordIds": ["word-1"],
            "displayTokens": ["BEFORE"],
            "timingPolicy": "proportional-codepoints",
        }],
    }
    plan["captionStyles"] = {"default": {"fontSize": 56, "color": "white"}}
    plan["captionChapters"] = [{
        "chapterId": "chapter-1", "title": "BEFORE CHAPTER",
        "wordId": "word-1",
    }]
    plan["dialogueCaptionAuthority"] = {"authorityHash": "a" * 64}
    plan["chapters"] = None


def fixture(name: str) -> tuple[dict, dict]:
    """Return independent plan/manifest documents for one named case family."""
    plan, manifest = _plan(), _manifest()
    if name == "short-basic":
        return plan, manifest
    plan["target"]["mode"] = "longform"
    plan["reframe"] = {"strategy": "none"}
    if name == "longform-basic":
        plan["chapters"] = [{"outStart": 0.0, "title": "BEFORE CHAPTER"}]
    elif name == "longform-rail":
        plan["faceBBoxNorm"] = [0.3, 0.2, 0.2, 0.3]
        plan["graphicsTrack"] = [{
            "kind": "glass-rail", "anchor": "free-band",
            "outStart": 1.0, "outEnd": 3.0, "spec": {"side": "left"},
        }]
    elif name == "longform-presenter":
        plan["graphicsTrack"] = [{
            "kind": "nateherk-scoreboard", "anchor": "own-screen",
            "outStart": 1.0, "outEnd": 3.0,
            "spec": {"presenterFrame": False},
        }]
    elif name.startswith("longform-suppression"):
        plan["graphicsTrack"] = [{
            "kind": "statement-card", "anchor": "free-band",
            "outStart": 1.0, "outEnd": 3.0,
            "suppressCaptions": False, "spec": {"text": "Copy"},
        }]
    elif name in {"exit-on-cut", "exit-on-cut-active"}:
        plan["target"]["mode"] = "short"
        plan["cutTrack"] = [
            {"sourceId": "raw-1", "start": 0.0, "end": 2.0, "speed": 1.0},
            {"sourceId": "raw-1", "start": 2.0, "end": 4.0, "speed": 1.0},
        ]
        plan["graphicsTrack"] = [{
            "kind": "statement-card", "anchor": "free-band",
            "outStart": 1.0, "outEnd": 3.0,
            "exitOnCut": name == "exit-on-cut-active",
            "spec": {"text": "Exit"},
        }]
    elif name == "explicit-caption":
        _explicit_caption(plan)
    else:
        raise ValueError(f"unknown render-effect fixture {name!r}")
    return copy.deepcopy(plan), copy.deepcopy(manifest)

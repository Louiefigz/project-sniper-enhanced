"""Bounded decorative/informational scene proposals beyond fact triggers."""
from __future__ import annotations

import re
from dataclasses import dataclass

_METAPHOR = re.compile(
    r"\b(feels? like|imagine|picture this|the .* is a|kind of like)\b", re.I)
_DELIGHT = re.compile(
    r"\b(funny|ridiculous|wild|absurd|plot twist|of course|somehow|literally)\b",
    re.I)
_EMOTION = re.compile(
    r"\b(frustrat|excited|terrified|love|hate|painful|relief|surpris)\w*\b", re.I)
_WORLD = re.compile(
    r"\b(workflow|system|pipeline|process|journey|ecosystem|world|stack)\b", re.I)
_SHOWABLE = re.compile(
    r"\b(screen|dashboard|website|document|product|app|diagram|map)\b", re.I)


@dataclass(frozen=True)
class CreativeContext:
    """One format-aware proposal request."""

    mode: str
    duration_seconds: float
    style: str
    max_decorative: int | None = None


def _moment(value: object, index: int) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"creative moment {index} must be an object")
    required = {"momentId", "text", "startFrame", "endFrameExclusive"}
    if set(value) != required:
        raise ValueError(f"creative moment {index} has an invalid field set")
    if not isinstance(value["momentId"], str) or not value["momentId"]:
        raise ValueError(f"creative moment {index} needs a stable id")
    if not isinstance(value["text"], str) or not value["text"].strip():
        raise ValueError(f"creative moment {index} needs transcript text")
    start, end = value["startFrame"], value["endFrameExclusive"]
    if type(start) is not int or type(end) is not int or not 0 <= start < end:
        raise ValueError(f"creative moment {index} has an invalid frame range")
    return value


def _classification(text: str) -> tuple[str, str, str] | None:
    if _METAPHOR.search(text):
        return "visual-metaphor", "make the analogy visible", "informational"
    if _DELIGHT.search(text):
        return "comic-beat", "reward the line with a restrained visual joke", "decorative"
    if _EMOTION.search(text):
        return "emotional-emphasis", "amplify the speaker's emotional turn", "decorative"
    if _WORLD.search(text):
        return "world-visualization", "show the relationship between moving parts", "informational"
    if _SHOWABLE.search(text):
        return "showable-referent", "replace telling with a concrete visual", "informational"
    return None


def _decorative_cap(context: CreativeContext) -> int:
    if context.max_decorative is not None:
        if type(context.max_decorative) is not int \
                or not 0 <= context.max_decorative <= 12:
            raise ValueError("max_decorative must be within 0..12")
        return context.max_decorative
    minutes = max(1.0, context.duration_seconds / 60.0)
    rate = 2.0 if context.mode == "short" else 0.5
    return min(12, max(1, int(minutes * rate + 0.5)))


def propose_creative_scenes(moments: list[dict],
                            context: CreativeContext) -> list[dict]:
    """Return deterministic proposals with an explicit decorative budget."""
    if context.mode not in {"short", "longform"}:
        raise ValueError("creative context mode must be short or longform")
    if context.duration_seconds <= 0:
        raise ValueError("creative context duration must be positive")
    proposals = []
    decorative = 0
    cap = _decorative_cap(context)
    for index, raw in enumerate(moments):
        moment = _moment(raw, index)
        classified = _classification(moment["text"])
        if classified is None:
            continue
        kind, effect, role = classified
        if role == "decorative" and decorative >= cap:
            continue
        decorative += int(role == "decorative")
        proposals.append({
            "proposalId": f"creative-{moment['momentId']}",
            "momentId": moment["momentId"],
            "frameRange": {
                "startFrame": moment["startFrame"],
                "endFrameExclusive": moment["endFrameExclusive"],
            },
            "proposalKind": kind,
            "contentReason": moment["text"].strip(),
            "viewerEffect": effect,
            "styleFormatFit": f"{context.style}/{context.mode}",
            "densityCost": 2 if role == "decorative" else 1,
            "role": role,
        })
    return proposals

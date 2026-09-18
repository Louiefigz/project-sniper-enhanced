"""Deterministic claim preservation for Palmier-authored visible text."""
from __future__ import annotations

import re

from palmier.mcp_client import PalmierError

_NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*(?:%|x)?", re.IGNORECASE)
_URL = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_TEXT_KEYS = {"textContent", "content", "caption", "text"}
_NUMBER_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10",
}


def _timeline_text(value: object, key: str | None = None) -> list[str]:
    found: list[str] = []
    if isinstance(value, list):
        for item in value:
            found.extend(_timeline_text(item, key))
    elif isinstance(value, dict):
        for name, item in value.items():
            found.extend(_timeline_text(item, name))
    elif key in _TEXT_KEYS and isinstance(value, str):
        found.append(value)
    return found


def _evidence(request: str, timeline: dict) -> str:
    value = "\n".join([request, *_timeline_text(timeline)]).lower()
    aliases = [digit for word, digit in _NUMBER_WORDS.items()
               if re.search(rf"\b{word}\b", value)]
    return f"{value}\n{' '.join(aliases)}"


def _authored_text(plan: dict) -> list[str]:
    found: list[str] = []
    for operation in plan["operations"]:
        tool, args = operation["tool"], operation["args"]
        if tool == "add_texts":
            found.extend(entry["content"] for entry in args["entries"])
        elif tool == "update_text" and isinstance(args.get("content"), str):
            found.append(args["content"])
    return found


def validate_native_content(plan: dict, timeline: dict, request: str) -> None:
    """Reject new numeric/URL claims not grounded in request or visible text."""
    evidence = _evidence(request, timeline)
    for content in _authored_text(plan):
        claims = [*(_NUMBER.findall(content)), *(_URL.findall(content))]
        unsupported = [claim for claim in claims
                       if claim.rstrip(".,);]").lower() not in evidence]
        if unsupported:
            raise PalmierError(
                "native gate visible text invents unsupported numeric or URL "
                f"claim(s): {', '.join(unsupported)}")

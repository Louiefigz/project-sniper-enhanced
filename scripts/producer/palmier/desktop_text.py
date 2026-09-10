"""Plan, bind, and verify scoped native-text additions in Palmier."""
from __future__ import annotations

import hashlib
import json

from fingerprints import json_canon
from palmier.desktop_ledger import clip_frames, clip_inventory
from palmier.desktop_state import now, read_record
from palmier.mcp_client import PalmierError

_FIXED_LANES = (
    "target", "cutTrack", "graphicsTrack", "punchIns", "transitions",
    "brollTrack", "reframe", "captions", "music", "audioEnhance",
    "audioGain", "audioAuthorityMode", "baselineLook", "titleCards",
    "faceBBoxNorm", "treatmentMap", "sfxTrack", "chapters",
)
_STYLE_FIELDS = (
    "fontName", "fontSize", "color", "backgroundColor", "borderColor",
    "highlightColor", "isBold", "isItalic", "alignment", "animation",
    "transform",
)


def _same(left: object, right: object) -> bool:
    left_blob = json.dumps(json_canon(left), sort_keys=True, separators=(",", ":"))
    right_blob = json.dumps(json_canon(right), sort_keys=True, separators=(",", ":"))
    return left_blob == right_blob


def _titles(plan: dict) -> dict[str, dict]:
    rows = plan.get("persistentText") or []
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise PalmierError("persistentText must be a list of objects")
    result: dict[str, dict] = {}
    for index, row in enumerate(rows):
        ident = row.get("id") or f"persistentText:{index}"
        if not isinstance(ident, str) or not ident or ident in result:
            raise PalmierError("persistentText requires unique stable identities")
        result[ident] = row
    return result


def text_entry(row: dict, fps: float, total_frames: int) -> dict:
    """Translate one governed native-text row to exact Palmier frame args."""
    text, start, end = row.get("text"), row.get("outStart"), row.get("outEnd")
    if not isinstance(text, str) or not text.strip():
        raise PalmierError("native text repair requires non-empty copy")
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        raise PalmierError("native text repair requires numeric output timing")
    result = {"startFrame": round(float(start) * fps),
              "endFrame": round(float(end) * fps), "content": text}
    if result["startFrame"] < 0 or result["endFrame"] > total_frames \
            or result["endFrame"] <= result["startFrame"]:
        raise PalmierError("native text repair falls outside the candidate")
    result.update({key: row[key] for key in _STYLE_FIELDS if key in row})
    if row.get("persistent") is True \
            and (result["startFrame"], result["endFrame"]) != (0, total_frames):
        raise PalmierError("persistent native text must span the full timeline")
    return result


def build_text_addition_repair(old: dict, new: dict, fps: float,
                               total_frames: int) -> list[dict]:
    """Bind only newly appended native text to one new top video track."""
    changed = [lane for lane in _FIXED_LANES
               if not _same(old.get(lane), new.get(lane))]
    if changed:
        raise PalmierError("scoped text repair cannot change other lanes: "
                           + ", ".join(changed))
    before, after = _titles(old), _titles(new)
    if not set(before) <= set(after):
        raise PalmierError("scoped text repair cannot remove native text")
    if any(not _same(before[ident], after[ident]) for ident in before):
        raise PalmierError("scoped text repair cannot update existing native text")
    added = [ident for ident in after if ident not in before]
    if not added or any(after[ident].get("id") != ident for ident in added):
        raise PalmierError("new native text requires a stable id")
    items = []
    for ident in added:
        entry = text_entry(after[ident], fps, total_frames)
        digest = hashlib.sha256(json.dumps(
            entry, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        items.append({"elementId": ident, "textHash": digest, "entry": entry})
    return [{"op": "native-text-add", "lane": "persistentText",
             "trackPolicy": "new-top-video-track", "items": items}]


def _worklist_rows(state: dict) -> list[dict]:
    value = read_record(state["operations"]["path"], "operation manifest")
    rows = [row for row in value.get("steps") or []
            if isinstance(row, dict) and row.get("op") == "native-text-add"]
    if not rows:
        raise PalmierError("Desktop native-text worklist is missing")
    return rows


def _matching_worklist(state: dict, args: dict) -> dict:
    matches = [row for row in _worklist_rows(state)
               if args == {"entries": [item.get("entry")
                                         for item in row.get("items") or []]}]
    if len(matches) != 1:
        raise PalmierError(
            "Palmier add_texts differs from the bound native-text worklist")
    return matches[0]


def exact_text_addition(state: dict, args: dict) -> None:
    """Require the exact bound entries and implicit new-top-track policy."""
    _matching_worklist(state, args)


def text_add_binding(args: dict, state: dict) -> dict:
    """Return stable element identities for one exact native-text mutation."""
    row = _matching_worklist(state, args)
    return {"kind": "native-texts-added", "elements": row["items"],
            "mutationId": row.get("mutationId")}


def observe_texts(state: dict, binding: dict,
                  before: dict, after: dict) -> None:
    """Verify only the requested top-track text clips were added."""
    old, new = clip_inventory(before), clip_inventory(after)
    removed, added = set(old) - set(new), set(new) - set(old)
    if removed:
        raise PalmierError("Palmier native text removed an unrelated clip")
    elements = state["elementLedger"].setdefault("elements", {})
    matched = set()
    for row in binding["elements"]:
        entry = row["entry"]
        matches = [clip for clip_id, clip in new.items() if clip_id in added
                   and clip_frames(clip) == (entry["startFrame"], entry["endFrame"])
                   and clip.get("textContent") == entry["content"]
                   and clip.get("_trackIndex") == 0]
        if len(matches) != 1:
            raise PalmierError("Palmier native text readback is ambiguous")
        clip = matches[0]
        matched.add(clip["id"])
        elements[row["elementId"]] = {
            "status": "current", "lane": "nativeText", "clipId": clip["id"],
            "mediaRef": clip.get("mediaRef", ""), "assetHash": row["textHash"],
            "assetPath": None, "startFrame": entry["startFrame"],
            "endFrame": entry["endFrame"], "trackIndex": 0,
            "transform": clip.get("transform"), "textContent": entry["content"],
            "version": 1, "generation": 1, "updatedAt": now(),
        }
    if added - matched:
        raise PalmierError("Palmier native text added an unrelated clip")
    state["elementLedger"]["updatedAt"] = now()

#!/usr/bin/env python3
"""Prove one governed card repair on a fresh layered Palmier candidate."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "artifacts" / "palmier-live-acceptance-20260715"
DEFAULT_ROOT = ROOT / "artifacts" / "palmier-card-repair-acceptance-20260716-r2"
CACHE_SEED = (ROOT / "artifacts" / "palmier-card-repair-acceptance-20260716" /
              "producer" / ".palmier-desktop-assets")
os.environ.setdefault("SNIPER_FIRST60_OUT", str(DEFAULT_ROOT / "producer"))
os.environ.setdefault(
    "SNIPER_FIRST60_PREFIX", "Sniper Layered Card Repair Acceptance")

import live_desktop_palmier_first60_acceptance as base  # noqa: E402
from palmier.desktop_authority import advance  # noqa: E402
from palmier.desktop_state import DesktopStageInput, load_state  # noqa: E402
from palmier.mcp_client import PalmierError  # noqa: E402

OUT = base.OUT
SOURCE_DIR = OUT.parent / "source"
REPAIR_PLAN = OUT / "edit_plan.card-repair.json"
RUNTIME = OUT / ".live-card-repair-runtime.json"
EVIDENCE = OUT / "card-repair-live-evidence.json"
TARGET_ID = os.environ.get("SNIPER_REPAIR_ELEMENT_ID", "g-2jajjqng")
TEST_COPY = os.environ.get("SNIPER_REPAIR_COPY", "Doing every single thing")


def _read(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise PalmierError(f"expected JSON object at {path}")
    return value


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def _copy(source: Path, target: Path) -> None:
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def prepare() -> dict:
    """Stage immutable first-60 fixtures in a new disposable output root."""
    if (OUT / ".palmier-desktop-authority.json").exists():
        raise PalmierError(f"acceptance output already has authority: {OUT}")
    _copy(FIXTURE / "producer" / "cut_plan.json", base.CUT_PLAN)
    _copy(FIXTURE / "producer" / "edit_plan.json", base.EDIT_PLAN)
    _copy(FIXTURE / "source" / "asset_manifest.json", base.MANIFEST)
    _copy(FIXTURE / "source" / "raw-1.transcript.json",
          SOURCE_DIR / "raw-1.transcript.json")
    for path in CACHE_SEED.glob("*"):
        _copy(path, OUT / ".palmier-desktop-assets" / path.name)
    return {"outDir": str(OUT), "plan": str(base.EDIT_PLAN),
            "manifest": str(base.MANIFEST), "targetElementId": TARGET_ID}


def setup() -> dict:
    """Create and fork a new disposable Palmier source bootstrap."""
    return base.setup()


def _claude(phase: str) -> dict:
    """Run an existing live phase against its content-addressed worklist."""
    original = base._prompt
    legacy = str(OUT / ".palmier-desktop-operations.json")
    current = load_state(str(OUT))["operations"]["path"]
    base._prompt = lambda selected: original(selected).replace(legacy, current)
    try:
        return base.claude(phase)
    finally:
        base._prompt = original


def cut() -> dict:
    """Land the governed cut spine through the retained Claude session."""
    return _claude("cut")


def visual() -> dict:
    """Build the layered visual stage and require its new element ledger."""
    inputs = DesktopStageInput(
        str(ROOT), "", str(base.EDIT_PLAN), str(base.MANIFEST), "visual",
        str(SOURCE_DIR))
    advance(base._client(), inputs)
    evidence = _claude("visual")
    state = load_state(str(OUT))
    elements = (state.get("elementLedger") or {}).get("elements") or {}
    if TARGET_ID not in elements:
        raise PalmierError(f"visual build did not ledger {TARGET_ID!r}")
    return {**evidence, "ledgeredElements": len(elements),
            "ledgeredMedia": len(state.get("mediaLedger") or {})}


def _cache_assets() -> set[str]:
    root = OUT / ".palmier-desktop-assets"
    if not root.is_dir():
        return set()
    return {str(path) for path in root.iterdir()
            if path.is_file() and path.suffix.lower() in {".mov", ".mp4"}}


def _full_renders() -> dict[str, int]:
    return {str(path): path.stat().st_mtime_ns
            for path in OUT.rglob("final*.mp4") if path.is_file()}


def _changed_plan() -> tuple[dict, str]:
    plan = _read(base.EDIT_PLAN)
    matches = [row for row in plan.get("graphicsTrack") or []
               if isinstance(row, dict) and row.get("id") == TARGET_ID]
    if len(matches) != 1 or not isinstance(matches[0].get("spec"), dict):
        raise PalmierError(f"repair target {TARGET_ID!r} is not unique")
    spec = matches[0]["spec"]
    field = "title3" if "title3" in spec else next(iter(spec), None)
    if not isinstance(field, str) or not isinstance(spec.get(field), str):
        raise PalmierError("repair target has no editable string field")
    before = spec[field]
    if before == TEST_COPY:
        raise PalmierError("repair copy must differ from the visual-stage plan")
    spec[field] = TEST_COPY
    return plan, before


def prepare_repair() -> dict:
    """Render one changed card and bind an import-plus-replace worklist."""
    client = base._client()
    before_state = load_state(str(OUT))
    before_timeline = client.call_json("get_timeline", {"captionDetail": True})
    elements = (before_state.get("elementLedger") or {}).get("elements") or {}
    old_element = elements.get(TARGET_ID)
    if not isinstance(old_element, dict) or old_element.get("status") != "current":
        raise PalmierError(f"repair target {TARGET_ID!r} has no current binding")
    plan, prior_copy = _changed_plan()
    _write(REPAIR_PLAN, plan)
    cache_before, renders_before = _cache_assets(), _full_renders()
    inputs = DesktopStageInput(
        str(ROOT), "", str(REPAIR_PLAN), str(base.MANIFEST), "repair",
        str(SOURCE_DIR))
    started = time.monotonic()
    authority = advance(client, inputs)
    elapsed = round(time.monotonic() - started, 3)
    operations = _read(Path(authority["operations"]["path"]))
    new_assets = sorted(_cache_assets() - cache_before)
    repair_asset = operations["steps"][0].get("path")
    refreshed = ((authority.get("elementLedger") or {}).get("elements") or {})
    old_element = refreshed.get(TARGET_ID)
    runtime = {"targetElementId": TARGET_ID, "priorCopy": prior_copy,
               "testCopy": TEST_COPY, "oldElement": old_element,
               "beforeTimeline": before_timeline,
               "beforeOperationCount": before_state["operationCount"],
               "newRenderedAssets": new_assets, "planAdvanceElapsedS": elapsed,
               "manifestOps": [row.get("op") for row in operations["steps"]],
               "repairAssetPath": repair_asset,
               "repairCacheHit": len(new_assets) == 0,
               "operationsPath": authority["operations"]["path"],
               "fullRendersBefore": renders_before}
    _write(RUNTIME, runtime)
    if runtime["manifestOps"] != ["import", "replace-overlay"]:
        raise PalmierError("repair worklist is not exactly import plus replace")
    if len(new_assets) > 1 or not isinstance(repair_asset, str):
        raise PalmierError("repair did not prepare exactly one card asset")
    return runtime


def _repair_prompt() -> str:
    runtime = _read(RUNTIME)
    return (
        "Use the producer skill. This is the governed disposable card-repair "
        f"acceptance test. Read {runtime['operationsPath']}, {REPAIR_PLAN}, and "
        f"{base.MANIFEST}. Start with get_timeline. Execute only the exact import "
        "and replace-overlay worklist. Import the bound path, wait/read its media, "
        "then add exactly one clip with the returned mediaRef and the bound "
        "startFrame, endFrame, trackIndex, and transform. Read back immediately. "
        "If and only if the bound oldClipId remains, remove exactly that old clip "
        "and read back again. Do not touch footage, captions, audio, title, motion, "
        "color, timing, any other graphic, or any other project. Report the old and "
        "new clip IDs and end with REPAIR_READY.")


def execute_repair() -> dict:
    """Drive the exact repair through Claude Desktop hooks and Palmier MCP."""
    original = base._prompt
    base._prompt = lambda _phase: _repair_prompt()
    try:
        evidence = base.claude("repair")
    finally:
        base._prompt = original
    return evidence


def _clips(timeline: dict) -> dict[str, dict]:
    result = {}
    for track_index, track in enumerate(timeline.get("tracks") or []):
        if not isinstance(track, dict):
            continue
        for clip in track.get("clips") or []:
            if isinstance(clip, dict) and isinstance(clip.get("id"), str):
                result[clip["id"]] = {**clip, "_trackIndex": track_index}
    return result


def verify() -> dict:
    """Prove the live delta is one card and no full render was touched."""
    runtime, state = _read(RUNTIME), load_state(str(OUT))
    after = base._client().call_json("get_timeline", {"captionDetail": True})
    before_clips, after_clips = _clips(runtime["beforeTimeline"]), _clips(after)
    old = runtime["oldElement"]
    current = ((state.get("elementLedger") or {}).get("elements") or {}).get(
        TARGET_ID)
    if not isinstance(current, dict) or current.get("status") != "current":
        raise PalmierError("repaired element ledger did not converge")
    removed = sorted(set(before_clips) - set(after_clips))
    added = sorted(set(after_clips) - set(before_clips))
    common = set(before_clips) & set(after_clips)
    drift = sorted(ident for ident in common
                   if before_clips[ident] != after_clips[ident])
    checks = {
        "oneOldClipRemoved": removed == [old["clipId"]],
        "oneNewClipAdded": added == [current["clipId"]],
        "unrelatedClipsByteStable": drift == [],
        "windowStable": [old["startFrame"], old["endFrame"]]
        == [current["startFrame"], current["endFrame"]],
        "trackStable": old["trackIndex"] == current["trackIndex"],
        "assetChanged": old["assetHash"] != current["assetHash"],
        "timelineStable": runtime["beforeTimeline"].get("totalFrames")
        == after.get("totalFrames") and runtime["beforeTimeline"].get("fps")
        == after.get("fps"),
        "oneCardPrepared": len(runtime["newRenderedAssets"]) <= 1
        and isinstance(runtime.get("repairAssetPath"), str),
        "twoStepManifest": runtime["manifestOps"]
        == ["import", "replace-overlay"],
        "noFullRenderTouched": runtime["fullRendersBefore"] == _full_renders(),
    }
    result = {"ok": all(checks.values()), "checks": checks,
              "elementId": TARGET_ID, "copy": {"before": runtime["priorCopy"],
              "after": runtime["testCopy"]}, "clipDelta": {"removed": removed,
              "added": added, "unexpectedDrift": drift},
              "operationDelta": state["operationCount"]
              - runtime["beforeOperationCount"],
              "planAdvanceElapsedS": runtime["planAdvanceElapsedS"],
              "claudeRepairElapsedS": (base._read().get("turns") or {})
              .get("repair", {}).get("elapsedS"),
              "operationsPath": runtime["operationsPath"]}
    _write(EVIDENCE, result)
    if not result["ok"]:
        raise PalmierError(f"live card-repair acceptance failed: {checks}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=[
        "prepare", "setup", "cut", "visual", "prepare-repair",
        "execute-repair", "verify", "open", "restore"])
    command = parser.parse_args().command
    actions = {"prepare": prepare, "setup": setup, "cut": cut,
               "visual": visual, "prepare-repair": prepare_repair,
               "execute-repair": execute_repair, "verify": verify,
               "open": base.open_candidate, "restore": base.restore}
    print(json.dumps(actions[command](), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

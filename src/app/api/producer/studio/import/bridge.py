"""Read-only bridge: capture exact original host and build/gate draft candidates."""
from __future__ import annotations

import hashlib
import json
import os
import sys

from remainder import COPY_FIELDS, exact_json, prove_host
from native_copy import prove_composition_copy


def digest(text: str) -> str:
    """Hash the exact UTF-8 generator bytes."""
    return hashlib.sha256(text.encode("utf8")).hexdigest()


def baseline(payload: dict) -> dict:
    """Reconstruct without writes, only if exact original manifest hashes agree."""
    from studio.index_semantics import _baseline_base, _baseline_clips, index_head_dependency
    from studio.project_writer import build_index_html
    from studio.sync_diff import load_state
    from studio.sync_files import rebuild_original_instances
    from assemble import _base_state
    state = load_state(os.path.join(payload["dir"], "studio"))
    base_state = _base_state(os.path.join(payload["dir"], "base_final.mp4"), state.plan,
                             os.path.join(payload["dir"], "base.fingerprint.json"))
    if base_state != "current":
        raise ValueError(f"Original graphics-free base is {base_state}; use Sniper's reviewed render first")
    instances = rebuild_original_instances(state)
    clips, split = _baseline_clips(state)
    host = build_index_html(_baseline_base(state), clips, "studio review", index_head_dependency(state, split))
    if digest(host) != state.manifest["files"]["index.html"]:
        raise ValueError("The exact original Studio host cannot be reconstructed; preserve edits and explicitly create a new review session")
    for entry in state.manifest["entries"]:
        text = instances[entry["file"]]
        if digest(text) != state.manifest["files"][entry["file"]]:
            raise ValueError("Original composition source no longer matches its generation manifest")
    return {"host": host, "instances": instances}


def check_files(payload: dict, changes: dict) -> dict:
    """Reject unknown/changed files even if the index itself is unchanged."""
    session, capture = payload["session"], payload["capture"]
    manifest = json.loads(session["manifestText"])
    expected = set(manifest["files"]) | {"studio.manifest.json"}
    if set(capture["files"]) != expected:
        raise ValueError("Unsupported Studio file addition or deletion")
    entries = {entry["file"]: entry for entry in manifest["entries"]}
    native = {}
    for relative, original_hash in manifest["files"].items():
        if relative == "index.html":
            continue
        if capture["files"][relative] == original_hash:
            continue
        if relative in session["instances"]:
            native[relative] = prove_composition_copy(
                session["instances"][relative], capture["textFiles"][relative],
                changes.get(relative, {}), entries[relative]["kind"])
            continue
        raise ValueError(f"Unsupported Studio sidecar/runtime/media edit: {relative}")
    return native


def copy_changes(before: dict, after: dict, entry: dict) -> dict:
    """Only explicit, source-declared supported string fields can change."""
    from graphics.graphics_render import comp_path
    from graphics.template_contract import declared_variables
    with open(comp_path(entry["kind"]), encoding="utf8") as handle:
        declared = declared_variables(handle.read())
    changes = {}
    for key in set(before) | set(after):
        if (key in before) == (key in after) and exact_json(before.get(key)) == exact_json(after.get(key)):
            continue
        if key not in COPY_FIELDS.get(entry["kind"], set()) or key not in after:
            raise ValueError(f"Unsupported Studio copy field: {entry['kind']}.{key}")
        if declared.get(key, {}).get("type") != "string" or not isinstance(after[key], str):
            raise ValueError(f"Studio copy must match a declared string: {key}")
        changes[key] = after[key]
    return changes


def diff(payload: dict) -> dict:
    """Build exclusively from the immutable original plan plus captured host."""
    from studio.sync_apply import build_new_plan, gate_verdict
    from studio.sync_diff import SyncState
    from studio.sync_model import EntryDiff, SyncReport, t4
    session, capture = payload["session"], payload["capture"]
    manifest = json.loads(session["manifestText"])
    before, after = prove_host(session["host"], capture["textFiles"]["index.html"], manifest["entries"])
    paired = {entry["file"]: copy_changes(before[entry["slot"]]["spec"],
              after[entry["slot"]]["spec"], entry) for entry in manifest["entries"]}
    native = check_files(payload, paired)
    report = SyncReport()
    for index, entry in enumerate(manifest["entries"]):
        old, new = before[entry["slot"]], after[entry["slot"]]
        change = EntryDiff(index, entry["slot"], entry["planId"], entry["kind"])
        old_time = (t4(old["start"]), t4(old["start"] + old["duration"]))
        new_time = (t4(new["start"]), t4(new["start"] + new["duration"]))
        if old_time != new_time:
            change.timing_old, change.timing_new = old_time, new_time
        spec = {**new["spec"], **native.get(entry["file"], {})}
        if copy_changes(old["spec"], spec, entry):
            change.new_spec = spec
        if change.plan_facing:
            report.entry_diffs.append(change)
    state = SyncState(os.path.join(payload["dir"], "studio"), manifest, {},
                      session["originalPlan"], "UNWRITABLE_GUI_SNAPSHOT", None)
    candidate = build_new_plan(state, report)
    manifest_path = os.path.join(payload["dir"], "asset_manifest.json")
    blockers, warnings = gate_verdict(state, report, candidate, manifest_path)
    return {"candidate": candidate, "blockers": blockers, "warnings": warnings}


def main() -> None:
    """Run a bounded read-only operation selected by the server, not user argv."""
    sys.path.insert(0, sys.argv[1])
    with open(sys.argv[2], encoding="utf8") as handle:
        payload = json.load(handle)
    try:
        result = baseline(payload) if payload["action"] == "baseline" else diff(payload)
        print(json.dumps(result, allow_nan=False))
    except (ValueError, KeyError, TypeError, OSError, RuntimeError) as error:
        print(json.dumps({"blockers": [str(error)], "warnings": []}))


if __name__ == "__main__":
    main()

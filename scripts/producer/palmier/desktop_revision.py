"""Render and bind multi-element incremental Desktop Palmier revisions."""
from __future__ import annotations

import os
from dataclasses import dataclass

from fingerprints import file_sha256, plan_content_hash
from graphics.graphics_render import (
    render_entry_at_rate as render_entry,
    timeline_padded_entry,
)
from motion.recompose import requires_recompose
from palmier.desktop_text import text_entry
from palmier.mcp_client import PalmierError
from palmier.presenter_asset import PresenterRequest, fill_presenter_entry
from palmier.presenter_asset import primary_source
from palmier.revision_diff import RevisionDiffInput, build_revision
from palmier.revision_schema import read_revision
from palmier.revision_schema import stable_digest, validate_revision
from palmier.scene_binding_revision import (
    is_scene_binding_operation,
    prepare_scene_binding_steps,
)

MAX_PAGE_MUTATIONS = 24


@dataclass(frozen=True)
class DesktopRevisionContext:
    """Runtime facts required to materialize one revision set."""

    plan: dict
    fps: float
    total_frames: int
    cache_dir: str
    source: dict
    ledger: dict


def _elements(context: DesktopRevisionContext) -> dict[str, dict]:
    ledger = context.ledger
    if not isinstance(ledger, dict) or ledger.get("schemaVersion") not in {1, 2}:
        raise PalmierError("incremental revision requires a current element ledger")
    rows = ledger.get("elements")
    if not isinstance(rows, dict):
        raise PalmierError("incremental revision element ledger is malformed")
    return rows


def _current(context: DesktopRevisionContext, operation: dict) -> dict:
    row = _elements(context).get(operation["elementId"])
    if not isinstance(row, dict) or row.get("status") != "current":
        raise PalmierError(
            f"revision element {operation['elementId']!r} has no current binding")
    version = row.get("version", 1)
    if version != operation.get("expectedVersion"):
        raise PalmierError(
            f"revision element {operation['elementId']!r} version is stale")
    return row


def _render(context: DesktopRevisionContext, operation: dict) -> dict:
    row = operation.get("after")
    if not isinstance(row, dict):
        raise PalmierError("graphic render operation has no after payload")
    if requires_recompose(row):
        raise PalmierError(
            "incremental graphic revision cannot change a presenter-recompose card")
    rendered = render_entry(
        timeline_padded_entry(row, context.fps),
        context.cache_dir, context.fps)
    rendered = fill_presenter_entry(PresenterRequest(
        context.plan, context.source, row, rendered, context.cache_dir))
    proof = rendered.get("proof")
    if not isinstance(proof, dict) or proof.get("schemaVersion") != 1:
        raise PalmierError(
            f"graphic {operation['elementId']!r} has no rendered asset proof")
    return {**rendered, "fileHash": file_sha256(rendered["path"])}


def _mutation_id(operation: dict, suffix: str) -> str:
    return f"{operation['operationId']}:{suffix}"


def _import(operation: dict, rendered: dict) -> dict:
    return {"op": "import", "key": f"revision:{operation['elementId']}",
            "path": rendered["path"], "fileHash": rendered["fileHash"],
            "elementId": operation["elementId"],
            "importName": operation["elementId"],
            "revisionOperationId": operation["operationId"],
            "mutationId": _mutation_id(operation, "import")}


def _frame_window(row: dict, fps: float) -> tuple[int, int]:
    return (round(float(row["outStart"]) * fps),
            round(float(row["outEnd"]) * fps))


def _placement(operation: dict, rendered: dict,
               context: DesktopRevisionContext) -> dict:
    after = operation["after"]
    start, end = _frame_window(after, context.fps)
    result = {
        "op": "add-overlay", "lane": "graphics",
        "elementId": operation["elementId"], "startFrame": start,
        "endFrame": end, "path": rendered["path"],
        "fileHash": rendered["fileHash"],
        "assetPath": rendered["path"], "assetHash": rendered["fileHash"],
        "sourceAnchor": operation.get("sourceAnchor"),
        "transform": {"width": 1.0, "height": 1.0,
                      "centerX": 0.5, "centerY": 0.5},
        "revisionOperationId": operation["operationId"],
        "mutationId": _mutation_id(operation, "place"),
    }
    if operation["action"] == "replace":
        current = _current(context, operation)
        _assert_delivery_format(current, rendered, operation["elementId"])
        result.update({"op": "replace-overlay",
                       "oldClipId": current["clipId"],
                       "oldMediaRef": current["mediaRef"],
                       "trackIndex": current["trackIndex"]})
    return result


def _assert_delivery_format(current: dict, rendered: dict, ident: str) -> None:
    old_path, new_path = current.get("assetPath"), rendered.get("path")
    if not isinstance(old_path, str) or not isinstance(new_path, str):
        raise PalmierError(f"graphic {ident!r} has no delivery-format receipt")
    if os.path.splitext(old_path)[1].lower() != os.path.splitext(new_path)[1].lower():
        raise PalmierError(
            f"graphic {ident!r} changed alpha/opaque delivery format")


def _remove(operation: dict, context: DesktopRevisionContext) -> dict:
    current = _current(context, operation)
    before = operation.get("before") or {}
    if operation["lane"] == "graphics" and requires_recompose(before):
        raise PalmierError("removing a presenter-recompose graphic needs a broader revision")
    return {"op": "remove-element", "lane": operation["lane"],
            "elementId": operation["elementId"], "clipId": current["clipId"],
            "revisionOperationId": operation["operationId"],
            "mutationId": _mutation_id(operation, "remove")}


def _move(operation: dict, context: DesktopRevisionContext) -> dict:
    current = _current(context, operation)
    before, after = operation.get("before") or {}, operation.get("after") or {}
    if requires_recompose(before) or requires_recompose(after):
        raise PalmierError("moving a presenter-recompose graphic needs a broader revision")
    start, end = _frame_window(after, context.fps)
    if end - start != current.get("endFrame") - current.get("startFrame"):
        raise PalmierError("duration-changing moves must render a replacement")
    return {"op": "move-element", "lane": operation["lane"],
            "elementId": operation["elementId"], "clipId": current["clipId"],
            "fromFrame": current["startFrame"], "toFrame": start,
            "toTrack": current["trackIndex"], "endFrame": end,
            "revisionOperationId": operation["operationId"],
            "mutationId": _mutation_id(operation, "move")}


def _native_text(operation: dict, context: DesktopRevisionContext) -> list[dict]:
    if operation["action"] == "remove":
        return [_remove(operation, context)]
    if operation["action"] == "add":
        entry = text_entry(operation["after"], context.fps,
                           context.total_frames)
        digest = stable_digest(entry)
        item = {"elementId": operation["elementId"], "textHash": digest,
                "entry": entry}
        return [{"op": "native-text-add", "lane": "nativeText",
                 "trackPolicy": "new-top-video-track", "items": [item],
                 "revisionOperationId": operation["operationId"],
                 "mutationId": _mutation_id(operation, "add-text")}]
    if operation["action"] != "update":
        raise PalmierError("native text supports add, update, or remove")
    return [_text_update(operation, context)]


def _text_update(operation: dict, context: DesktopRevisionContext) -> dict:
    current = _current(context, operation)
    before, after = operation.get("before"), operation.get("after")
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise PalmierError("native text update needs before and after payloads")
    changed = {key for key in set(before) | set(after)
               if before.get(key) != after.get(key)}
    if changed != {"text"} or not isinstance(after.get("text"), str):
        raise PalmierError("native text fast update currently supports copy only")
    return {"op": "native-text-update", "lane": "nativeText",
            "elementId": operation["elementId"], "clipId": current["clipId"],
            "content": after["text"],
            "revisionOperationId": operation["operationId"],
            "mutationId": _mutation_id(operation, "update-text")}


def _graphic(operation: dict, context: DesktopRevisionContext) -> list[dict]:
    action = operation["action"]
    if action == "remove":
        return [_remove(operation, context)]
    if action == "move":
        return [_move(operation, context)]
    if action not in {"add", "replace"}:
        raise PalmierError(f"unsupported incremental graphic action {action!r}")
    if action == "replace":
        _current(context, operation)  # reject stale work before opening renderer
    rendered = _render(context, operation)
    return [_import(operation, rendered), _placement(operation, rendered, context)]


def _pages(steps: list[dict]) -> list[dict]:
    pages: list[dict] = []
    for index in range(0, len(steps), MAX_PAGE_MUTATIONS):
        page_steps = steps[index:index + MAX_PAGE_MUTATIONS]
        page_index = len(pages)
        for row in page_steps:
            row["pageIndex"] = page_index
        pages.append({"index": page_index,
                      "mutationIds": [row["mutationId"] for row in page_steps]})
    return pages


def prepare_revision(revision: object,
                     context: DesktopRevisionContext) -> dict:
    """Materialize exact worklist steps for one validated revision set."""
    value = validate_revision(revision)
    expected = value.get("nextPlanHash")
    if expected is not None and expected != plan_content_hash(context.plan):
        raise PalmierError("Palmier revision targets a different next edit plan")
    scene_ops = [row for row in value["operations"]
                 if is_scene_binding_operation(row)]
    if scene_ops and (len(scene_ops) != 1 or len(value["operations"]) != 1):
        raise PalmierError(
            "scene replacement cannot carry extra revision operations")
    steps: list[dict] = prepare_scene_binding_steps(scene_ops[0], context) \
        if scene_ops else []
    for operation in ([] if scene_ops else value["operations"]):
        planner = _graphic if operation["lane"] == "graphics" else _native_text
        steps.extend(planner(operation, context))
    if not steps:
        raise PalmierError("Palmier revision produced no mutations")
    return {"revision": value, "steps": steps, "pages": _pages(steps)}


def _revision_value(inputs: object, project: dict,
                    old_plan: dict, plan: dict) -> dict:
    revision_path = getattr(inputs, "revision_path", None)
    revision = read_revision(revision_path) if revision_path else build_revision(
        RevisionDiffInput(old_plan, plan, project.get("elementLedger") or {},
                          str(project.get("expectedFingerprint") or "")))
    if revision.get("basePlanHash") != plan_content_hash(old_plan):
        raise PalmierError("Palmier revision belongs to a different base plan")
    expected = revision.get("baseCandidateFingerprint")
    if expected != project.get("expectedFingerprint"):
        raise PalmierError("Palmier revision belongs to a different candidate")
    if revision.get("nextPlanHash") != plan_content_hash(plan):
        raise PalmierError("Palmier revision belongs to a different next plan")
    return revision


def prepare_manifest_revision(inputs: object, native: object,
                              project: dict, cache: str) -> tuple:
    """Bridge Desktop manifest inputs into the isolated revision planner."""
    from palmier.checkpoint_inputs import read_json
    prior = project.get("plan") if isinstance(project, dict) else None
    prior_path = prior.get("path") if isinstance(prior, dict) else None
    if not isinstance(prior_path, str):
        raise PalmierError("incremental revision has no prior plan authority")
    old_plan = read_json(prior_path, "prior edit plan")
    revision = _revision_value(inputs, project, old_plan, native.plan)
    runtime = DesktopRevisionContext(
        native.plan, native.fps, round(native.duration_s * native.fps), cache,
        primary_source(native.manifest), project.get("elementLedger") or {})
    prepared = prepare_revision(revision, runtime)
    capability = {"mode": "incremental-revision", "approved": False,
                  "scope": "multi-element", "omissions": [],
                  "limitations": [],
                  "dependencies": revision.get("dependencies") or {}}
    return prepared["steps"], capability, prepared

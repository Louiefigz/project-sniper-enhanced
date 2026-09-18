#!/usr/bin/env python3
"""Compile a private scene review into one Desktop Palmier revision sidecar."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fingerprints import file_sha256, plan_content_hash  # noqa: E402
from graphics.scene_contract import canonical_json  # noqa: E402
from graphics.scene_package_contract import (  # noqa: E402
    load_scene_package,
    read_regular_json,
)
from palmier.desktop_hook_authority import validate_authority  # noqa: E402
from palmier.desktop_revision_progress import revision_complete  # noqa: E402
from palmier.desktop_state import load_state  # noqa: E402
from palmier.mcp_client import PalmierError  # noqa: E402
from palmier.revision_schema import write_revision  # noqa: E402
from palmier.scene_binding_revision import (  # noqa: E402
    SceneBindingRevisionInput,
    build_scene_binding_revision,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("previous_package")
    parser.add_argument("current_package")
    parser.add_argument("previous_render_receipt")
    parser.add_argument("current_render_receipt")
    parser.add_argument("review_receipt")
    parser.add_argument("--desktop-out-dir", required=True)
    parser.add_argument("--bundle-store")
    parser.add_argument("--next-plan")
    return parser


def _receipt(path: str, kind: str, label: str) -> dict:
    value = read_regular_json(os.path.abspath(path), label)
    receipt_hash = value.get("receiptHash")
    body = {key: item for key, item in value.items() if key != "receiptHash"}
    if value.get("kind") != kind or receipt_hash != hashlib.sha256(
            canonical_json(body)).hexdigest():
        raise PalmierError(f"{label} is stale or has the wrong kind")
    return value


def _bindings(receipt: dict, resolved: object, label: str) -> dict:
    expected = {
        "packageHash": resolved.package_hash,
        "sceneId": resolved.scene["sceneId"],
        "sceneVersion": resolved.scene["version"],
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise PalmierError(f"{label} binds another scene package")
    value = receipt.get("palmierBindings")
    if not isinstance(value, dict):
        raise PalmierError(f"{label} has no scene bindings")
    return value


def _desktop(out_dir: str) -> dict:
    state = load_state(os.path.abspath(out_dir))
    validate_authority(state)
    if state.get("pendingOperation"):
        raise PalmierError("scene revision cannot replace a pending operation")
    if state.get("stage") == "revision" and not revision_complete(state):
        raise PalmierError("the prior Desktop revision is incomplete")
    return state


def _review(
    path: str,
    previous: object,
    current: object,
    current_render: dict,
) -> dict:
    value = _receipt(path, "scene-unit-review-repair", "scene review receipt")
    expected = {
        "sceneId": current.scene["sceneId"],
        "previousPackageHash": previous.package_hash,
        "currentPackageHash": current.package_hash,
        "currentRenderReceiptHash": current_render["receiptHash"],
    }
    if any(value.get(key) != item for key, item in expected.items()):
        raise PalmierError("scene review receipt binds another repair")
    delta = value.get("bindingDelta")
    if not isinstance(delta, dict):
        raise PalmierError("scene review receipt has no binding delta")
    return delta


def run(argv: list[str] | None = None) -> dict:
    """Compile immutable authorities without connecting to or mutating Palmier."""
    args = _parser().parse_args(argv)
    store = os.path.abspath(args.bundle_store) \
        if args.bundle_store else None
    previous = load_scene_package(
        os.path.abspath(args.previous_package), store)
    current = load_scene_package(
        os.path.abspath(args.current_package), store)
    old_render = _receipt(
        args.previous_render_receipt, "scene-package-render",
        "previous scene render receipt")
    new_render = _receipt(
        args.current_render_receipt, "scene-package-render",
        "current scene render receipt")
    old_bindings = _bindings(old_render, previous, "previous scene render")
    new_bindings = _bindings(new_render, current, "current scene render")
    delta = _review(
        args.review_receipt, previous, current, new_render)
    state = _desktop(args.desktop_out_dir)
    old_plan = read_regular_json(state["plan"]["path"], "Desktop base plan")
    next_path = os.path.abspath(args.next_plan) \
        if args.next_plan else state["plan"]["path"]
    next_plan = read_regular_json(next_path, "Desktop next plan")
    revision = build_scene_binding_revision(SceneBindingRevisionInput(
        previous.scene, current.scene, old_bindings, new_bindings, delta,
        state.get("elementLedger"), state["expectedFingerprint"],
        plan_content_hash(old_plan), plan_content_hash(next_plan)))
    saved = write_revision(state["outDir"], revision)
    return {
        "schemaVersion": 1, "kind": "palmier-scene-revision-compile",
        "revisionSetId": revision["revisionSetId"],
        "path": saved["path"], "hash": file_sha256(saved["path"]),
        "nextPlanPath": next_path, "connectedPalmierMutationCount": 0,
    }


def main(argv: list[str] | None = None) -> int:
    try:
        result, code = run(argv), 0
    except (OSError, ValueError, RuntimeError) as exc:
        result = {"schemaVersion": 1, "ok": False,
                  "error": f"{type(exc).__name__}: {exc}"}
        code = 65
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())

"""Read-only SDK text proposals against explicit package and supplied treatment state."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from edit.exact_timing import PositiveRational
from graphics.scene_contract import SceneContractError, canonical_json, validate_scene
from graphics.scene_package_contract import (
    ResolvedScenePackage, load_scene_package, read_regular_json,
)
from headless.process_runner import ProcessRequest, run_text
from headless.safe_source_files import PinnedSourceRoot
from planner.treatment_models import TreatmentState
from planner.treatment_operations import apply_treatment_operation

_ROOT = Path(__file__).resolve().parents[3]
_SDK = _ROOT / "scripts/producer/studio/sdk_scene_variable_proposal.mjs"
_MAX_INPUT = 1024 * 1024
_MAX_OUTPUT = 64 * 1024
_STATE_KEYS = {"plan", "scenes", "fps", "total_frames"}
_FLAGS = {"proposalOnly": True, "applied": False, "approved": False,
          "renderVerified": False, "suppliedBindingsOnly": True}


def _hash(value: object) -> str:
    """Hash canonical supplied JSON, not raw file spelling or approval evidence."""
    return hashlib.sha256(canonical_json(value)).hexdigest()


def add_text_proposal_arguments(parser: argparse.ArgumentParser) -> None:
    """Share the same explicit proposal-only command on both existing CLI surfaces."""
    parser.description = (
        "Propose declared text using installed SDK; no apply, approval, HTML save or render. "
        "State is caller-supplied TreatmentState JSON, not live project authority.")
    parser.add_argument("package_path", help="absolute original ScenePackageV1 file")
    parser.add_argument("--bundle-store", required=True)
    parser.add_argument("--state", required=True,
                        help="absolute JSON: plan, scenes, fps, total_frames")
    parser.add_argument("--expected-package-hash", required=True,
                        help="SHA256 of canonical original package JSON")
    parser.add_argument("--expected-state-hash", required=True,
                        help="SHA256 of canonical complete supplied state JSON")
    parser.add_argument("--unit-id", required=True)
    parser.add_argument("--element-id", required=True)
    parser.add_argument("--variable", required=True)
    parser.add_argument("--expected-text", required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--expected-scene-version", required=True, type=int)


def _state(value: dict, scene: dict) -> TreatmentState:
    """Load the complete supplied state and require its exact resolved target scene."""
    if set(value) != _STATE_KEYS or not isinstance(value["plan"], dict) \
            or not isinstance(value["scenes"], list) or not 1 <= len(value["scenes"]) <= 256:
        raise SceneContractError("supplied TreatmentState has invalid closed fields")
    fps = PositiveRational.from_value(value["fps"])
    count = value["total_frames"]
    if type(count) is not int or not 0 < count <= 2**53 - 1:
        raise SceneContractError("supplied state needs positive exact total_frames")
    scenes = tuple(validate_scene(row) for row in value["scenes"])
    ids = [row["sceneId"] for row in scenes]
    target = [row for row in scenes if row["sceneId"] == scene["sceneId"]]
    if len(ids) != len(set(ids)) or len(target) != 1 \
            or canonical_json(target[0]) != canonical_json(scene):
        raise SceneContractError("supplied state does not bind the exact package scene")
    if any(row["timing"]["fps"] != fps.to_dict()
           or row["timing"]["endFrameExclusive"] > count for row in scenes):
        raise SceneContractError("supplied scene timing leaves the state clock")
    return TreatmentState(value["plan"], scenes, fps, count)


def _operation(args: argparse.Namespace, scene: dict) -> dict:
    """Build only the existing closed title operation, with caller preconditions."""
    return {"schemaVersion": 1, "operation": "title.setText",
            "sceneId": scene["sceneId"], "elementId": args.element_id,
            "variable": args.variable, "text": args.text,
            "expectedText": args.expected_text,
            "expectedSceneVersion": args.expected_scene_version}


def _input(args: argparse.Namespace, resolved: ResolvedScenePackage) -> dict:
    """Read the actual selected bundle unit; source HTML is never executed or written."""
    bundle, scene = resolved.bundle, resolved.scene
    if bundle is None:
        raise SceneContractError("SDK text proposal requires a project scene bundle")
    units = [row for row in scene["renderUnits"] if row["unitId"] == args.unit_id]
    if len(units) != 1 or args.element_id not in units[0]["elementIds"]:
        raise SceneContractError("element does not belong to the exact requested unit")
    entry = units[0]["entry"]
    row = next(item for item in bundle.files if item["path"] == entry)
    if row["sizeBytes"] > 512 * 1024:
        raise SceneContractError("SDK unit HTML exceeds 512 KiB")
    with PinnedSourceRoot(bundle.path) as source:
        raw = source.read(entry)
        source.assert_current()
    if len(raw) != row["sizeBytes"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
        raise SceneContractError("original unit HTML differs from the captured bundle")
    return {"html": raw.decode("utf-8"), "originalHtmlSha256": row["sha256"],
            "scene": scene, "bundle": {"hash": bundle.digest,
            "manifest": bundle.manifest, "files": list(bundle.files)},
            "unitId": args.unit_id, "elementId": args.element_id,
            "variable": args.variable, "expectedValue": args.expected_text,
            "value": args.text, "expectedSceneVersion": args.expected_scene_version}


def _reject_constant(value: str) -> None:
    """Never accept JavaScript/Python non-JSON numeric extensions."""
    raise SceneContractError(f"SDK returned non-JSON constant {value}")


def _sdk(input_value: dict) -> dict:
    """Use existing bounded child cleanup with one exact temporary request reference."""
    raw = canonical_json(input_value)
    if not 0 < len(raw) <= _MAX_INPUT:
        raise SceneContractError("SDK proposal input exceeds 1 MiB")
    node = shutil.which("node")
    if node is None:
        raise SceneContractError("installed Node is required; no download is attempted")
    node = os.path.realpath(node)
    with tempfile.TemporaryDirectory(prefix="sniper-sdk-text-") as directory:
        path = os.path.join(os.path.realpath(directory), "request.json")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
        result = run_text(ProcessRequest(
            (node, str(_SDK), path, hashlib.sha256(raw).hexdigest(), str(len(raw))),
            "", str(_ROOT), {"PATH": os.path.dirname(node), "LANG": "C.UTF-8",
                             "TZ": "UTC"}, 30, max_output_bytes=_MAX_OUTPUT))
    if result.returncode != 0 or result.stderr:
        raise SceneContractError("installed SDK refused text proposal; nothing was applied")
    value = json.loads(result.stdout, parse_constant=_reject_constant)
    if not isinstance(value, dict):
        raise SceneContractError("SDK proposal output is not an object")
    return value


def _unchanged(args: argparse.Namespace, state_hash: str, package_hash: str) -> None:
    """Re-read supplied metadata after the child; this is freshness, not a publication lease."""
    if _hash(read_regular_json(args.state, "supplied treatment state")) != state_hash:
        raise SceneContractError("original supplied state changed during SDK proposal")
    current = load_scene_package(args.package_path, args.bundle_store)
    if current.package_hash != package_hash:
        raise SceneContractError("original package changed during SDK proposal")


def propose_text(args: argparse.Namespace) -> dict:
    """Validate one detached proposal without persisting the candidate or adopting authority."""
    resolved = load_scene_package(args.package_path, args.bundle_store)
    original = read_regular_json(args.state, "supplied treatment state")
    state_hash = _hash(original)
    if resolved.package_hash != args.expected_package_hash or state_hash != args.expected_state_hash:
        raise SceneContractError("stale expected package or supplied-state hash")
    state = _state(original, resolved.scene)
    operation = _operation(args, resolved.scene)
    candidate = apply_treatment_operation(state, operation)
    supplied = _input(args, resolved)
    result = _sdk(supplied)
    if canonical_json(result) != canonical_json({"operation": operation, **_FLAGS}):
        raise SceneContractError("SDK operation or proposal-only flags differ")
    _unchanged(args, state_hash, resolved.package_hash)
    scene = next(row for row in candidate.state.scenes if row["sceneId"] == resolved.scene["sceneId"])
    output = {"schemaVersion": 1, "kind": "scene-text-proposal", **result,
              "originalPackageHash": resolved.package_hash, "originalStateHash": state_hash,
              "originalHtmlSha256": supplied["originalHtmlSha256"],
              "candidateScene": scene, "operationReceipt": candidate.receipt}
    if len(canonical_json(output)) > _MAX_INPUT:
        raise SceneContractError("text proposal output exceeds 1 MiB")
    return output

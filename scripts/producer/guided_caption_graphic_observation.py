"""Owned opt-in observation through the existing sealed renderer and proof.

No cache hit, second renderer, image fallback or new work deadline is allowed.
Call only outside a parent SIGALRM phase: render_to owns its work timer and its
mandatory exact-container cleanup, while the original caller owns all work.
"""
from __future__ import annotations

import copy
import subprocess
import time
from fractions import Fraction
from pathlib import Path

from color.deadline import wall_budget, require_time
from cut_preview_io import digest, file_hash
from graphics.asset_proof import AssetProofRequest, prove_rendered_asset
from graphics.frame_quantization import hyperframes_duration
from guided_opening_graphic_proof import OpeningGraphicIntent, intent_record
from guided_caption_dependencies import Guard
from headless.container_policy import required_runtime
from headless.container_renderer import RenderRequest, render_to
from headless.render_layout_contract import (POLICY, PIPELINE_POLICY, closed, role_inventory,
                                             sealed_documents, sha, validate_request)
from headless.render_layout_read import LayoutReadExpectation, read_observation
from headless.render_layout_transport import approved_sources
from headless.runtime_receipt import bind_runtime_receipt

GRAPHIC_POLICY = "owned-sealed-agenda-caption-screen-v1"
PIPELINE_GRAPHIC_POLICY = "owned-sealed-pipeline-caption-screen-v1"


def native_observation_class(entry: dict) -> tuple[str, str, str] | None:
    """Two explicit native classes; no wildcard, inferred layout or style change."""
    if entry.get("anchor") != "own-screen" or type(entry.get("spec")) is not dict \
            or entry["spec"].get("layout") != "caption-safe-upper-v1":
        return None
    classes = {"agenda-slide": (GRAPHIC_POLICY, POLICY, "compositions/agenda-slide.html"),
        "module-pipeline": (PIPELINE_GRAPHIC_POLICY, PIPELINE_POLICY, "compositions/module-pipeline.html")}
    return classes.get(entry.get("kind"))


def graphic_policy(intent: dict) -> str:
    """Derive owner policy only from the separately held original entry."""
    selected = native_observation_class(intent["entry"])
    if selected is None:
        raise RuntimeError("graphic has no explicit supported native observation class")
    return selected[0]


def observed_execution_request(request: dict, intent: OpeningGraphicIntent) -> dict:
    """Declare this exact opt-in before spawn; keep historical requests untouched."""
    kinds = {"private-opening-ordinary-at-rate-oci": "private-opening-observed-at-rate-oci",
             "private-body-ordinary-at-rate-oci": "private-body-observed-at-rate-oci"}
    return {**request, "schemaVersion": 2, "kind": kinds[request["kind"]],
        "scope": "owned-native-caption-screen-not-approval", "captionLayoutPolicy": graphic_policy(intent_record(intent)),
        "layoutRequest": observation_request(intent_record(intent))}


def observation_request(intent: dict) -> dict:
    """Local animation clock derives only from the original absolute endpoints."""
    rate = Fraction(intent["frameRate"])
    frames = intent["endFrameExclusive"] - intent["startFrame"]
    if type(frames) is not int or intent["fullAnimationFrames"] != frames:
        raise RuntimeError("observed graphic lost its original full animation span")
    selected = native_observation_class(intent["entry"])
    if selected is None:
        raise RuntimeError("graphic has no explicit supported native observation class")
    return validate_request({"schemaVersion": 1, "profile": selected[1],
        "snapshotSha256": intent["snapshot"]["sha256"], "composition": selected[2],
        "frameRate": f"{rate.numerator}/{rate.denominator}", "totalFrames": frames,
        "width": intent["dimensions"][0], "height": intent["dimensions"][1]})


def _asset(intent: OpeningGraphicIntent, output: Path, html: str) -> dict:
    """Use the same full decode/copy/occupancy proof as ordinary own-screen assets."""
    frames = intent.row["endFrameExclusive"] - intent.row["startFrame"]
    proof = prove_rendered_asset(AssetProofRequest(str(output), intent.row["entry"], "mp4",
        intent.dimensions, hyperframes_duration(frames, intent.rate.numeric), intent.key,
        expected_fps=intent.rate.numeric, comp_html=html, sealed_asset_inputs=intent.snapshot.asset_bindings))
    return bind_runtime_receipt(str(output), proof)


def _returned_observation(returned: dict, proof: dict, output: Path) -> dict:
    """Bind sidecar evidence to the ACTUAL return, allowing only archive proof.

    The asset binder adds retainedInputArchive after independently checking the
    promoted archive. No other runtime field may differ from the live return.
    A new hash discovered on disk must never replace that held return.
    """
    runtime = proof.get("runtimeAttestation")
    if type(returned) is not dict or "retainedInputArchive" in returned \
            or type(runtime) is not dict or "retainedInputArchive" not in runtime \
            or digest({key: value for key, value in runtime.items()
                       if key != "retainedInputArchive"}) != digest(returned):
        raise RuntimeError("caption graphic runtime differs from actual renderer return")
    if returned.get("outputSha256") != proof["asset"]["sha256"]:
        raise RuntimeError("caption graphic media differs from actual renderer return")
    layout = returned.get("layoutObservation")
    if type(layout) is not dict:
        raise RuntimeError("caption graphic actual renderer omitted layout return")
    return {"path": str(output) + ".layout.json", "sha256": sha(layout.get("sha256"))}


def _verify_return(intent: OpeningGraphicIntent, output: Path, context: tuple) -> tuple[dict, dict]:
    """Read actual held return under the unchanged original proof deadline."""
    returned, request, documents, sources, runtime, deadline = context
    with wall_budget(deadline):
        proof = _asset(intent, output, documents["motion/" + request["composition"]].decode())
        metadata = {"schemaVersion": 1, "policy": graphic_policy(intent_record(intent)), "request": request,
            "observation": _returned_observation(returned, proof, output), "observerSources": sources}
        expected = LayoutReadExpectation(request, proof["asset"]["sha256"], metadata["observation"]["sha256"],
            file_hash(Path(str(output) + ".proof.json")), runtime.image_id, sources)
        _ref, observed = read_observation(str(output), expected, lambda: require_time(deadline))
        if observed["status"] != "observed":
            raise RuntimeError("actual native caption geometry remains unqualified")
        if approved_sources(required_runtime()) != sources:
            raise RuntimeError("actual caption observer source changed during render")
    return proof, metadata


def render_observed_graphic(intent: OpeningGraphicIntent, output: Path, context: tuple) -> tuple[dict, dict]:
    """One actual render under original time, with cleanup outside the work alarm."""
    clock, runtime, name = context
    started = time.monotonic()
    deadline = min(clock.end, started + runtime.timeout_seconds)
    event = {"stage": "actual-owned-caption-layout-graphic", "status": "failed"}
    try:
        clock.remaining()
        request = observation_request(intent_record(intent))
        with wall_budget(deadline):
            documents = sealed_documents(intent.snapshot, request)
            role_inventory(documents, request["profile"])
            sources = approved_sources(required_runtime())
        returned = copy.deepcopy(render_to(RenderRequest(request["composition"], "mp4", str(output), intent.snapshot,
                                name, intent.rate.token, request, deadline)))
        clock.remaining()
        proof, metadata = _verify_return(intent, output, (returned, request, documents, sources, runtime, deadline))
        clock.remaining()
        event["status"] = "complete"
        return {"path": str(output), "cached": False, "key": intent.key, "kind": intent.row["entry"]["kind"],
                "fmt": "mp4", "fps": intent.rate.token, "proof": proof}, metadata
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        event["error"] = str(error)
        raise
    finally:
        event["elapsedMs"] = round((time.monotonic() - started) * 1000)
        clock.events.append(event)


def read_graphic_observation(proof: dict, request: dict, guard: Guard) -> tuple[dict, dict]:
    """Reopen only actual result-held bytes, not a caller-created rectangle record."""
    metadata = closed(proof.get("captionLayoutObservation"),
        {"schemaVersion", "policy", "request", "observation", "observerSources"}, "caption graphic observation")
    expected = observation_request(request["intent"])
    policy = graphic_policy(request["intent"])
    if request.get("schemaVersion") != 2 or request.get("captionLayoutPolicy") != policy \
            or digest(request.get("layoutRequest")) != digest(expected) \
            or request.get("kind") not in ("private-opening-observed-at-rate-oci", "private-body-observed-at-rate-oci") \
            or request.get("scope") != "owned-native-caption-screen-not-approval":
        raise RuntimeError("caption geometry was not declared by the actual pre-spawn request")
    if type(metadata["schemaVersion"]) is not int or metadata["schemaVersion"] != 1 \
            or metadata["policy"] != policy or digest(metadata["request"]) != digest(expected):
        raise RuntimeError("caption graphic observation differs from the actual held execution request")
    raw = closed(metadata["observation"], {"path", "sha256"}, "caption raw layout reference")
    path = proof["actualAsset"]["path"]
    if raw["path"] != path + ".layout.json":
        raise RuntimeError("caption raw layout escaped its actually rendered asset")
    runtime = required_runtime()
    if runtime.image_id != request["imageId"] or metadata["observerSources"] != approved_sources(runtime):
        raise RuntimeError("caption observation runtime/source closure is stale")
    held = LayoutReadExpectation(expected, proof["actualAsset"]["sha256"], raw["sha256"],
        proof["proofSidecar"]["sha256"], request["imageId"], metadata["observerSources"])
    return read_observation(path, held, guard)

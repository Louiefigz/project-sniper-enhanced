"""Read actual held body graphic and pre-encode prefix execution evidence.

No new render, seal or oracle run is performed. The external stopped-worker
completion is required by the caller; these relational checks alone are not
execution authentication, human approval or an independent pixel observation.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from cut_preview_io import bound_json, digest
from graphics.composite_core import CompositeOptions
from graphics.owned_execution import GraphicsComposition, _composition_evidence
from guided_body_claim import body_registration_intent, body_resource_claim, body_resource_request
from guided_body_prefix import BodyPrefixBinding, body_prefix_request, body_prefix_metadata, body_prefix_captions
from guided_body_work import BodyWork
from guided_graphic_template import read_graphic_template
from guided_opening_frames import full_program_frames
from guided_opening_graphic_proof import verify_graphics_unchanged
from guided_opening_result import _graphic, held_ref
from headless.resource_ledger import registered_containers, removed_containers
from headless.runtime_receipt import validate_runtime_attestation
from opening_prefix_contract import HeldPrefixInput, canonical_hash
from guided_caption_layers import caption_page_clips
from guided_caption_screen_read import validate_graphic_request


def _graphic_request(proof: dict, row: dict, work: BodyWork) -> None:
    """Bind actual retained runtime to this activation and unchanged source intent."""
    root, control = work.control.root, work.control
    _graphic(proof, row, root)
    request = bound_json(Path(proof["requestPath"]), proof["requestSha256"])
    intent, actual = request["intent"], proof["actualProof"]
    template = read_graphic_template(row, work.inputs.documents["authority"]["frameRate"])
    expected = {"entry": row["entry"], "entryHash": row["entryHash"], "frameRate": template.rate.token,
        "startFrame": row["startFrame"], "endFrameExclusive": row["endFrameExclusive"],
        "fullAnimationFrames": template.frames, "dimensions": list(template.dimensions),
        "expectedCopy": list(template.copy), "expectedKey": proof["renderKey"]}
    if any(digest(intent[key]) != digest(value) for key, value in expected.items()):
        raise RuntimeError("body graphic request changed its exact original template/copy/frame intent")
    validate_graphic_request(request, proof, work.inputs.value["profile"], "body")
    if request["inputSha256"] != control.invocation.input_sha256 \
            or request["executionActivationSha256"] != control.invocation.activation_sha256 \
            or request["imageId"] != control.value["runtime"]["imageId"]:
        raise RuntimeError("body graphic request belongs to another activation or renderer class")
    path = Path(proof["actualAsset"]["path"])
    disk = bound_json(Path(proof["proofSidecar"]["path"]), proof["proofSidecar"]["sha256"])
    if digest(disk) != digest({key: item for key, item in actual.items() if key != "sidecar"}) \
            or actual.get("sidecar") != str(path) + ".proof.json":
        raise RuntimeError("body actual asset proof differs from its held sidecar")
    runtime = actual["runtimeAttestation"]
    if runtime["snapshotSha256"] != intent["snapshot"]["sha256"] \
            or digest(runtime["snapshotManifest"]) != digest(intent["snapshot"]["manifest"]) \
            or digest(actual["assetInputs"]) != digest(intent["snapshot"]["assetBindings"]) \
            or actual["copy"]["expected"] != expected["expectedCopy"]:
        raise RuntimeError("body graphic actual runtime lost its independently sealed input/copy")
    validate_runtime_attestation(runtime, str(path), proof["actualAsset"]["sha256"], request["imageId"])
    _graphic_cleanup(proof, request, row["order"], work)


def _graphic_cleanup(proof: dict, request: dict, order: int, work: BodyWork) -> None:
    """Read exact activation-derived ledger; never infer external process cleanup."""
    claim = body_resource_claim(work.control)
    resources = body_resource_request(claim, order)
    attempt = work.control.root / "graphics/attempts" / f"graphic-{order}"
    if digest(bound_json(attempt / "registration-intent.json")) != digest(body_registration_intent(claim, order)):
        raise RuntimeError("body graphic registration intent changed")
    name = request["containerName"]
    runtime = proof["actualProof"]["runtimeAttestation"]
    if proof["removedContainerNames"] != [name] or registered_containers(resources) \
            or removed_containers(resources) != (name,) \
            or runtime["containerBeforeOutput"]["Name"] != "/" + name \
            or runtime["containerAfterOutput"]["Name"] != "/" + name:
        raise RuntimeError("body graphic exact owned name/ledger cleanup differs")


def _prefix(record: dict, work: BodyWork) -> None:
    """Rebind graph, complete original range, asset inventory and retained output."""
    control, authority = work.control, work.inputs.documents["authority"]
    original = control.documents["openingResult"]
    composition = record["composition"]
    output = Path(composition["outputPath"])
    if not output.is_relative_to(control.root / "body-candidate") or output.name != "final.mp4":
        raise RuntimeError("body prefix encoded path escaped actual private assembly")
    value = GraphicsComposition(original["fullProgram"]["base"]["path"], str(output), tuple(record["resolvedClips"]),
        CompositeOptions(eof_pass=True, frame_rate=authority["frameRate"], video_only=True),
        (authority["target"]["width"], authority["target"]["height"]),
        (authority["frameRate"], authority["totalFrames"]),
        caption_page_clips(work.captions) if work.captions is not None else ())
    old_root = Path(control.documents["heldInput"]["opening"]["outputRoot"])
    binding = BodyPrefixBinding(work.inputs, original, old_root, work.captions)
    if "presenterLayouts" in work.inputs.documents["candidatePlan"] or "presenterLayers" in original["pictures"]:
        _presenter_prefix(record, work, value, binding)
        return
    _composition_evidence(composition, value)
    request, derivation = body_prefix_request(value, binding, record["graphics"])
    proof = composition["prefixOracle"]
    if digest(composition["originalGraphDerivation"]) != digest(derivation) \
            or proof["openingGraphHash"] != canonical_hash(list(request.opening_clips)):
        raise RuntimeError("body prefix differs from original approved opening graph")
    expected = {row.path: asdict(row) for row in (request.base, *request.assets)}
    for name in ("ffmpeg", "ffprobe"):
        tool = work.pipeline["opening"]["tools"][name]
        expected[tool["path"]] = {"path": tool["path"], "sha256": tool["sha256"],
                                  "size_bytes": Path(tool["path"]).stat().st_size}
    observed = proof["inputs"]
    if len(observed) != len(expected) or {row["path"]: row for row in observed} != expected:
        raise RuntimeError("body prefix input inventory differs from actual held assets")
    for role in ("core", "review"):
        row, span = proof["comparison"][role], getattr(request.ranges, role)
        if (row["startFrame"], row["endFrameExclusive"]) != span or row["exactPreencodePixels"] is not True \
                or row["frameCount"] != span[1] - span[0]:
            raise RuntimeError("body prefix omits the exact complete approved opening range")
    held_ref(composition["retainedPicture"], control.root, control.root / "picture-only.mp4")


def _presenter_tools(work: BodyWork) -> tuple[HeldPrefixInput, HeldPrefixInput]:
    """Use the initial dependency hash-pass sizes, not a later stat beside a claimed SHA."""
    work.guard()
    result = []
    for name in ("ffmpeg", "ffprobe"):
        expected = work.pipeline["opening"]["tools"][name]
        rows = [row for row in work.files if str(row.path) == expected["path"]]
        if not rows or any(row.sha256 != expected["sha256"] or row.identity != rows[0].identity for row in rows):
            raise RuntimeError("presenter body read tool lacks its original held dependency identity")
        result.append(HeldPrefixInput(expected["path"], expected["sha256"], rows[0].identity[5]))
    return tuple(result)


def _presenter_prefix(record: dict, work: BodyWork, value: GraphicsComposition, binding: BodyPrefixBinding) -> None:
    """Read actual saved schema2 evidence; never reconstruct a live body presenter owner."""
    from guided_presenter_body_read import PresenterBodyReadContext
    from guided_presenter_caption_body_read import verify_presenter_body_picture
    from guided_presenter_capture import PresenterCaptureContext, acquire_presenter_read_context

    work.guard()
    request, derivation = body_prefix_metadata(value, binding, record["graphics"])
    request, derivation = body_prefix_captions(request, value, binding, derivation)
    composition = record["composition"]
    if digest(composition["originalGraphDerivation"]) != digest(derivation):
        raise RuntimeError("presenter body prefix changed its original opening derivation")
    tools = _presenter_tools(work)
    acquisition = PresenterCaptureContext(work.pipeline["opening"]["tools"], str(work.control.root), work.clock, work.guard)
    with acquire_presenter_read_context(work.inputs, request.base, acquisition) as context:
        verify_presenter_body_picture(composition, request,
            PresenterBodyReadContext(context, binding.original_result["pictures"], tools), work.captions)
        held_ref(composition["retainedPicture"], work.control.root, work.control.root / "picture-only.mp4")
        work.guard()


def read_body_graphics(record: dict, work: BodyWork) -> None:
    """All full-plan rows and original assets must survive actual worker readback."""
    work.guard()
    rows = full_program_frames(work.inputs)
    if type(record["graphics"]) is not list or len(record["graphics"]) != len(rows) \
            or type(record["resolvedClips"]) is not list or len(record["resolvedClips"]) != len(rows):
        raise RuntimeError("body graphic evidence omitted or added full-plan rows")
    for row, proof in zip(rows, record["graphics"]):
        work.guard()
        _graphic_request(proof, row, work)
    _prefix(record, work)
    verify_graphics_unchanged(record["graphics"])
    work.guard()

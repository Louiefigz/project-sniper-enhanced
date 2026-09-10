"""Relate actual original caption/graphic bytes to a bounded screening report.

Called only beneath the opening/body owner's held completion/current-source
reader. No new seal, DOM observation, rendering or approval is performed.
"""
from __future__ import annotations

import hashlib
from fractions import Fraction
from pathlib import Path

from cut_preview_io import bound_json, digest
from graphics import graphics_render
from guided_caption_dependencies import Guard
from guided_caption_layout import ObservationReader
from guided_caption_profile import screened_caption_profile
from guided_graphic_template import read_graphic_template
from headless.source_closure import discover_root_sources


def _sources(row: dict, rate: str) -> tuple[dict, list[dict]]:
    """Bind current original template/dependencies, separate from transformed tar."""
    template = read_graphic_template(row, rate)
    ref = {"path": str(template.path), "sha256": template.sha256}
    data = discover_root_sources(template.html, graphics_render.MOTION_DIR)
    refs = [{"path": str(Path(graphics_render.MOTION_DIR) / name),
             "sha256": hashlib.sha256(raw).hexdigest()} for name, raw in sorted(data.items())]
    return ref, sorted([ref, *refs], key=lambda item: item["path"])


def _request(row: dict, proof: dict) -> dict:
    """The owner-held raw request retains original order, entry and full endpoints."""
    if proof.get("candidateOrder") != row["order"] or proof.get("graphicId") != row["graphicId"]:
        raise RuntimeError("caption screen actual graphic order/identity differs")
    request = bound_json(Path(proof["requestPath"]), proof["requestSha256"])
    intent = request["intent"]
    if intent["entryHash"] != row["entryHash"] or digest(intent["entry"]) != digest(row["entry"]) \
            or intent["startFrame"] != row["startFrame"] or intent["endFrameExclusive"] != row["endFrameExclusive"] \
            or intent["fullAnimationFrames"] != row["endFrameExclusive"] - row["startFrame"]:
        raise RuntimeError("caption screen graphic lost its exact original animation intent")
    return request


def validate_graphic_request(request: dict, proof: dict, profile: str, phase: str) -> None:
    """Keep ordinary request bytes unchanged; close the explicit new render class."""
    if phase not in ("opening", "body"):
        raise RuntimeError("unknown caption graphic owner phase")
    fields = {"schemaVersion", "kind", "scope", "containerName", "imageId", "build", "intent"}
    fields |= {"executionInputHash"} if phase == "opening" else {"inputSha256", "executionActivationSha256"}
    observed = "captionLayoutObservation" in proof
    version, render_class, scope = 1, "ordinary", "not-fixed30-presealed-v2-not-approval"
    if observed:
        if not screened_caption_profile(profile):
            raise RuntimeError("historical profile cannot own a new observed render request")
        from guided_caption_graphic_observation import graphic_policy, observation_request
        fields |= {"captionLayoutPolicy", "layoutRequest"}
        version, render_class, scope = 2, "observed", "owned-native-caption-screen-not-approval"
        if request.get("captionLayoutPolicy") != graphic_policy(request["intent"]) \
                or digest(request.get("layoutRequest")) != digest(observation_request(request["intent"])):
            raise RuntimeError("observed graphic request lost its exact local animation policy")
    if set(request) != fields or type(request["schemaVersion"]) is not int or request["schemaVersion"] != version \
            or request["kind"] != f"private-{phase}-{render_class}-at-rate-oci" or request["scope"] != scope:
        raise RuntimeError("graphic execution request has an unsupported renderer class")


def graphic_projection(context: tuple, row: dict, proof: dict, guard: Guard) -> tuple:
    """Native declarations never stand in for actual all-frame geometry."""
    from guided_caption_screen import supported_layout
    owner, clock = context
    guard()
    request = _request(row, proof)
    validate_graphic_request(request, proof, owner.inputs.value["profile"], owner.owner_phase)
    if owner.owner_phase == "opening" and request["executionInputHash"] != owner.inputs.value["executionInputHash"]:
        raise RuntimeError("caption observation belongs to another original opening input")
    if Fraction(request["intent"]["frameRate"]) != Fraction(clock["frameRate"]) \
            or request["intent"]["dimensions"] != [clock["width"], clock["height"]]:
        raise RuntimeError("caption graphic request lost original native clock/canvas")
    template, sources = _sources(row, clock["frameRate"])
    binding = {**clock, "graphicId": row["graphicId"], "entryHash": row["entryHash"],
        "specHash": digest(row["entry"].get("spec") or {}), "template": template, "sources": sources,
        "executionInputHash": owner.inputs.value["executionInputHash"],
        "graphicRequestHash": proof["requestSha256"], "graphicMediaSha256": proof["actualAsset"]["sha256"]}
    graphic = {"graphicId": row["graphicId"], "order": row["order"], "entryHash": row["entryHash"],
        "startFrame": row["startFrame"], "endFrameExclusive": row["endFrameExclusive"], "binding": binding}
    declaration = None
    if supported_layout(row, owner.inputs.documents["authority"]):
        declaration = _declaration(binding, request)
    guard()
    return graphic, declaration, request


def _declaration(binding: dict, request: dict) -> dict:
    """Policy-authored clear region + actual sealed role inventory, not observed ink."""
    from guided_caption_graphic_observation import observation_request
    from headless.container_io import SealedInput
    from headless.render_layout_contract import role_inventory, sealed_documents
    intent = request["intent"]
    ref = intent["snapshot"]
    snapshot = SealedInput(ref["path"], ref["sha256"], tuple(ref["manifest"]))
    local = observation_request(intent)
    roles = role_inventory(sealed_documents(snapshot, local), local["profile"])
    return {"schemaVersion": 1, "kind": "native-caption-layout-declaration", "binding": binding,
        "captionClearRect": [0, 600, 1920, 1080], "gutterPx": 16,
        "protectedRoles": [row["id"] for row in roles]}


def observation_reader(records: dict, guard: Guard) -> ObservationReader:
    """Return a live strong reader; no serialized supplied rectangle is accepted."""
    def read(binding: dict, declaration: dict) -> tuple[dict, dict] | None:
        from guided_caption_graphic_observation import read_graphic_observation
        from headless.render_layout_read import screening_envelopes
        guard()
        proof, request = records[binding["graphicId"]]
        if "captionLayoutObservation" not in proof:
            return None
        if binding["graphicRequestHash"] != proof["requestSha256"] \
                or binding["graphicMediaSha256"] != proof["actualAsset"]["sha256"]:
            raise RuntimeError("caption screening observation belongs to different held bytes")
        ref, observed = read_graphic_observation(proof, request, guard)
        if digest(bound_json(Path(proof["requestPath"]), proof["requestSha256"])) != digest(request):
            raise RuntimeError("caption screen original execution request changed during observation")
        intent = request["intent"]
        local = observed["request"]
        if local["frameRate"] != binding["frameRate"] or (local["width"], local["height"]) != (
                binding["width"], binding["height"]) \
                or local["totalFrames"] != intent["endFrameExclusive"] - intent["startFrame"]:
            raise RuntimeError("graphic-local observation cannot map onto the full-program clock")
        roles = screening_envelopes(observed)
        guard()
        return ref, {"schemaVersion": 1, "kind": "native-caption-layout-observation", "binding": binding,
            "declarationHash": digest(declaration), "startFrame": intent["startFrame"],
            "endFrameExclusive": intent["endFrameExclusive"], "framesObserved": observed["framesObserved"],
            "roles": roles}
    return read


def verify_screen(record: dict, context: object, guard: Guard) -> None:
    """Rebuild from original held files; never trust a serialized success label."""
    from guided_caption_screen import require_screen, screen_result
    expected = screen_result(context, record["graphics"], guard)
    if context is None:
        if "captionLayoutScreen" in record:
            raise RuntimeError("historical result acquired an unqualified caption screen")
        return
    if "captionLayoutScreen" not in record or digest(expected) != digest(record["captionLayoutScreen"]):
        raise RuntimeError("caption layout screen differs from original held dependencies")
    require_screen(expected)
    guard()

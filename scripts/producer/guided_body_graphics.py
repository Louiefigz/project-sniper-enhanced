"""Owned exact-rate body graphics through the ordinary renderer/compositor seams.

Every graphic gets a fresh private cache, independent expected seal and owned
resource ledger. First-version body reuse is the proved whole base/master only,
not a new cache authority. Prefix equality concerns actual pre-encode pixels;
complete encoded output and audio/QC remain the assembler/readback's work.
"""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from audio.assemble_publication import copy_verified
from cut_preview_io import digest, file_hash, write_new
from graphics.owned_execution import GraphicsComposition, OwnedGraphicsExecution
from guided_body_claim import body_registration_intent, body_resource_claim, body_resource_request
from guided_body_execution import BodyExecutionClock
from guided_body_inputs import BodyControl
from guided_body_prefix import BodyPrefixBinding, body_prefix_request
from guided_opening_graphic_proof import graphic_intent, intent_record, verify_graphic_result
from guided_opening_graphics import _proof_environment, _tools_environment, _render_asset, graphics_runtime
from guided_opening_inputs import OpeningInputs
from headless.render_runtime import current_render_build_manifest
from headless.resource_ledger import container_lease, registered_containers, removed_containers
from opening_prefix_composition import PrefixCompositionJob, compose_verified_prefix
from opening_prefix_contract import HeldPrefixInput, PrefixOracleRuntime
from guided_caption_execution import OwnedCaptionExecution
from guided_presenter_execution import OwnedPresenterExecution
from guided_presenter_caption_body_picture import (
    BodyPresenterCaptionContext, check_presenter_caption_body, check_presenter_caption_body_proof,
    finish_presenter_caption_body,
    hold_presenter_caption_body_proof, hold_presenter_caption_body_retained, prepare_presenter_caption_body,
)


@dataclass(frozen=True)
class BodyGraphicsContext:
    """Actual activated inputs and live guard, never a JSON-selected callback."""

    control: BodyControl
    inputs: OpeningInputs
    pipeline: dict
    clock: BodyExecutionClock
    guard: Callable[[], None]


def _render(row: dict, context: tuple) -> tuple[dict, dict]:
    """Register before spawn; do not put the mandatory ledger cleanup under an alarm."""
    state, runtime, claim, observe = context
    clock = state.clock
    attempt = state.control.root / "graphics/attempts" / f"graphic-{row['order']}"
    attempt.mkdir(mode=0o700)
    cache = attempt / "cache"
    cache.mkdir(mode=0o700)
    intent = clock.phase("body-graphic-intent-seal", lambda: graphic_intent(row, attempt,
        state.inputs.documents["authority"]["frameRate"]))
    resources = body_resource_request(claim, row["order"])
    build = clock.phase("body-graphic-build-before", lambda: current_render_build_manifest(runtime))
    write_new(attempt / "registration-intent.json", body_registration_intent(claim, row["order"]))
    with container_lease(resources) as name:
        request = {"schemaVersion": 1, "kind": "private-body-ordinary-at-rate-oci",
            "scope": "not-fixed30-presealed-v2-not-approval", "inputSha256": state.control.invocation.input_sha256,
            "executionActivationSha256": state.control.invocation.activation_sha256,
            "containerName": name, "imageId": runtime.image_id, "build": build, "intent": intent_record(intent)}
        if observe:
            from guided_caption_graphic_observation import observed_execution_request
            request = observed_execution_request(request, intent)
        path = attempt / "execution-request.json"
        write_new(path, request)
        held_sha = file_hash(path)
        with _proof_environment(name, runtime):
            result, observed = _render_asset(intent, cache, (clock, runtime, name, "body-actual-ordinary-at-rate-oci"), observe)
            proof = clock.phase("body-actual-graphic-proof", lambda: verify_graphic_result(result, intent,
                (runtime.image_id, name, state.pipeline["tools"])))
        if digest(clock.phase("body-graphic-build-after", lambda: current_render_build_manifest(runtime))) != digest(build) \
                or file_hash(path) != held_sha:
            raise RuntimeError("body graphic build/request changed during execution")
    if registered_containers(resources) or removed_containers(resources) != (name,):
        raise RuntimeError("body graphic exact container cleanup is unproved")
    evidence = {"graphicId": row["graphicId"], "candidateOrder": row["order"], "requestPath": str(path),
        "requestSha256": held_sha, "resourceLedgerPath": str(attempt / "resource-ledger.json"),
        "removedContainerNames": [name], "workerCleanupObserved": True, **proof}
    if observed is not None:
        evidence["captionLayoutObservation"] = observed
    return result, evidence


def _tool(row: dict) -> HeldPrefixInput:
    """Bind the actual pinned tool bytes, not an executable found from user input."""
    path = Path(row["path"])
    return HeldPrefixInput(str(path), row["sha256"], path.stat().st_size)


@dataclass
class BodyGraphicsOwner:
    """One sequential owned render/compose lifecycle; duplicate callbacks fail closed."""

    context: BodyGraphicsContext
    rows: list[dict]
    evidence: list[dict] = field(default_factory=list)
    composition: dict | None = None
    retained_picture: dict | None = None
    resolved_clips: tuple[dict, ...] | None = None
    captions: OwnedCaptionExecution | None = None
    screening: object = None
    observed_orders: set[int] = field(default_factory=set)
    caption_screen: dict | None = None
    presenter: OwnedPresenterExecution | None = None

    def render(self, entry: dict, order: int) -> dict:
        """Require exactly the next complete candidate entry, including unmodified copy."""
        state = self.context
        state.guard()
        if type(order) is not int or order != len(self.evidence) or order >= len(self.rows) \
                or digest(entry) != digest(self.rows[order]["entry"]):
            raise RuntimeError("body render callback changed, skipped or repeated its exact candidate entry")
        claim = body_resource_claim(state.control)
        runtime = graphics_runtime(state.inputs, state.pipeline, claim)
        with _tools_environment(runtime):
            result, proof = _render(self.rows[order], (state, runtime, claim, order in self.observed_orders))
        state.guard()
        self.evidence.append(proof)
        return result

    def compose(self, value: GraphicsComposition) -> dict:
        """Prove the actual graph prefix, encode once, retain exact picture before mux."""
        state = self.context
        state.guard()
        if self.composition is not None or len(self.evidence) != len(self.rows):
            raise RuntimeError("body compositor was repeated or lacks complete graphics")
        from guided_caption_screen import screen_result, require_screen
        self.caption_screen = screen_result(self.screening, self.evidence, state.guard)
        require_screen(self.caption_screen)
        record = state.control.documents["openingResult"]
        original_root = Path(state.control.documents["heldInput"]["opening"]["outputRoot"])
        binding = BodyPrefixBinding(state.inputs, record, original_root, self.captions.held if self.captions else None)
        request, derivation = body_prefix_request(value, binding, self.evidence)
        clearance = self._prepare_clearance(request, value)
        directory = state.control.root / "prefix-work"
        directory.mkdir(mode=0o700)
        tools = state.pipeline["tools"]
        runtime = PrefixOracleRuntime(_tool(tools["ffmpeg"]), _tool(tools["ffprobe"]),
            str(directory), min(900, state.clock.remaining()))
        check_presenter_caption_body(clearance)
        proof, held = state.clock.phase("body-prefix-and-picture-encode", lambda: self._compose_picture(
            PrefixCompositionJob(request, runtime, value.video_out, state.clock.remaining), clearance))
        retained, retained_hold = state.clock.phase("body-retain-picture-copy", lambda: self._retain_picture(value, proof, held))
        check_presenter_caption_body(clearance)
        state.guard()
        if self.captions is not None:
            self.captions.complete(value.video_out, proof)
        caption_clearance = finish_presenter_caption_body(retained_hold)
        self.retained_picture = retained
        self.resolved_clips = tuple(copy.deepcopy(value.clips))
        self.composition = {**proof, "originalGraphDerivation": derivation, "retainedPicture": retained}
        if caption_clearance is not None:
            self.composition["presenterCaptionClearance"] = caption_clearance
        return self.composition

    def _compose_picture(self, job: PrefixCompositionJob, clearance: object) -> tuple:
        """Hold the actual compositor return INSIDE the existing timed phase."""
        proof = compose_verified_prefix(job)
        return proof, hold_presenter_caption_body_proof(clearance, proof)

    def _retain_picture(self, value: GraphicsComposition, proof: dict, held: object) -> tuple:
        """Hold the actual copy before even a phase-exit or caption completion callback."""
        check_presenter_caption_body_proof(held)
        retained = self._retain(value, proof)
        return retained, hold_presenter_caption_body_retained(held, retained)

    def _prepare_clearance(self, request: object, value: GraphicsComposition) -> object:
        """Borrow the exact original body clock and detect owner replacement by callbacks."""
        state, captions, presenter = self.context, self.captions, self.presenter

        def guard() -> None:
            """Original phase authority remains live across actual encode and retention."""
            state.guard()
            state.clock.remaining()
            if self.context is not state or self.captions is not captions or self.presenter is not presenter:
                raise RuntimeError("body presenter caption live owner changed during composition")

        context = BodyPresenterCaptionContext(state.inputs, captions, presenter, guard)
        return prepare_presenter_caption_body(context, request, value, str(state.control.root / "picture-only.mp4"))

    def _retain(self, value: GraphicsComposition, proof: dict) -> dict:
        """A real streaming new copy; never retain a hardlink or relabel final A/V bytes."""
        path = self.context.control.root / "picture-only.mp4"
        expected = proof["output"]
        if os.path.lexists(path):
            raise RuntimeError("body retained picture already exists; no replacement is permitted")
        if expected["size_bytes"] > 2 * 1024 ** 3:
            raise RuntimeError("body retained picture exceeds the supported2GiB copy limit")
        copy_verified(Path(value.video_out), path, expected["sha256"])
        if file_hash(path) != expected["sha256"] or path.stat().st_size != expected["size_bytes"]:
            raise RuntimeError("body retained picture differs from the actual prefix encode")
        return {"path": str(path), "sha256": expected["sha256"], "sizeBytes": expected["size_bytes"]}

    def hooks(self) -> OwnedGraphicsExecution:
        """Only this live internal owner provides callbacks to the existing assembler."""
        return OwnedGraphicsExecution(self.render, self.compose, self.context.guard,
                                      captions=self.captions, presenter=self.presenter)

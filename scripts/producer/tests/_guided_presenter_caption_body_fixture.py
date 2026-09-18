"""Real tiny held files/live owners; native prefix and outer admission are TEST stubs.

The original caption projection, inspector, copy, caption support staging and
completion run normally. This fixture is NOT an isolated source admission,
actual pixel oracle, stopped-worker proof or release/approval qualification.
"""
from __future__ import annotations

from dataclasses import asdict
import os
from pathlib import Path
import stat
from types import SimpleNamespace
from unittest.mock import patch

from _guided_presenter_caption_picture_fixture import CaptionPictureFixture
from cut_preview_io import file_hash
from graphics.composite_core import CompositeOptions
from graphics.owned_execution import GraphicsComposition
from guided_body_graphics import BodyGraphicsContext, BodyGraphicsOwner
from guided_caption_execution import OwnedCaptionExecution
from guided_caption_layers import caption_page_clips, caption_prefix_request
from opening_prefix_contract import CompositorPrefixRequest, PrefixClock, PrefixRanges
from opening_prefix_graphs import graph_hash, graph_layer_policy, proof_header
from guided_presenter_probe_identity import presenter_stat_identity
from test_opening_prefix_contract import held


class BodyCaptionPictureFixture(CaptionPictureFixture):
    """One original rational 960-frame clock with real TEST caption support bytes."""

    def __init__(self) -> None:
        """Keep all writable output paths below this fixture's own canonical root."""
        super().__init__()
        self.output_root = self.root / "TEST-body-candidate"
        self.output_root.mkdir()
        self.output = self.output_root / "TEST-final-not-video.mp4"
        self.captions = OwnedCaptionExecution(self.held, self.guard)
        self.captions.stage(str(self.output))
        clock = PrefixClock(self.frame_rate, 960, 1080, 1920)
        request = CompositorPrefixRequest(held(self.base), (), (), (), clock,
            PrefixRanges((0, 60), (0, 120)), presenter=self.owner.prefix_graphs(120))
        self.request = caption_prefix_request(request, self.held)
        self.value = GraphicsComposition(str(self.base), str(self.output), (),
            CompositeOptions(eof_pass=True, video_only=True, frame_rate=self.frame_rate,
                             presenter=self.owner.full_graph()),
            (1080, 1920), (self.frame_rate, 960), caption_page_clips(self.held), self.owner)
        tool = asdict(self.runtime.ffprobe)
        control = SimpleNamespace(root=self.root, documents={"openingResult": {"TEST": "outer admission stub"},
            "heldInput": {"opening": {"outputRoot": str(self.root)}}})
        clock_owner = SimpleNamespace(remaining=self.probe.deadline.remaining, phase=self.phase)
        state = BodyGraphicsContext(control, self.inputs, {"tools": {"ffmpeg": tool, "ffprobe": tool}},
                                    clock_owner, self.guard)
        self.body = BodyGraphicsOwner(state, [], captions=self.captions, presenter=self.owner)
        self.last_proof = None

    def phase(self, name: str, operation: object) -> object:
        """Use the same original TEST deadline while recording actual control-flow order."""
        self.probe.deadline.remaining()
        self.events.append(name)
        result = operation()
        self.probe.deadline.remaining()
        return result

    def encode(self, job: object) -> dict:
        """Write plain TEST bytes, never launch an encoder or claim their pixel validity."""
        if job.output_path != str(self.output) or job.request is not self.request or self.output.exists():
            raise AssertionError("TEST native stub changed its exact new output/request")
        self.commands.append(job)
        self.output.write_bytes(b"TEST actual retained bytes, NOT a video or native prefix proof")
        proof = {**proof_header(self.request, composition=True),
            "scope": "executed-graph-bound-picture-not-decoded-output-or-approval",
            "outputPath": str(self.output), "output": {"path": str(self.output),
                "sha256": file_hash(self.output), "size_bytes": self.output.stat().st_size},
            "executedCommandHash": "e" * 64, "ordinaryPathCommandHash": "d" * 64,
            "outputTransport": "exclusively-reserved-held-regular-file-descriptor-mp4",
            "privateMoovPlacement": "end-of-file; faststart belongs to existing final delivery mux",
            "prefixOracle": {**proof_header(self.request), **graph_layer_policy(self.request),
                "status": "verified", "fullGraphHash": graph_hash(self.request, "full"),
                "openingGraphHash": graph_hash(self.request, "opening")},
            "elapsedMs": 0.0, "outputDecoded": False, "audioCompared": False, "deliveryApproved": False,
            "cleanupScope": "owned-runner-local-groups; caller-must-reconcile-external-ledger"}
        self.last_proof = proof
        return proof

    def render_body(self) -> dict:
        """Actual body seam/inspector/copy/completion; only prefix/admission leaves stubbed."""
        with patch("guided_body_graphics.body_prefix_request", return_value=(self.request, {"TEST": "derivation stub"})), \
                patch("guided_body_graphics.compose_verified_prefix", side_effect=self.encode):
            return self.body.compose(self.value)

    def mutate_owned(self, path: Path) -> None:
        """Fault only three explicit canonical TEST-owned regular single-link paths."""
        allowed = {self.output, self.root / "picture-only.mp4", Path(self.held.root) / "caption_pages.json"}
        if self.root.resolve(strict=True) != self.root or self.root.parent != Path("/private/tmp") \
                or not self.root.name.startswith("sniper-presenter-caption-TEST-") \
                or path not in allowed or path.resolve(strict=True) != path or not path.is_relative_to(self.root):
            raise AssertionError("TEST fault escaped exact owned root/inventory")
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_uid != os.getuid():
            raise AssertionError("TEST fault requires an owned regular single-link file")
        descriptor = os.open(path, os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            if presenter_stat_identity(os.fstat(descriptor)) != presenter_stat_identity(before):
                raise AssertionError("TEST fault descriptor changed before write")
            if os.write(descriptor, b"!") != 1:
                raise AssertionError("TEST fault write was incomplete")
        finally:
            os.close(descriptor)

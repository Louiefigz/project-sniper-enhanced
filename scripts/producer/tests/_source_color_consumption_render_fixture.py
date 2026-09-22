"""Composable actual lower hooks with explicit TEST native/output-proof leaves.

This does not produce media, admit a source, select a master, or construct a
qualified OpeningPreparation. Its returned master/picture records are TEST
observations around the actual cut/master/recorder control flow.
"""
from __future__ import annotations

from contextlib import ExitStack, nullcontext
from copy import deepcopy
from fractions import Fraction
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

from audio import master, render_audio_master as audio, audio_mix_picture
from audio.audio_mix_picture import PictureSource
from audio.render_audio_authority import AudioAdmission
from audio.render_audio_bus import SourceAudioBus
from edit.picture_lock_common import content_hash
import cut_speed as cut
import render


class SourceColorRenderFixture:
    """Borrow original actual source fixture/context; never create another owner or deadline."""

    def __init__(self, fixture: object, context: object) -> None:
        """Keep the exact original holder context and construct only its ordinary render args."""
        self.fixture, self.context = fixture, context
        self.ctx = fixture.render_context(context)
        self.picture = None
        self.sealed = None

    def cut_leaves(self, stack: ExitStack) -> dict:
        """Run real options/part builders while stubbing every native/probe observation."""
        Path(self.ctx.out_dir).mkdir(parents=True, exist_ok=True)
        paths = {row["path"]: None for row in self.ctx.manifest["sources"]}
        values = {"observe_cut_source_set": paths, "decide_profile": cut.Profile(1920, 1080, Fraction(24), "yuv420p"),
                  "_warn_off_profile": None, "run_ff": None, "_clamp_part_audio": 6,
                  "concat_parts": None, "probe_video_frames": 18, "probe_duration": .75,
                  "assert_cut_sources_stable": None, "cut_source_receipts": [], "emit": None}
        recorder = Mock()
        recorder.publish.return_value = {"TEST": "native leaves stubbed"}
        stack.enter_context(patch.object(cut, "execution_scope", return_value=nullcontext(recorder)))
        result = {name: stack.enter_context(patch.object(cut, name, return_value=value)) for name, value in values.items()}
        stack.enter_context(patch.object(render, "write_manifestation", side_effect=self.fixture.manifestation))
        stack.enter_context(patch.object(render, "probe_video", return_value={"r_frame_rate": "24/1"}))
        stack.enter_context(patch.object(render, "emit"))
        return result

    def observed(self, path: str, _duration: float) -> PictureSource:
        """Supply synthetic packet observations retaining the actual returned typed object."""
        rows = tuple((Fraction(index, 24), None, "SHA256:" + "d" * 64, "[]") for index in range(18))
        self.picture = PictureSource(path, "e" * 64, Fraction(1, 24), rows)
        return self.picture

    def mix(self, output: str, encoder: object) -> dict:
        """Call the actual audio/picture-copy coordinator, not its native runner or publisher."""
        result = encoder(output + ".TEST-candidate")
        return {**result, "delivery": {"TEST": "not qualified"}}

    def seal(self, _path: str, payload: dict) -> dict:
        """Return the publisher's exact semantics, without claiming a file was published."""
        self.sealed = {**deepcopy(payload), "receiptHash": content_hash(payload)}
        return self.sealed

    def bus(self) -> SourceAudioBus:
        """Shape-only audio admission/native facts remain explicit TEST fixture leaves."""
        self.ctx.audio_admission = AudioAdmission("TEST", "/TEST/manifest", "a" * 64, "b" * 64,
            (), {"ffmpeg": {"path": "/TEST-unopened/ffmpeg"}}, (), policy="source-float-v2")
        self.ctx.source_audio_bus = SourceAudioBus(self.ctx.out_dir + "/TEST-dialogue.wav", "a" * 64,
            36000, "24/1", 18, self.ctx.out_dir, {"receiptHash": "a" * 64}, self.ctx.audio_admission)
        return self.ctx.source_audio_bus

    def master_leaves(self, stack: ExitStack) -> dict:
        """Leave actual master and verify_picture_copy logic in place; open no source."""
        self.bus()
        stack.enter_context(patch.object(render, "probe_video_frames", return_value=18))
        stack.enter_context(patch.object(render, "invalidate_assembled_sidecar"))
        stack.enter_context(patch.object(master, "_run", return_value=subprocess.CompletedProcess([], 0, "", "")))
        stack.enter_context(patch.object(master.os.path, "isfile", return_value=True))
        values = {"verify_source_bus": None, "_observe_final_audio": ({}, 0, ""),
            "select_pass2_filter": master.MasterFilterSelection("TEST", None, {"TEST": True}),
            "run_audio": None, "_audio_clock": {},
            "file_sha256": "e" * 64, "finalize_master": {
                "status": "done", "out": self.ctx.out_dir + "/final.mp4", "warnings": []}}
        recorder = Mock()
        recorder.publish.return_value = {"TEST": "native leaves stubbed"}
        stack.enter_context(patch.object(cut, "execution_scope", return_value=nullcontext(recorder)))
        result = {name: stack.enter_context(patch.object(audio, name, return_value=value)) for name, value in values.items()}
        result["seal_audio_record"] = stack.enter_context(patch.object(audio, "seal_audio_record", side_effect=self.seal))
        stack.enter_context(patch.object(audio, "observe_picture_source", side_effect=self.observed))
        stack.enter_context(patch.object(audio, "render_qualified_mix", side_effect=self.mix))
        stack.enter_context(patch.object(audio_mix_picture, "file_sha256", return_value="e" * 64))
        stack.enter_context(patch.object(audio_mix_picture, "packet_signature", side_effect=lambda *_: self.picture.packets))
        return result

    def run(self) -> tuple:
        """Complete actual lower hooks; no generic-stage guard can replace them."""
        with ExitStack() as stack:
            cuts = self.cut_leaves(stack)
            source = render.cut_stage(self.ctx)
            masters = self.master_leaves(stack)
            result = render.master_stage(self.ctx, source, None)
        if cuts["run_ff"].call_count != 3 or masters["seal_audio_record"].call_count != 1:
            raise AssertionError("TEST actual lower dispatch omitted expected native/publication leaves")
        return source, result

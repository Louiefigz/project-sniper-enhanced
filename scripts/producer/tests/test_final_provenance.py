"""Producer-final provenance: canonical plan hash and byte authority."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import assemble as asm
import fingerprints as fpr
import render as renderer
from audio import music_stage
from palmier.sync import plan_content_hash as palmier_plan_hash
from tests._final_provenance_fixture import RenderOptions
from tests._final_provenance_fixture import plan as _plan


def _audio_stage(name: str, order: list[str] | None):
    def run(_ctx, video):
        if order is not None:
            order.append(name)
        return video
    return run


def _transition_stage(order: list[str] | None):
    def run(_ctx, video, _duration):
        if order is not None:
            order.append("transitions")
        return video
    return run


class PlanContentHashTests(unittest.TestCase):
    def test_matches_palmier_canonical_semantics(self) -> None:
        plan = _plan()
        self.assertEqual(fpr.plan_content_hash(plan), palmier_plan_hash(plan))
        self.assertEqual(len(fpr.plan_content_hash(plan)), 64)

    def test_ignores_counters_private_keys_ids_and_number_spelling(self) -> None:
        original = _plan()
        saved = copy.deepcopy(original)
        saved["planVersion"] = 99
        saved["_selection"] = {"anything": True}
        saved["graphicsTrack"][0]["id"] = "g-new"
        saved["cutTrack"][0]["end"] = 2
        self.assertEqual(fpr.plan_content_hash(original),
                         fpr.plan_content_hash(saved))

    def test_audio_and_music_policy_move_the_full_hash(self) -> None:
        plan = _plan()
        original = fpr.plan_content_hash(plan)
        plan["music"] = {"enabled": True, "path": "/bed.mp3"}
        self.assertNotEqual(fpr.plan_content_hash(plan), original)
        plan = _plan()
        plan["audioEnhance"] = {"preset": "voice-strong"}
        self.assertNotEqual(fpr.plan_content_hash(plan), original)


class AuthorityHashTests(unittest.TestCase):
    def test_streaming_file_hash_matches_sha256(self) -> None:
        payload = (b"producer-authority" * 100_000) + b"tail"
        with tempfile.TemporaryDirectory() as tmp:
            final = Path(tmp, "final.mp4")
            final.write_bytes(payload)
            self.assertEqual(fpr.file_sha256(str(final)),
                             hashlib.sha256(payload).hexdigest())

    def test_atomic_sidecar_preserves_existing_record_on_replace_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            final = Path(tmp, "final.mp4")
            final.write_bytes(b"new-final")
            sidecar = Path(fpr.assembled_sidecar_path(str(final)))
            sidecar.write_text('{"planHash":"old"}')
            with patch.object(fpr.os, "replace",
                              side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    fpr.write_assembled_sidecar(str(final), _plan())
            self.assertEqual(sidecar.read_text(), '{"planHash":"old"}')
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])


class StageReceiptTests(unittest.TestCase):
    def test_stage_fingerprint_moves_with_payload_or_input_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp, "source.mp4")
            source.write_bytes(b"source-v1")
            original = fpr.stage_fingerprint({"zoom": 1.1}, [str(source)])
            self.assertNotEqual(
                original,
                fpr.stage_fingerprint({"zoom": 1.2}, [str(source)]))
            source.write_bytes(b"source-v2")
            self.assertNotEqual(
                original,
                fpr.stage_fingerprint({"zoom": 1.1}, [str(source)]))

    def test_legacy_intermediate_rebuilds_until_receipt_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp, "punched.mp4")
            output.write_bytes(b"legacy-output")
            signature = "current-signature"
            self.assertFalse(fpr.stage_receipt_current(str(output), signature))
            fpr.write_stage_receipt(str(output), signature)
            self.assertTrue(fpr.stage_receipt_current(str(output), signature))
            self.assertFalse(fpr.stage_receipt_current(str(output), "stale"))


class AssembleProvenanceTests(unittest.TestCase):
    def _run(self, tmp: str, fail: bool = False) -> tuple[Path, dict | None]:
        final = Path(tmp, "final.mp4")
        base = Path(tmp, "base.mp4")
        final.write_bytes(b"prior")
        base.write_bytes(b"base")
        from test_base_reuse import bound_record
        fingerprint = Path(tmp, "base.fingerprint.json")
        fingerprint.write_text(json.dumps(bound_record(base, _plan())))
        job = asm.AssembleJob(str(base), _plan(), str(final), None,
                              fingerprint_path=str(fingerprint))

        def composite(_job: asm.AssembleJob) -> dict:
            if fail:
                raise RuntimeError("composite failed")
            final.write_bytes(b"assembled-authority")
            return {"passes": 1}

        with patch.object(asm, "_check_staleness"), \
                patch.object(asm, "_reuse_composite", return_value=False), \
                patch.object(asm, "_composite", side_effect=composite), \
                patch.object(music_stage, "apply_music", return_value=None), \
                patch.object(asm, "write_proxy", return_value=None):
            if fail:
                with self.assertRaisesRegex(RuntimeError, "composite failed"):
                    asm.assemble(job)
                return final, None
            return final, asm.assemble(job)

    def test_success_stamps_existing_and_full_authority_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            final, summary = self._run(tmp)
            sidecar = json.loads(Path(str(final) + ".assembled.json").read_text())
            self.assertEqual(set(sidecar), {"videoFingerprint",
                                            "graphicsFingerprint", "planHash",
                                            "authorityHash"})
            self.assertEqual(sidecar["planHash"], fpr.plan_content_hash(_plan()))
            self.assertEqual(sidecar["authorityHash"],
                             fpr.file_sha256(str(final)))
            self.assertEqual(summary["planHash"], sidecar["planHash"])

    def test_failed_assemble_leaves_no_stale_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            final = Path(tmp, "final.mp4")
            Path(str(final) + ".assembled.json").write_text('{"old":true}')
            self._run(tmp, fail=True)
            self.assertFalse(Path(str(final) + ".assembled.json").exists())


class RenderProvenanceTests(unittest.TestCase):
    def _render(
        self, tmp: str, options: RenderOptions | None = None,
    ) -> Path:
        config = options or RenderOptions()
        plan = _plan()
        ctx = renderer.RenderCtx(plan, {}, tmp, tmp,
                                 skip_graphics=config.skip_graphics)
        final = Path(tmp, "final.mp4")

        def master(spec) -> dict:
            if config.audio_order is not None:
                config.audio_order.append("master")
            if config.fail_master:
                raise RuntimeError("master failed")
            Path(spec.out).write_bytes(b"full-render-authority")
            return {"status": "done", "out": spec.out}

        simple = lambda _ctx, video: video

        patches = {
            "gate": lambda _ctx: None,
            "compile_stage": lambda _ctx: SimpleNamespace(
                output_duration=2.0, segments=[]),
            "cut_stage": lambda _ctx: "video",
            "channels_stage": _audio_stage("channels", config.audio_order),
            "baseline_stage": simple,
            "reframe_stage": simple,
            "punch_stage": simple,
            "broll_stage": simple,
            "overlays_stage": simple,
            "captions_stage": lambda *_args: None,
            "longform_sidecar_stage": lambda *_args: None,
            "graphics_track_stage": lambda _ctx, video, ass: (video, ass),
            "enhance_stage": _audio_stage("enhance", config.audio_order),
            "transitions_stage": _transition_stage(config.audio_order),
            "gain_stage": _audio_stage("gain", config.audio_order),
            "probe_video": lambda _path: {"r_frame_rate": "24/1"},
            "probe_video_frames": lambda _path: 48,
            "master": master,
        }
        with ExitStack() as stack:
            stack.enter_context(patch(
                "palmier_visual_bootstrap_authority.seal_palmier_visual_bootstrap",
                return_value={"receiptHash": "unit-fixture", "bootstrapArtifact": {"videoFrames": 48}}))
            for name, replacement in patches.items():
                stack.enter_context(patch.object(renderer, name, replacement))
            renderer.render(ctx, audit=False)
        return final

    def test_successful_full_render_stamps_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            final = self._render(tmp)
            sidecar = json.loads(Path(str(final) + ".assembled.json").read_text())
            self.assertEqual(sidecar["planHash"], fpr.plan_content_hash(_plan()))
            self.assertEqual(sidecar["authorityHash"],
                             fpr.file_sha256(str(final)))

    def test_base_render_does_not_claim_assembled_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            final = self._render(tmp, RenderOptions(skip_graphics=True))
            self.assertFalse(Path(str(final) + ".assembled.json").exists())

    def test_music_enabled_monolithic_render_cannot_claim_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = _plan()
            plan["music"] = {"enabled": True, "path": "/bed.mp3"}
            ctx = renderer.RenderCtx(plan, {}, tmp, tmp)
            Path(tmp, "final.mp4").write_bytes(b"missing-music-bed")
            with patch.object(renderer, "emit") as emitted:
                renderer._checkpoint_full_render(ctx)
            self.assertFalse(Path(tmp, "final.mp4.assembled.json").exists())
            self.assertEqual(emitted.call_args.kwargs["status"],
                             "final_provenance_skipped")

    def test_failed_master_invalidates_prior_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sidecar = Path(tmp, "final.mp4.assembled.json")
            sidecar.write_text('{"old":true}')
            with self.assertRaisesRegex(RuntimeError, "master failed"):
                self._render(tmp, RenderOptions(fail_master=True))
            self.assertFalse(sidecar.exists())

    def test_dead_channel_repair_precedes_every_audio_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            order: list[str] = []
            self._render(tmp, RenderOptions(audio_order=order))
        self.assertEqual(order, ["channels", "enhance", "transitions",
                                 "gain", "master"])

class MasterTimingContractTests(unittest.TestCase):
    def test_fractional_rate_reaches_master_without_integer_rounding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = renderer.RenderCtx(_plan(), {}, tmp, tmp)
            captured = []

            def master(spec):
                captured.append(spec)
                return {"status": "done", "out": spec.out}

            with patch.object(renderer, "probe_video",
                              return_value={"r_frame_rate": "24000/1001"}), \
                    patch.object(renderer, "probe_video_frames",
                                 return_value=240), \
                    patch.object(renderer, "master", side_effect=master):
                renderer.master_stage(ctx, "pre-master.mp4", None, 10.01)

        self.assertEqual(captured[0].fps, 24)
        self.assertEqual(captured[0].fps_exact, "24000/1001")
        self.assertEqual(captured[0].duration, 10.01)
        self.assertEqual(captured[0].frame_count, 240)


if __name__ == "__main__":
    unittest.main(verbosity=2)

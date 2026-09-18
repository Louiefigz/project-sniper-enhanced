"""CaptionTrackV1 integration with legacy render authority and Audit B."""
from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from audit.audit_captions import check_caption_authority
from captions.caption_authority import write_caption_artifacts
from captions.caption_assemble import (
    checkpoint_caption_free_composite,
    restore_caption_free_composite,
)
from captions.caption_plan_pipeline import (
    PlanCaptionContext,
    compile_plan_caption_track,
    validate_plan_caption_authority,
)
from captions.caption_words import CaptionFrameRate, stable_word_id
from captions.caption_shards import materialize_caption_shards
from compile_timeline import compile_plan
from fingerprints import (
    base_fingerprint,
    caption_fingerprint,
    plan_content_hash,
    write_assembled_sidecar,
)
from tests._caption_legacy_fixture import plan as _plan
from tests._caption_legacy_fixture import transcript as _transcript


class CaptionLegacyIntegrationTests(unittest.TestCase):
    def _compile(self, root: str, plan: dict) -> dict:
        transcript = os.path.join(root, "transcript.json")
        Path(transcript).write_text(json.dumps(_transcript()))
        manifest = {
            "_path": os.path.join(root, "manifest.json"),
            "sources": [{
                "id": "raw-a", "transcriptPath": transcript,
            }],
        }
        context = PlanCaptionContext(
            plan, manifest, compile_plan(plan), CaptionFrameRate(30_000, 1001),
            root)
        result = compile_plan_caption_track(context)
        self.assertIsNotNone(result)
        return result or {}

    def test_strict_track_compiles_all_outputs_from_one_generation(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            plan = _plan()
            compilation = self._compile(root, plan)
            shards = materialize_caption_shards(plan, compilation, root)
            artifacts = write_caption_artifacts(
                plan, compilation, root, shards.manifest)
            self.assertEqual(
                compilation["fps"],
                {"numerator": "30000", "denominator": "1001"})
            self.assertEqual(len(compilation["cues"]), 1)
            self.assertIn("Project Sniper works", Path(artifacts.srt).read_text())
            self.assertIn("cue-", Path(artifacts.ass).read_text())
            palmier = json.loads(Path(artifacts.palmier).read_text())
            self.assertEqual(palmier["kind"], "regenerable-alpha-captions")

    def test_explicit_caption_edit_never_invalidates_picture_base(self) -> None:
        plan = _plan()
        before_base = base_fingerprint(plan)
        before_caption = caption_fingerprint(plan)
        before_plan = plan_content_hash(plan)
        self.assertEqual(len(before_caption or ""), 64)
        changed = copy.deepcopy(plan)
        changed["captionsTrack"]["groups"][0]["placement"] = "top-center"
        self.assertEqual(base_fingerprint(changed), before_base)
        self.assertNotEqual(caption_fingerprint(changed), before_caption)
        self.assertNotEqual(plan_content_hash(changed), before_plan)
        repaired = copy.deepcopy(plan)
        repaired["dialogueCaptionAuthority"] = {
            "authorityHash": "a" * 64,
        }
        self.assertEqual(base_fingerprint(repaired), before_base)
        self.assertNotEqual(caption_fingerprint(repaired), before_caption)
        self.assertNotEqual(plan_content_hash(repaired), before_plan)

    def test_semantic_chapters_share_caption_timeline_and_authority(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            plan = _plan()
            plan["target"]["mode"] = "longform"
            plan["captions"]["burn"] = False
            plan["captionChapters"] = [{
                "chapterId": "chapter-intro", "title": "Intro",
                "wordId": stable_word_id("raw-a", 0),
            }, {
                "chapterId": "chapter-proof", "title": "Proof",
                "wordId": stable_word_id("raw-a", 2),
            }]
            compilation = self._compile(root, plan)
            artifacts = write_caption_artifacts(plan, compilation, root)
            self.assertIsNotNone(artifacts.chapters_json)
            self.assertEqual(
                Path(artifacts.chapters_text or "").read_text(),
                "0:00 Intro\n0:00 Proof\n")
            self.assertIn(
                "chapterProjectionHash", artifacts.receipt)
            self.assertEqual(
                set(artifacts.receipt["files"]) - {
                    "compilation", "ass", "srt", "palmier",
                },
                {"chaptersJson", "chaptersText"})

    def test_ghost_timed_text_array_remains_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "not a timed text array"):
            validate_plan_caption_authority({
                "captionsTrack": [{
                    "outStart": 0, "outEnd": 1, "text": "ghost",
                }],
            })

    def test_unused_or_non_rendering_style_authority_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            unused = _plan()
            unused["captionStyles"] = {
                "ghost": {"fill": "#ffffff"},
            }
            with self.assertRaisesRegex(ValueError, "unused styles"):
                self._compile(root, unused)
            malformed = _plan()
            malformed["captionStyles"] = {
                "karaoke": {"decorativeOnly": True},
            }
            with self.assertRaisesRegex(ValueError, "unknown fields"):
                self._compile(root, malformed)

    def test_caption_only_edit_reuses_proved_caption_free_composite(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            plan = _plan()
            base = os.path.join(root, "base.mp4")
            final = os.path.join(root, "final.mp4")
            Path(base).write_bytes(b"unchanged-base")
            Path(final).write_bytes(b"caption-free-graphics")
            job = SimpleNamespace(plan=plan, base=base, out=final)
            receipt = checkpoint_caption_free_composite(job)
            self.assertIsNotNone(receipt)
            replacement = os.path.join(root, "replacement.mp4")
            Path(replacement).write_bytes(b"old-captioned-final")
            os.replace(replacement, final)
            changed = copy.deepcopy(plan)
            changed["captionsTrack"]["groups"][0]["placement"] = "top-center"
            changed_job = SimpleNamespace(
                plan=changed, base=base, out=final)
            self.assertTrue(restore_caption_free_composite(changed_job))
            self.assertEqual(
                Path(final).read_bytes(), b"caption-free-graphics")
            changed["graphicsTrack"] = [{
                "id": "graphic-1", "kind": "stat-card",
                "outStart": 0, "outEnd": 1,
            }]
            self.assertFalse(restore_caption_free_composite(changed_job))

    def test_caption_free_cache_fails_closed_when_base_bytes_change(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            base = os.path.join(root, "base.mp4")
            final = os.path.join(root, "final.mp4")
            Path(base).write_bytes(b"base-a")
            Path(final).write_bytes(b"caption-free")
            job = SimpleNamespace(plan=_plan(), base=base, out=final)
            checkpoint_caption_free_composite(job)
            Path(base).write_bytes(b"base-b")
            self.assertFalse(restore_caption_free_composite(job))

    def test_audit_binds_final_and_detects_tampered_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            plan = _plan()
            compilation = self._compile(root, plan)
            shards = materialize_caption_shards(plan, compilation, root)
            artifacts = write_caption_artifacts(
                plan, compilation, root, shards.manifest)
            final = os.path.join(root, "final.mp4")
            Path(final).write_bytes(b"captioned-final")
            write_assembled_sidecar(final, plan)
            stale = copy.deepcopy(plan)
            stale["captionsTrack"]["groups"][0]["placement"] = "top-center"
            with self.assertRaisesRegex(
                    ValueError, "does not bind the current plan"):
                write_assembled_sidecar(final, stale)
            checks = check_caption_authority(root, plan)
            self.assertEqual([row.status for row in checks], ["pass"])
            Path(artifacts.srt).write_text("tampered")
            checks = check_caption_authority(root, plan)
            self.assertEqual([row.status for row in checks], ["fail"])
            self.assertIn("stale", checks[0].detail)

if __name__ == "__main__":
    unittest.main(verbosity=2)

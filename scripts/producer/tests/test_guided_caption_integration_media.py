"""Tiny actual shared caption/prefix/AAC/QC; no creative, speech or OCI approval."""
from __future__ import annotations

import io
import subprocess
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

import numpy as np
from PIL import Image

from _guided_caption_body_fixture import CaptionBodyFixture
from _guided_caption_integration_fixture import graphic, plan_for_profile, preparation
from assemble import AssembleJob, assemble
from audio.audio_mix_picture import packet_signature
from cut_preview_io import bound_json, digest, file_hash, write_new
from guided_body_result import observe_body_media, verify_body_media_files
from guided_caption_integration import read_prepared_captions
from guided_opening_picture import compose_ranges
from opening_prefix_contract import PrefixDeadline
from palmier.process_deadline import use_process_deadline


def _pixels(path: Path, frame: int, alpha: bool = False) -> np.ndarray:
    """Read an exact synthetic frame with no scaling or source mutations."""
    data = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"select=eq(n\\,{frame})",
        "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "pipe:1"],
        capture_output=True, timeout=15, check=True).stdout
    return np.asarray(Image.open(io.BytesIO(data)).convert("RGBA" if alpha else "RGB"))


class SharedCaptionActualMediaTests(unittest.TestCase):
    """Explicit TEST transcript/calibration bytes; production mechanism only."""

    def _run(self, short: bool) -> None:
        root = Path(tempfile.mkdtemp(prefix="sniper-shared-caption-", dir="/private/tmp"))
        print(f"TEST shared caption {'portrait karaoke' if short else 'landscape line'}: {root}", flush=True)
        started, clock = time.monotonic(), PrefixDeadline(180)
        try:
            self._execute(root, short, (started, clock))
        except Exception as error:
            write_new(root / "TEST-failure.json", {"status": "failed", "error": str(error),
                "scope": "synthetic-mechanical-fixture-not-authority", "elapsedSeconds": time.monotonic() - started})
            raise
        print(f"TEST shared caption completed: {time.monotonic() - started:.3f}s", flush=True)

    def _execute(self, root: Path, short: bool, timing: tuple) -> None:
        started, clock = timing
        with use_process_deadline(clock):
            inputs, output, prepared = preparation(root, short, clock.remaining)
            canvas = (1080, 1920) if short else (1920, 1080)
            asset, clip = graphic(root, canvas)
            tools = prepared.selection.master.source_bus.admission.tools
            original_sha = file_hash(prepared.base)
            projection = read_prepared_captions(prepared.evidence, inputs, prepared.base.parent, clock.remaining)
            self.assertEqual(projection, prepared.captions)
            picture = compose_ranges(prepared.base, [clip], (output, inputs.documents["authority"], tools), projection)
            body = CaptionBodyFixture(root / "body", prepared, (inputs, asset, clip, clock))
            job, result = body.execute()
            media = observe_body_media(body.root, inputs, prepared.selection,
                {"composition": body.composition, "programDeliveryReceipt": result["programDeliveryReceipt"], "captions": projection})
            verify_body_media_files(body.root, media)
            self._assertions((body, job, result, media), (picture, original_sha))
            write_new(root / "TEST-mechanical-evidence.json", {"TEST": "not speech/OCI/human approval",
                "profile": inputs.value["profile"], "preparation": prepared.evidence, "openingPicture": picture,
                "composition": body.composition, "media": media, "elapsedSeconds": time.monotonic() - started})

    def _assertions(self, values: tuple, original: tuple) -> None:
        body, job, result, media = values
        picture, original_sha = original
        self.assertEqual(media["final"]["frames"], 120)
        self.assertTrue(media["final"]["videoDecodeSucceeded"])
        self.assertEqual(media["programDelivery"]["samples"], 192192)
        self.assertEqual(media["programDelivery"]["audiblePathAacEncodes"], 1)
        self.assertFalse(media["programDelivery"]["approved"])
        self.assertEqual(file_hash(body.prepared.base), original_sha)
        self.assertFalse(result["preparationReuse"]["programRemastered"])
        self.assertEqual(packet_signature(str(body.root / "picture-only.mp4"), "v:0"), packet_signature(job.out, "v:0"))
        checks = {row["name"]: row["status"] for row in bound_json(Path(job.out).parent / "audit_report.json")["checks"]}
        self.assertEqual(checks["caption_authority"], "pass")
        self.assertNotIn("fail", checks.values())
        self.assertTrue(media["captionSupport"])
        self.assertEqual(picture["captionLayers"]["projectionHash"], body.prepared.captions.data_hash)
        oracle = body.composition["prefixOracle"]
        self.assertTrue(oracle["comparison"]["core"]["exactPreencodePixels"])
        self.assertTrue(oracle["comparison"]["review"]["exactPreencodePixels"])
        self.assertEqual(oracle["layerPolicy"]["fullCaptionTail"], len(body.owner.clips()))
        pixels = _pixels(Path(job.out), 8)
        region = pixels[pixels.shape[0] // 2:, pixels.shape[1] // 5:4 * pixels.shape[1] // 5]
        self.assertGreater(int(np.sum(np.max(region, axis=2) > 180)), 100,
                           "actual caption glyph pixels must survive the later-start opaque graphic")
        self.assertNotEqual(digest(result["captions"]), digest({"burned": False}))
        self._late_caption(body, Path(job.out))

    def _late_caption(self, body: CaptionBodyFixture, output: Path) -> None:
        """Actual later-body word survives beyond the entire opening review."""
        page = body.prepared.captions.data["pages"]["entries"][0]
        alpha = _pixels(Path(body.prepared.captions.root) / page["media"]["name"], 105 - page["startFrame"], True)
        mask = (alpha[:, :, 3] > 200) & (np.max(alpha[:, :, :3], axis=2) > 180)
        self.assertGreater(int(np.sum(mask)), 100)
        base, final = _pixels(body.prepared.base, 105), _pixels(output, 105)
        delta = np.abs(final.astype(np.int16) - base.astype(np.int16))
        self.assertGreater(float(np.mean(delta[mask])), 10,
                           "held late-caption glyph area must visibly differ from the caption-free base")

    def test_retired_fixture_plan_refused_before_any_media_or_output(self) -> None:
        """Historical kind metadata cannot revive the assembly execution path."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for short, retired in ((False, "statement-card"), (True, "kinetic-quote")):
                plan = plan_for_profile(short)
                plan["graphicsTrack"][0]["kind"] = retired
                job = AssembleJob(str(root / "missing-base.mp4"), plan,
                                  str(root / "must-not-exist.mp4"), None)
                with self.subTest(kind=retired), mock.patch("subprocess.run") as run:
                    with self.assertRaisesRegex(ValueError, "retired"):
                        assemble(job)
                run.assert_not_called()
                self.assertEqual(list(root.iterdir()), [])

    def test_landscape_line(self) -> None:
        self._run(False)

    def test_manual_portrait_karaoke(self) -> None:
        self._run(True)


if __name__ == "__main__":
    unittest.main(verbosity=2)

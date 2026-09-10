"""Actual 9:16 crop/base/prefix pixels; NOT speech, caption or creator approval."""
from __future__ import annotations

import copy
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from _cut_preview_fixture import ffmpeg
from _guided_manual_short_media import pixel_bands, preparation
from cut_preview_io import bound_json, digest, file_hash, write_new
from guided_opening_picture import observe_picture
from guided_short_geometry import capture_short_geometry, verify_short_geometry
from opening_prefix_composition import PrefixCompositionJob, compose_verified_prefix
from opening_prefix_contract import CompositorPrefixRequest, PrefixClock, PrefixOracleRuntime, PrefixRanges
from test_opening_prefix_contract import held
from test_opening_compositor_media import _clip


class ManualShortMediaTests(unittest.TestCase):
    """Actual local tools; fake ingest attestations and below-auth TEST invocation."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(tempfile.mkdtemp(prefix="sniper-manual-short-", dir="/private/tmp"))
        print(f"TEST manual-short mechanical evidence: {cls.root}", flush=True)
        started = time.monotonic()
        cls.inputs, cls.output, cls.prepared = preparation(cls.root)
        cls.tools = cls.prepared.selection.master.source_bus.admission.tools
        cls.base_root = cls.prepared.base.parent
        cls.preparation_ms = round((time.monotonic() - started) * 1000)
        write_new(cls.root / "TEST-preparation-evidence.json", cls.prepared.evidence)
        print(f"TEST ordinary short preparation: {cls.preparation_ms} ms", flush=True)

    def test_actual_crop_matches_displayed_source_pixels_and_full_frame_clock(self) -> None:
        evidence = self.prepared.evidence
        geometry = evidence["shortGeometry"]
        self.assertEqual(geometry["resolvedCrop"], [240, 0, 240, 270])
        self.assertEqual([geometry["sourceMetadata"][key] for key in ("displayWidth", "displayHeight")], [480, 270])
        self.assertEqual(geometry["baseArtifact"], evidence["base"])
        self.assertEqual(evidence["base"]["frames"], 60)
        self.assertEqual((evidence["base"]["width"], evidence["base"]["height"]), (1080, 1920))
        self.assertFalse(geometry["captionsBurned"])
        self.assertFalse(geometry["subjectFramingReviewed"])
        top, bottom = pixel_bands(self.prepared.base)
        self.assertGreater(top[1], 100)
        self.assertLess(max(top[0], top[2]), 40)
        self.assertGreater(bottom[2], 200)
        self.assertLess(max(bottom[0], bottom[1]), 40)

    def test_geometry_reopens_actual_trace_and_artifacts_without_plan_mutation(self) -> None:
        before = copy.deepcopy(self.inputs.documents)
        verify_short_geometry(self.prepared.evidence, self.inputs, self.base_root, self.prepared.selection)
        self.assertEqual(self.inputs.documents, before)
        self.assertEqual(file_hash(self.inputs.path), self.inputs.sha256)
        self.assertEqual(self.prepared.selection.master.receipt["totalSamples"], 96096)

    def test_geometry_projects_receipt_without_rounding_nanosecond_identity(self) -> None:
        geometry = self.prepared.evidence["shortGeometry"]
        reference = geometry["bootstrapReceipt"]
        original = bound_json(Path(reference["path"]), reference["sha256"])
        self.assertGreater(original["bootstrapArtifact"]["statSignature"]["mtimeNs"], 2 ** 53)
        with self.assertRaisesRegex(ValueError, "safe range"):
            digest(original["bootstrapArtifact"])
        self.assertEqual(set(geometry["reframedArtifact"]), {"path", "sha256", "sizeBytes", "videoFrames"})
        self.assertEqual(len(digest(geometry)), 64)
        self.assertEqual(file_hash(Path(reference["path"])), reference["sha256"])

    def test_self_consistent_claimed_crop_cannot_replace_actual_trace(self) -> None:
        inputs = copy.deepcopy(self.inputs)
        inputs.documents["candidatePlan"]["reframe"]["crop"] = [0, 0, 0.5, 1]
        with self.assertRaisesRegex(RuntimeError, "trace differs"):
            capture_short_geometry(inputs, self.base_root, self.prepared.selection, self.prepared.evidence["base"])
        evidence = copy.deepcopy(self.prepared.evidence)
        evidence["shortGeometry"]["resolvedCrop"][0] = 0
        with self.assertRaisesRegex(RuntimeError, "evidence changed"):
            verify_short_geometry(evidence, self.inputs, self.base_root, self.prepared.selection)

    def test_missing_and_changed_spec_artifact_fail_closed(self) -> None:
        import guided_short_geometry as geometry
        original = geometry.bound_json
        spec = Path(self.prepared.evidence["shortGeometry"]["specArtifact"]["path"])
        def changed(path, *args):
            value = original(path, *args)
            return {"layout": "fill", "crop": [0, 0, 0.5, 1]} if Path(path) == spec else value
        with patch.object(geometry, "bound_json", side_effect=changed):
            with self.assertRaisesRegex(RuntimeError, "executed crop spec changed"):
                verify_short_geometry(self.prepared.evidence, self.inputs, self.base_root, self.prepared.selection)
        evidence = copy.deepcopy(self.prepared.evidence)
        evidence.pop("shortGeometry")
        with self.assertRaisesRegex(RuntimeError, "evidence changed"):
            verify_short_geometry(evidence, self.inputs, self.base_root, self.prepared.selection)

    def test_actual_full_body_prefix_uses_same_held_cropped_base(self) -> None:
        output = self.output / "body-prefix"
        output.mkdir(mode=0o700)
        request = CompositorPrefixRequest(held(self.prepared.base), (), (), (),
            PrefixClock("30000/1001", 60, 1080, 1920), PrefixRanges((0, 4), (0, 8)))
        runtime = PrefixOracleRuntime(held(Path(self.tools["ffmpeg"]["path"])),
            held(Path(self.tools["ffprobe"]["path"])), str(output), 45)
        end = time.monotonic() + 45
        picture = output / "picture.mp4"
        proof = compose_verified_prefix(PrefixCompositionJob(request, runtime, str(picture), lambda: end - time.monotonic()))
        self.assertTrue(proof["prefixOracle"]["comparison"]["core"]["exactPreencodePixels"])
        self.assertTrue(proof["prefixOracle"]["comparison"]["review"]["exactPreencodePixels"])
        self.assertEqual(proof["prefixOracle"]["fullGraphHash"], proof["prefixOracle"]["openingGraphHash"])
        self.assertFalse(proof["deliveryApproved"])
        self.assertEqual(proof["prefixOracle"]["inputs"][0]["sha256"], self.prepared.evidence["base"]["sha256"])
        observed = observe_picture(picture, ("30000/1001", 60, (1080, 1920)), self.tools)
        self.assertEqual(observed["frames"], 60)
        top, bottom = pixel_bands(picture)
        self.assertGreater(top[1], 100)
        self.assertGreater(bottom[2], 200)
        write_new(output / "TEST-prefix-evidence.json", proof)
        print(f"TEST actual same-base portrait prefix/encode: {proof['elapsedMs']:.3f} ms", flush=True)

    def test_native_portrait_graphic_crosses_review_end_without_shortening_body(self) -> None:
        output = self.output / "crossing-graphic"
        output.mkdir(mode=0o700)
        asset = output / "TEST-native-translucent.mov"
        ffmpeg(["-f", "lavfi", "-i", "color=yellow:s=1080x1920:r=30000/1001:d=0.5,format=argb",
            "-vf", "colorchannelmixer=aa=0.5", "-frames:v", "12", "-c:v", "qtrle", str(asset)])
        clip = _clip(asset, (2, 14), "30000/1001")
        request = CompositorPrefixRequest(held(self.prepared.base), (held(asset),), (clip,), (clip,),
            PrefixClock("30000/1001", 60, 1080, 1920), PrefixRanges((0, 4), (0, 8)))
        runtime = PrefixOracleRuntime(held(Path(self.tools["ffmpeg"]["path"])),
            held(Path(self.tools["ffprobe"]["path"])), str(output), 45)
        end, picture = time.monotonic() + 45, output / "picture.mp4"
        proof = compose_verified_prefix(PrefixCompositionJob(request, runtime, str(picture), lambda: end - time.monotonic()))
        self.assertTrue(proof["prefixOracle"]["comparison"]["core"]["exactPreencodePixels"])
        self.assertTrue(proof["prefixOracle"]["comparison"]["review"]["exactPreencodePixels"])
        self.assertEqual(len(proof["prefixOracle"]["graphicWorkload"]["nativeVideoMetadata"]), 1)
        self.assertEqual(proof["prefixOracle"]["graphicWorkload"]["fullGraphInputPixels"], 2 * 1080 * 1920)
        observe_picture(picture, ("30000/1001", 60, (1080, 1920)), self.tools)
        crossing, later = pixel_bands(picture, 0.3), pixel_bands(picture, 0.6)
        self.assertGreater(crossing[0][0], 90, "graphic disappeared after review end8 before own end14")
        self.assertLess(later[0][0], 40, "graphic incorrectly persisted after exact half-open end14")
        self.assertGreater(later[0][1], 100)
        write_new(output / "TEST-prefix-evidence.json", proof)
        print(f"TEST native crossing portrait graphic prefix/encode: {proof['elapsedMs']:.3f} ms", flush=True)


class RotatedManualShortMediaTests(unittest.TestCase):
    """Real rotated stored landscape interpreted in displayed source coordinates."""

    def test_actual_rotated_source_crop_has_uniform_display_top_pixels(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="sniper-rotated-manual-short-", dir="/private/tmp"))
        print(f"TEST rotated short mechanical evidence: {root}", flush=True)
        inputs, output, prepared = preparation(root, rotated=True)
        geometry = prepared.evidence["shortGeometry"]
        metadata = geometry["sourceMetadata"]
        self.assertEqual([metadata["stream"][key] for key in ("width", "height")], [480, 270])
        self.assertEqual([metadata[key] for key in ("displayWidth", "displayHeight")], [270, 480])
        self.assertTrue(any(row.get("rotation") == 90 for row in metadata["stream"]["side_data_list"]))
        self.assertEqual(geometry["resolvedCrop"], [0, 0, 270, 240])
        expected = pixel_bands(Path(geometry["source"]["path"]))[0]
        for actual in pixel_bands(prepared.base):
            self.assertLess(max(abs(actual[index] - expected[index]) for index in range(3)), 12)
        self.assertEqual(prepared.evidence["base"]["frames"], 60)
        self.assertEqual((prepared.evidence["base"]["width"], prepared.evidence["base"]["height"]), (1080, 1920))
        verify_short_geometry(prepared.evidence, inputs, output / "full-program-base", prepared.selection)
        write_new(root / "TEST-preparation-evidence.json", prepared.evidence)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Palmier graphics carry production placement inside full-canvas media."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from fingerprints import file_sha256, video_fingerprint
from palmier.checkpoint_asset_authority import (
    bind_checkpoint_asset_authority,
    checkpoint_assets_current,
)
from palmier.checkpoint_graphics import (
    PlacementBakeContext,
    bake_rendered_graphic,
    current_placement_reference,
)
from palmier.checkpoint_graphics_cache import validate_placement_receipt
from palmier.checkpoint_inputs import CheckpointInput, checkpoint_inputs
from palmier.desktop_repair import RepairRenderContext, render_changed_graphics
from palmier.mcp_client import PalmierError
from palmier.translate import TranslateRequest, translate
from planner.graphics_anchors import _clip_dims, _content_bbox


def _alpha_asset(directory: str, canvas: tuple[int, int]) -> dict:
    width, height = canvas
    path = os.path.join(directory, f"raw-{width}x{height}.mov")
    source = (
        f"color=c=black@0.0:s={width}x{height}:r=10:d=1,format=rgba,"
        "drawbox=x=10:y=20:w=20:h=20:color=red@1:t=fill:replace=1"
    )
    command = [
        "ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi",
        "-i", source, "-frames:v", "10", "-an", "-c:v", "prores_ks",
        "-profile:v", "4444", "-pix_fmt", "yuva444p10le", path,
    ]
    subprocess.run(command, check=True, capture_output=True)
    proof = {"schemaVersion": 1, "asset": {
        "sha256": file_sha256(path), "width": width, "height": height,
        "durationS": 1.0, "frameCount": 10, "fps": 10,
    }}
    with open(path + ".proof.json", "w", encoding="utf-8") as handle:
        json.dump(proof, handle)
    return {"path": path, "proof": proof, "kind": "synthetic", "fmt": "mov"}


def _entry(point: tuple[int, int], text: str = "Before") -> dict:
    return {
        "id": "graphic-1", "kind": "checkpoint-transition-white-flash",
        "anchor": "free-band", "outStart": 0, "outEnd": 1,
        "placement": {"x": point[0], "y": point[1]},
        "spec": {"text": text},
    }


class FullCanvasPlacementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _bake(self, authored: tuple, delivery: tuple,
              point: tuple) -> dict:
        rendered = _alpha_asset(self.tmp.name, authored)
        context = PlacementBakeContext(
            self.tmp.name, 10, delivery[0], delivery[1])
        return bake_rendered_graphic(_entry(point), rendered, context)

    def _assert_bbox(self, result: dict, expected: tuple) -> None:
        found = _content_bbox(result["path"])
        for observed, wanted in zip(found, expected):
            self.assertLessEqual(abs(observed - wanted), 2)

    def test_9x16_asset_bakes_scaled_offset_then_uses_identity(self):
        result = self._bake((90, 160), (180, 320), (30, 40))
        self.assertEqual(_clip_dims(result["path"]), (180, 320))
        self._assert_bbox(result, (60, 80, 100, 120))
        receipt = validate_placement_receipt(result["path"])
        self.assertEqual(receipt["placement"]["x"], 40)
        self.assertEqual(receipt["placement"]["y"], 40)
        plan = {"target": {"mode": "short"},
                "cutTrack": [{"sourceId": "src", "start": 0, "end": 1}],
                "graphicsTrack": [_entry((30, 40))]}
        request = TranslateRequest(
            10, "/source.mp4", {0: result["path"]}, "portrait",
            180, 320, normalize_graphics_to_canvas=True)
        overlay = next(row for row in translate(plan, request)
                       if row["op"] == "overlays")
        self.assertEqual(overlay["entries"][0]["transform"], {
            "width": 1.0, "height": 1.0,
            "centerX": 0.5, "centerY": 0.5,
        })

    def test_16x9_asset_bakes_scaled_offset(self):
        result = self._bake((160, 90), (320, 180), (50, 20))
        self.assertEqual(_clip_dims(result["path"]), (320, 180))
        self._assert_bbox(result, (100, 40, 140, 80))
        receipt = validate_placement_receipt(result["path"])
        self.assertEqual(receipt["placement"]["x"], 80)
        self.assertEqual(receipt["placement"]["y"], 0)

    def test_receipt_tamper_quarantines_and_rebuilds(self):
        rendered = _alpha_asset(self.tmp.name, (90, 160))
        context = PlacementBakeContext(self.tmp.name, 10, 180, 320)
        first = bake_rendered_graphic(_entry((30, 40)), rendered, context)
        receipt_path = first["path"] + ".placement.json"
        with open(receipt_path, encoding="utf-8") as handle:
            tampered = json.load(handle)
        tampered["placement"]["x"] = 999
        with open(receipt_path, "w", encoding="utf-8") as handle:
            json.dump(tampered, handle)
        second = bake_rendered_graphic(_entry((30, 40)), rendered, context)
        self.assertFalse(second["cached"])
        self.assertEqual(second["receipt"]["placement"]["x"], 40)
        rejected = [name for name in os.listdir(self.tmp.name)
                    if ".rejected-" in name]
        self.assertEqual(len(rejected), 3)

    def test_asset_authority_detects_post_bake_media_drift(self):
        result = self._bake((160, 90), (320, 180), (50, 20))
        capability = bind_checkpoint_asset_authority(
            {}, [result["receipt"]])
        self.assertTrue(checkpoint_assets_current(capability))
        with open(result["path"], "ab") as handle:
            handle.write(b"tamper")
        self.assertFalse(checkpoint_assets_current(capability))

    def test_raw_proof_object_must_match_its_sidecar(self):
        rendered = _alpha_asset(self.tmp.name, (160, 90))
        rendered["proof"] = json.loads(json.dumps(rendered["proof"]))
        rendered["proof"]["asset"]["frameCount"] = 11
        context = PlacementBakeContext(self.tmp.name, 10, 320, 180)
        with self.assertRaisesRegex(PalmierError, "differs from its sidecar"):
            bake_rendered_graphic(
                _entry((50, 20)), rendered, context)

    def test_checkpoint_imports_the_baked_asset_not_raw_comp(self):
        rendered = _alpha_asset(self.tmp.name, (160, 90))
        plan = {"target": {"mode": "longform"},
                "cutTrack": [{"sourceId": "src", "start": 0, "end": 1}],
                "graphicsTrack": [_entry((50, 20))]}
        plan_path = os.path.join(self.tmp.name, "edit_plan.json")
        manifest_path = os.path.join(self.tmp.name, "asset_manifest.json")
        with open(plan_path, "w", encoding="utf-8") as handle:
            json.dump(plan, handle)
        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump({"sources": [{
                "id": "src", "role": "primary", "path": rendered["path"],
                "fps": 10, "resolution": [160, 90],
            }]}, handle)
        spec = CheckpointInput(
            self.tmp.name, plan_path, manifest_path, "plan", 0,
            cache_dir=self.tmp.name)
        state = {"projectName": "demo", "projectSettings": {
            "fps": 10, "width": 320, "height": 180,
        }}
        with patch("palmier.checkpoint_plan.render_entry",
                   return_value={**rendered, "cached": False, "key": "raw"}):
            _authority, steps, capability = checkpoint_inputs(spec, state)
        imported = next(row for row in steps
                        if row.get("key") == "gfx:0")
        self.assertNotEqual(imported["path"], rendered["path"])
        self.assertEqual(_clip_dims(imported["path"]), (320, 180))
        overlay = next(row for row in steps if row["op"] == "overlays")
        self.assertEqual(overlay["entries"][0]["transform"]["width"], 1.0)
        self.assertTrue(checkpoint_assets_current(capability))


class PlacementReferenceTests(unittest.TestCase):
    def test_only_current_delivery_sized_base_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = {"target": {"mode": "longform"},
                    "cutTrack": [{"sourceId": "src", "start": 0, "end": 1}]}
            base = os.path.join(directory, "base_final.mp4")
            with open(base, "wb") as handle:
                handle.write(b"base")
            with open(os.path.join(directory, "base.fingerprint.json"),
                      "w", encoding="utf-8") as handle:
                json.dump({"videoFingerprint": video_fingerprint(plan)}, handle)
            probe = type("Probe", (), {
                "width": 3840, "height": 2160, "duration": 1.0,
                "fps": 24.0, "vfr": False,
            })()
            with patch("palmier.checkpoint_graphics.probe_media",
                       return_value=probe):
                found = current_placement_reference(
                    directory, plan, (3840, 2160))
                self.assertEqual(found, (base, file_sha256(base)))
                self.assertIsNone(current_placement_reference(
                    directory, plan, (1920, 1080)))

    def test_face_aware_bake_without_current_base_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            rendered = _alpha_asset(directory, (90, 160))
            entry = {**_entry((30, 40))}
            entry.pop("placement")
            entry["faceBBoxNorm"] = [0.3, 0.2, 0.2, 0.2]
            context = PlacementBakeContext(directory, 10, 90, 160)
            with self.assertRaisesRegex(PalmierError, "graphics-free base"):
                bake_rendered_graphic(entry, rendered, context)

    def test_base_mutating_graphic_semantics_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            rendered = _alpha_asset(directory, (160, 90))
            context = PlacementBakeContext(directory, 10, 320, 180)
            entries = [
                {**_entry((50, 20)), "takeoverBase": "blur-desat"},
                {**_entry((50, 20)), "anchor": "focus-shift"},
                {**_entry((50, 20)), "kind": "module-takeover"},
            ]
            messages = ("takeoverBase", "focus-shift", "presenter PIP")
            for entry, message in zip(entries, messages):
                with self.subTest(message=message), self.assertRaisesRegex(
                        PalmierError, message):
                    bake_rendered_graphic(entry, rendered, context)


class ScopedRepairPlacementTests(unittest.TestCase):
    def test_changed_card_repair_keeps_baked_delivery_placement(self):
        with tempfile.TemporaryDirectory() as directory:
            rendered = _alpha_asset(directory, (160, 90))
            old = {"target": {"mode": "longform"},
                   "cutTrack": [{"sourceId": "src", "start": 0, "end": 1}],
                   "graphicsTrack": [_entry((50, 20), "Before")]}
            new = json.loads(json.dumps(old))
            new["graphicsTrack"][0]["spec"]["text"] = "After"
            context = RepairRenderContext(
                10, directory, {},
                PlacementBakeContext(directory, 10, 320, 180))
            with patch("palmier.desktop_repair.render_entry",
                       return_value=rendered):
                steps = render_changed_graphics(old, new, context)
            imported, overlays = steps
            self.assertNotEqual(imported["path"], rendered["path"])
            self.assertEqual(_clip_dims(imported["path"]), (320, 180))
            self.assertEqual(imported["placementReceiptHash"],
                             file_sha256(imported["placementReceiptPath"]))
            self.assertEqual(overlays["entries"][0]["transform"], {
                "width": 1.0, "height": 1.0,
                "centerX": 0.5, "centerY": 0.5,
            })
            receipt = validate_placement_receipt(imported["path"])
            self.assertEqual((receipt["placement"]["x"],
                              receipt["placement"]["y"]), (80, 0))


if __name__ == "__main__":
    unittest.main()

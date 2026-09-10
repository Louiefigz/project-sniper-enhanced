"""Scoped Palmier graphic repair and element-ledger contracts."""
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from fingerprints import file_sha256
from palmier.desktop_element_types import (ElementObservation,
                                           RecoveryObservation)
from palmier.desktop_elements import (bind_operation,
                                      observe_bound_operation,
                                      recover_bound_operation)
from palmier.desktop_repair import (RepairRenderContext,
                                    build_graphic_repair,
                                    render_changed_graphics)
from palmier.checkpoint_graphics import PlacementBakeContext
from palmier.desktop_authority import _receipt
from palmier.desktop_manifest import prepare_desktop_manifest
from palmier.desktop_state import DesktopStageInput
from palmier.mcp_client import PalmierError


def _plan(text="Before", start=1.0, cuts=None):
    return {
        "cutTrack": cuts or [{"sourceId": "src", "start": 0, "end": 10}],
        "graphicsTrack": [{"id": "graphic-1", "kind": "statement-card",
                           "outStart": start, "outEnd": 4.0,
                           "spec": {"text": text}}],
    }


def _clip(ident, media, start, end):
    return {"id": ident, "mediaRef": media, "frames": [start, end]}


def _timeline(*clips):
    return {"tracks": [{"id": "video", "clips": list(clips)}]}


def _ledger(asset_hash="old-hash"):
    return {"schemaVersion": 1, "elements": {"graphic-1": {
        "status": "current", "lane": "graphics", "clipId": "old-card",
        "mediaRef": "old-media", "assetHash": asset_hash,
        "assetPath": "/old.mov", "startFrame": 24, "endFrame": 96,
        "trackIndex": 0,
    }}}


class ScopedRepairPlanTests(unittest.TestCase):
    def setUp(self):
        self.steps = [
            {"op": "import", "key": "gfx:0", "path": "/new.mov",
             "fileHash": "new-hash", "elementId": "graphic-1"},
            {"op": "overlays", "entries": [{
                "mediaKey": "gfx:0", "elementId": "graphic-1",
                "stableIdentity": True, "startFrame": 24, "endFrame": 96,
                "assetPath": "/new.mov", "assetHash": "new-hash",
                "transform": {"width": 1.0, "height": 1.0,
                              "centerX": 0.5, "centerY": 0.5},
            }]},
        ]

    def test_text_change_emits_one_import_and_one_replacement(self):
        result = build_graphic_repair(
            _plan(), _plan("After"), self.steps, _ledger())
        self.assertEqual([row["op"] for row in result],
                         ["import", "replace-overlay"])
        replace = result[1]
        self.assertEqual(replace["oldClipId"], "old-card")
        self.assertEqual(replace["trackIndex"], 0)
        self.assertEqual((replace["startFrame"], replace["endFrame"]), (24, 96))

    def test_unchanged_asset_is_a_noop_even_if_plan_metadata_changed(self):
        with self.assertRaisesRegex(PalmierError, "no changed rendered"):
            build_graphic_repair(
                _plan(), _plan("After"), self.steps, _ledger("new-hash"))

    def test_timing_or_cut_change_cannot_hide_inside_card_repair(self):
        with self.assertRaisesRegex(PalmierError, "changed timing"):
            build_graphic_repair(
                _plan(), _plan("After", start=2.0), self.steps, _ledger())
        changed_cuts = [{"sourceId": "src", "start": 0, "end": 9}]
        with self.assertRaisesRegex(PalmierError, "timing/base lanes: cutTrack"):
            build_graphic_repair(
                _plan(), _plan("After", cuts=changed_cuts),
                self.steps, _ledger())

    def test_missing_stable_id_or_ledger_fails_closed(self):
        plan = _plan("After")
        plan["graphicsTrack"][0].pop("id")
        with self.assertRaisesRegex(PalmierError, "stable id"):
            build_graphic_repair(_plan(), plan, self.steps, _ledger())
        with self.assertRaisesRegex(PalmierError, "element ledger"):
            build_graphic_repair(_plan(), _plan("After"), self.steps, None)

    def test_alpha_to_opaque_format_change_requires_visual_rebuild(self):
        steps = json.loads(json.dumps(self.steps))
        steps[0]["path"] = "/new.mp4"
        with self.assertRaisesRegex(PalmierError, "delivery format"):
            build_graphic_repair(_plan(), _plan("After"), steps, _ledger())

    def test_long_plan_opens_only_the_changed_graphic_renderer(self):
        old, new = _plan(start=1.01), _plan("After", start=1.01)
        for index in range(2, 77):
            start = 5.0 + index * 4.0
            row = {"id": f"graphic-{index}", "kind": "statement-card",
                   "outStart": start, "outEnd": start + 3.0,
                   "spec": {"text": f"Unchanged {index}"}}
            old["graphicsTrack"].append(row)
            new["graphicsTrack"].append(json.loads(json.dumps(row)))
        rendered = {"path": "/changed.mov", "proof": {"schemaVersion": 1}}
        with patch("palmier.desktop_repair.render_entry",
                   return_value=rendered) as call, patch(
                       "palmier.desktop_repair.bake_rendered_graphic",
                       return_value=rendered), patch(
                       "palmier.desktop_repair.file_sha256",
                       return_value="f" * 64):
            context = RepairRenderContext(
                24, "/cache", {},
                PlacementBakeContext("/cache", 24, 1920, 1080))
            steps = render_changed_graphics(old, new, context)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args.args[0]["id"], "graphic-1")
        self.assertAlmostEqual(call.call_args.args[0]["outEnd"], 4.01)
        self.assertEqual(len(steps[1]["entries"]), 1)


class ElementLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.asset = os.path.join(self.tmp.name, "new.mov")
        with open(self.asset, "wb") as handle:
            handle.write(b"new-card")
        self.digest = file_sha256(self.asset)
        self.operations = os.path.join(self.tmp.name, "operations.json")
        self.state = {
            "stage": "repair", "operations": {"path": self.operations},
            "mediaLedger": {self.digest: {"mediaRef": "new-media"}},
            "elementLedger": _ledger(),
        }
        self._write_steps([
            {"op": "import", "key": "repair:graphic-1", "path": self.asset,
             "fileHash": self.digest, "elementId": "graphic-1"},
            {"op": "replace-overlay", "lane": "graphics",
             "elementId": "graphic-1", "oldClipId": "old-card",
             "oldMediaRef": "old-media", "trackIndex": 0,
             "startFrame": 24, "endFrame": 96, "path": self.asset,
             "fileHash": self.digest},
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def _write_steps(self, steps):
        with open(self.operations, "w", encoding="utf-8") as handle:
            json.dump({"steps": steps}, handle)

    def test_import_receipt_binds_hash_to_returned_media(self):
        args = {"source": {"path": self.asset}}
        binding = bind_operation("import_media", args, self.state)
        event = {"tool_response": {"content": [{
            "type": "text", "text": '{"mediaRef":"fresh-media"}'}]}}
        observe_bound_operation(ElementObservation(
            self.state, {"binding": binding}, _timeline(), _timeline(), event))
        self.assertEqual(self.state["mediaLedger"][self.digest]["mediaRef"],
                         "fresh-media")

    def test_import_receipt_accepts_claude_mcp_content_array(self):
        binding = bind_operation("import_media", {"source": {"path": self.asset}}, self.state)
        event = {"tool_response": [{"type": "text",
                  "text": '{"mediaRef":"claude-media"}'}]}
        observe_bound_operation(ElementObservation(
            self.state, {"binding": binding}, _timeline(), _timeline(), event))
        self.assertEqual(self.state["mediaLedger"][self.digest]["mediaRef"],
                         "claude-media")

    def test_missed_import_hook_recovers_one_exact_inventory_asset(self):
        args = {"source": {"path": self.asset}, "name": "graphic-1"}
        binding = bind_operation("import_media", args, self.state)
        client = SimpleNamespace(call_json=lambda *_args: {"assets": [{
            "id": "recovered-media", "name": "graphic-1",
            "durationSeconds": 3.0, "width": 1920, "height": 1080}]})
        probe = SimpleNamespace(duration=3.0, width=1920, height=1080)
        with patch("palmier.desktop_elements.probe_media", return_value=probe):
            recover_bound_operation(RecoveryObservation(
                self.state, {"binding": binding}, _timeline(), _timeline(), client))
        self.assertEqual(self.state["mediaLedger"][self.digest]["mediaRef"],
                         "recovered-media")

    def test_ambiguous_import_recovery_accepts_only_a_matching_explicit_ref(self):
        binding = bind_operation(
            "import_media", {"source": {"path": self.asset}}, self.state)
        assets = [{"id": ident, "name": "new", "durationSeconds": 3.0,
                   "width": 1920, "height": 1080}
                  for ident in ("duplicate-a", "duplicate-b")]
        client = SimpleNamespace(call_json=lambda *_args: {"assets": assets})
        probe = SimpleNamespace(duration=3.0, width=1920, height=1080)
        with patch("palmier.desktop_elements.probe_media", return_value=probe):
            recover_bound_operation(RecoveryObservation(
                self.state, {"binding": binding}, _timeline(), _timeline(),
                client, "duplicate-b"))
        self.assertEqual(self.state["mediaLedger"][self.digest]["mediaRef"],
                         "duplicate-b")

    def test_atomic_replacement_advances_only_the_bound_element(self):
        args = {"entries": [{"mediaRef": "new-media", "startFrame": 24,
                              "endFrame": 96, "trackIndex": 0}]}
        binding = bind_operation("add_clips", args, self.state)
        before = _timeline(_clip("source", "source", 0, 240),
                           _clip("old-card", "old-media", 24, 96))
        after = _timeline(_clip("source", "source", 0, 240),
                          _clip("new-card", "new-media", 24, 96))
        observe_bound_operation(ElementObservation(
            self.state, {"binding": binding}, before, after, {}))
        row = self.state["elementLedger"]["elements"]["graphic-1"]
        self.assertEqual((row["status"], row["clipId"], row["assetHash"]),
                         ("current", "new-card", self.digest))

    def test_two_step_replacement_tracks_required_cleanup(self):
        args = {"entries": [{"mediaRef": "new-media", "startFrame": 24,
                              "endFrame": 96, "trackIndex": 0}]}
        add = bind_operation("add_clips", args, self.state)
        before = _timeline(_clip("old-card", "old-media", 24, 96))
        both = _timeline(_clip("old-card", "old-media", 24, 96),
                         _clip("new-card", "new-media", 24, 96))
        observe_bound_operation(ElementObservation(
            self.state, {"binding": add}, before, both, {}))
        row = self.state["elementLedger"]["elements"]["graphic-1"]
        self.assertEqual(row["status"], "cleanup-required")
        cleanup = bind_operation(
            "remove_clips", {"clipIds": ["old-card"]}, self.state)
        final = _timeline(_clip("new-card", "new-media", 24, 96))
        observe_bound_operation(ElementObservation(
            self.state, {"binding": cleanup}, both, final, {}))
        self.assertEqual((row["status"], row["clipId"]),
                         ("current", "new-card"))

    def test_unrelated_structural_change_is_rejected(self):
        args = {"entries": [{"mediaRef": "new-media", "startFrame": 24,
                              "endFrame": 96, "trackIndex": 0}]}
        binding = bind_operation("add_clips", args, self.state)
        before = _timeline(_clip("old-card", "old-media", 24, 96),
                           _clip("other", "other-media", 100, 120))
        after = _timeline(_clip("new-card", "new-media", 24, 96))
        with self.assertRaisesRegex(PalmierError, "unrelated clip"):
            observe_bound_operation(ElementObservation(
                self.state, {"binding": binding}, before, after, {}))


class RepairManifestIntegrationTests(unittest.TestCase):
    def test_plan_authority_survives_in_place_source_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "edit_plan.json")
            with open(source, "w", encoding="utf-8") as handle:
                json.dump({"version": 1}, handle)
            first = _receipt(source, tmp, "plan")
            with open(source, "w", encoding="utf-8") as handle:
                json.dump({"version": 2}, handle)
            second = _receipt(source, tmp, "plan")
            self.assertNotEqual(first, second)
            self.assertEqual(file_sha256(first["path"]), first["hash"])
            with open(first["path"], encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["version"], 1)

    def test_repair_manifest_renders_cache_then_keeps_only_changed_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source.mp4")
            graphic = os.path.join(tmp, "new-card.mov")
            with open(source, "wb") as handle:
                handle.write(b"source")
            with open(graphic, "wb") as handle:
                handle.write(b"new graphic bytes")
            with open(graphic + ".placement.json", "w",
                      encoding="utf-8") as handle:
                json.dump({"schemaVersion": 1}, handle)
            old_path = os.path.join(tmp, "old-plan.json")
            new_path = os.path.join(tmp, "new-plan.json")
            manifest_path = os.path.join(tmp, "manifest.json")
            old_plan, new_plan = _plan(), _plan("After")
            old_plan["target"] = new_plan["target"] = {"mode": "longform"}
            for path, value in ((old_path, old_plan), (new_path, new_plan)):
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(value, handle)
            with open(manifest_path, "w", encoding="utf-8") as handle:
                json.dump({"sources": [{"id": "src", "role": "primary",
                                        "path": source, "fps": 24,
                                        "resolution": [1920, 1080]}]}, handle)
            state = {
                "projectName": "demo", "projectSettings": {
                    "fps": 24, "width": 1920, "height": 1080},
                "plan": {"path": old_path, "hash": file_sha256(old_path)},
                "exactMasterReference": {
                    "status": "ready", "startFrame": 0, "endFrame": 240,
                    "hidden": True, "muted": True, "assetPath": source,
                    "assetHash": file_sha256(source),
                },
                "elementLedger": _ledger(),
            }
            rendered = {"path": graphic, "cached": False, "key": "render-key",
                        "kind": "statement-card", "fmt": "mov",
                        "proof": {"schemaVersion": 1}}
            inputs = DesktopStageInput(
                tmp, tmp, new_path, manifest_path, "repair")
            with patch("palmier.desktop_repair.render_entry",
                       return_value=rendered), patch(
                           "palmier.desktop_repair.bake_rendered_graphic",
                           return_value=rendered):
                result = prepare_desktop_manifest(inputs, state)
            steps = result["content"]["steps"]
            self.assertEqual([row["op"] for row in steps],
                             ["import", "replace-overlay"])
            self.assertEqual(steps[1]["fileHash"], file_sha256(graphic))
            self.assertEqual(result["content"]["capability"]["mode"],
                             "scoped-card-repair")


if __name__ == "__main__":
    unittest.main()

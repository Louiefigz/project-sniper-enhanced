"""Adversarial local contracts for the disabled exact-master reference."""
from __future__ import annotations

import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from exact_master_reference_fixture import (COVERAGE, add_args,
                                            added_timeline, base_timeline,
                                            clone, make_state)
from palmier.desktop_element_types import ElementObservation
from palmier.desktop_exact_master_binding import (
    bind_exact_master_operation, expected_disable_args)
from palmier.desktop_exact_master_contract import (
    assert_reference_mutation_allowed, assert_reference_ready,
    require_exact_master_ready)
from palmier.desktop_exact_master_readback import observe_exact_master_operation
from palmier.desktop_exact_master_plan import prepare_exact_master_reference
from palmier.desktop_frame_authority import DesktopFrameAuthority
from palmier.master import MasterFacts
from palmier.mcp_client import PalmierError


class ExactMasterReferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.state = make_state(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _place(self, coverage: dict = COVERAGE) -> dict:
        binding = bind_exact_master_operation(
            "add_clips", add_args(), self.state)
        self.assertIsInstance(binding, dict)
        handled = observe_exact_master_operation(ElementObservation(
            self.state, {"binding": binding}, base_timeline(),
            added_timeline(), {}, coverage))
        self.assertTrue(handled)
        return binding

    def _disable(self, after: dict | None = None) -> dict:
        args = expected_disable_args(self.state)
        binding = bind_exact_master_operation(
            "manage_tracks", args, self.state)
        self.assertIsInstance(binding, dict)
        observe_exact_master_operation(ElementObservation(
            self.state, {"binding": binding}, added_timeline(),
            after or added_timeline(disabled=True), {}, COVERAGE))
        return binding

    def test_exact_add_then_disable_is_ledgered_and_ready(self) -> None:
        self._place()
        record = self.state["exactMasterReference"]
        self.assertEqual(record["status"], "disable-required")
        self.assertEqual(record["clipId"], "master-video")
        with self.assertRaisesRegex(PalmierError, "hidden/muted"):
            assert_reference_mutation_allowed(
                "set_keyframes", {}, self.state)
        self._disable()
        self.assertEqual(
            self.state["exactMasterReference"]["status"], "ready")
        self.assertEqual(
            self.state["elementLedger"]["elements"]
            ["exact-master-reference"]["status"], "current")
        require_exact_master_ready(
            self.state, added_timeline(disabled=True), COVERAGE)

    def test_add_binding_rejects_wrong_window_or_explicit_track(self) -> None:
        for entry in (
            {"mediaRef": "master-media", "startFrame": 0, "endFrame": 119},
            {"mediaRef": "master-media", "startFrame": 0, "endFrame": 120,
             "trackIndex": 0},
        ):
            with self.subTest(entry=entry), self.assertRaisesRegex(
                    PalmierError, "dedicated placement"):
                bind_exact_master_operation(
                    "add_clips", {"entries": [entry]}, self.state)

    def test_add_rejects_unrelated_drift_and_stacking(self) -> None:
        binding = bind_exact_master_operation(
            "add_clips", add_args(), self.state)
        drifted = added_timeline()
        drifted["tracks"][1]["clips"][0]["opacity"] = 0.5
        with self.assertRaisesRegex(PalmierError, "unrelated"):
            observe_exact_master_operation(ElementObservation(
                self.state, {"binding": binding}, base_timeline(),
                drifted, {}, COVERAGE))
        stacked = added_timeline()
        stacked["tracks"][0]["clips"].append({
            "id": "stacked", "mediaRef": "master-media",
            "frames": [0, 120],
        })
        with self.assertRaisesRegex(PalmierError, "identities|dedicated"):
            observe_exact_master_operation(ElementObservation(
                self.state, {"binding": binding}, base_timeline(),
                stacked, {}, COVERAGE))

    def test_add_requires_complete_fresh_readback(self) -> None:
        binding = bind_exact_master_operation(
            "add_clips", add_args(), self.state)
        with self.assertRaisesRegex(PalmierError, "incomplete"):
            observe_exact_master_operation(ElementObservation(
                self.state, {"binding": binding}, base_timeline(),
                added_timeline(), {}, {"complete": False}))
        self.assertNotIn("exactMasterReference", self.state)

    def test_disable_rejects_audible_or_unrelated_result(self) -> None:
        self._place()
        expected = expected_disable_args(self.state)
        binding = bind_exact_master_operation(
            "manage_tracks", expected, self.state)
        audible = added_timeline(disabled=True)
        audible["tracks"][3].pop("muted")
        with self.assertRaisesRegex(PalmierError, "left a route active"):
            observe_exact_master_operation(ElementObservation(
                self.state, {"binding": binding}, added_timeline(),
                audible, {}, COVERAGE))
        drifted = added_timeline(disabled=True)
        drifted["tracks"][1]["clips"][0]["opacity"] = 0.25
        with self.assertRaisesRegex(PalmierError, "unrelated"):
            observe_exact_master_operation(ElementObservation(
                self.state, {"binding": binding}, added_timeline(),
                drifted, {}, COVERAGE))
        self.assertEqual(
            self.state["exactMasterReference"]["status"], "disable-required")

    def test_ready_reference_fails_if_reenabled_or_multiplied(self) -> None:
        self._place()
        self._disable()
        visible = added_timeline(disabled=True)
        visible["tracks"][0].pop("hidden")
        with self.assertRaisesRegex(PalmierError, "visible"):
            assert_reference_ready(self.state, visible, COVERAGE)
        stacked = added_timeline(disabled=True)
        duplicate = clone(stacked["tracks"][0]["clips"][0])
        duplicate["id"] = "duplicate-master"
        stacked["tracks"][1]["clips"].append(duplicate)
        with self.assertRaisesRegex(PalmierError, "multiply stacked"):
            assert_reference_ready(self.state, stacked, COVERAGE)
        unknown = added_timeline(disabled=True)
        unknown["tracks"][0]["clips"][0]["opacity"] = 1.0
        with self.assertRaisesRegex(PalmierError, "unapproved"):
            assert_reference_ready(self.state, unknown, COVERAGE)
        wrong_rate = added_timeline(disabled=True)
        wrong_rate["fps"] = 30
        with self.assertRaisesRegex(PalmierError, "timebase"):
            assert_reference_ready(self.state, wrong_rate, COVERAGE)

    def test_ready_track_flags_cannot_be_mutated(self) -> None:
        self._place()
        self._disable()
        with self.assertRaisesRegex(PalmierError, "immutable"):
            assert_reference_mutation_allowed(
                "manage_tracks",
                {"set": [{"index": 3, "muted": False}]}, self.state)
        assert_reference_mutation_allowed(
            "manage_tracks", {"set": [{"index": 2, "muted": True}]},
            self.state)

    def test_ready_reference_indices_refresh_from_complete_readback(self) -> None:
        self._place()
        self._disable()
        shifted = added_timeline(disabled=True)
        shifted["tracks"].insert(0, {
            "index": 0, "label": "V3", "type": "video", "clips": [],
        })
        for index, track in enumerate(shifted["tracks"]):
            track["index"] = index
        shifted["tracks"][1]["clips"][0]["audio"]["track"] = 4
        shifted["tracks"][2]["clips"][0]["audio"]["track"] = 3
        assert_reference_ready(self.state, shifted, COVERAGE)
        self.assertEqual(
            (self.state["exactMasterReference"]["videoTrackIndex"],
             self.state["exactMasterReference"]["audioTrackIndex"]),
            (1, 4))

    def test_ready_reference_identities_cannot_be_targeted(self) -> None:
        self._place()
        self._disable()
        cases = (
            ("set_clip_properties", {"clipIds": ["master-video"],
                                     "opacity": 0}),
            ("remove_clips", {"clipIds": ["master-audio"]}),
            ("move_clips", {"moves": [{"clipId": "master-video",
                                       "toTrack": 1}]}),
            ("add_clips", {"entries": [{
                "mediaRef": "master-media", "startFrame": 0,
                "endFrame": 120,
            }]}),
        )
        for tool, args in cases:
            with self.subTest(tool=tool), self.assertRaisesRegex(
                    PalmierError, "identities are immutable"):
                assert_reference_mutation_allowed(tool, args, self.state)

    def test_plan_requires_exact_duration_canvas_and_audio(self) -> None:
        master_path = next(iter(self.state["mediaLedger"].values()))["path"]
        digest = next(iter(self.state["mediaLedger"]))
        inputs = SimpleNamespace(
            out_dir=self.temp.name, plan_path="plan", manifest_path="manifest")
        authority = SimpleNamespace(plan_hash="p" * 64)
        project = {"projectSettings": {
            "fps": 24, "width": 1920, "height": 1080}}
        master = MasterFacts(
            master_path, digest, 5.0, 24.0, 1920, 1080, 120, "24/1")
        probe = SimpleNamespace(
            audio_present=True, audio_channels=2, audio_sample_rate=48000)
        frames = DesktopFrameAuthority(120, "test")
        with patch("palmier.desktop_exact_master_plan.approved_master",
                   return_value=master), patch(
                       "palmier.desktop_exact_master_plan.probe_media",
                       return_value=probe):
            steps, capability = prepare_exact_master_reference(
                inputs, authority, project, frames)
            self.assertEqual(
                [row["op"] for row in steps],
                ["import", "exact-master-reference-add",
                 "exact-master-reference-disable"])
            self.assertFalse(capability["connectedReadbackQualified"])
            with self.assertRaisesRegex(PalmierError, "duration"):
                prepare_exact_master_reference(
                    inputs, authority, project,
                    DesktopFrameAuthority(119, "test"))
            fractional = MasterFacts(
                master_path, digest, 4.0, 29.97, 1920, 1080, 120,
                "30000/1001")
            with patch(
                    "palmier.desktop_exact_master_plan.approved_master",
                    return_value=fractional), self.assertRaisesRegex(
                        PalmierError, "30000/1001"):
                prepare_exact_master_reference(
                    inputs, authority, {
                        "projectSettings": {
                            "fps": 30, "width": 1920, "height": 1080,
                        }}, frames)
        silent = SimpleNamespace(
            audio_present=False, audio_channels=None, audio_sample_rate=None)
        with patch("palmier.desktop_exact_master_plan.approved_master",
                   return_value=master), patch(
                       "palmier.desktop_exact_master_plan.probe_media",
                       return_value=silent), self.assertRaisesRegex(
                           PalmierError, "no audio"):
            prepare_exact_master_reference(
                inputs, authority, project, frames)


if __name__ == "__main__":
    unittest.main(verbosity=2)

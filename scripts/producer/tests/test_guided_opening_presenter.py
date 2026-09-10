"""Opening live graph control-flow faults; encode/probe outputs remain TEST stubs."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import patch

from _guided_opening_presenter_fixture import OpeningPresenterFixture
from cut_preview_io import digest
from guided_opening_picture import compose_ranges
from opening_prefix_contract import canonical_hash
from opening_prefix_presenter import presenter_graph_payload
from opening_prefix_presenter import _observation_record


class OpeningPresenterTests(unittest.TestCase):
    """Check actual range adapter routing without claiming real image quality."""

    def setUp(self) -> None:
        """Hold synthetic selected observation with actual small-file identities."""
        self.fixture = OpeningPresenterFixture()
        self.addCleanup(self.fixture.close)

    def compose(self, context: object = None) -> dict:
        """Stub only the final compositor and picture decoder leaves."""
        fixture = self.fixture
        with patch("guided_opening_picture.composite", side_effect=fixture.compose), \
                patch("guided_opening_picture.observe_picture", side_effect=fixture.observed):
            return compose_ranges(fixture.base, [], context or fixture.context)

    def test_range_graph_preserves_whole_crossing_window_and_future_binding(self) -> None:
        fixture = self.fixture
        original = deepcopy(fixture.plan)
        with patch("guided_presenter_observation.run_text") as probe, \
                patch("guided_opening_presenter._observation_record", wraps=_observation_record) as projection:
            result = self.compose()
        probe.assert_not_called()
        self.assertEqual(projection.call_count, 1)
        self.assertEqual(fixture.plan, original)
        self.assertEqual([row[2].frame_range for row in fixture.commands], [(0, 6), (0, 12)])
        for _clips, _out, options in fixture.commands:
            self.assertEqual(len(options.presenter.windows), 1)
            self.assertEqual(options.presenter.windows[0].geometry.timing.end_frame_exclusive, 18)
            self.assertEqual(options.presenter.canvas.total_frames, 48)
            self.assertEqual(options.frame_rate, "30000/1001")
        layers = result["presenterLayers"]
        self.assertEqual(layers["graphHash"], canonical_hash(layers["graph"]))
        self.assertEqual(layers["pictureRangesHash"], digest(result["ranges"]))
        self.assertEqual(layers["fullPresenterGraphHash"], canonical_hash(presenter_graph_payload(fixture.owner.full_graph())))
        self.assertFalse(layers["captionClearanceVerified"])
        self.assertFalse(layers["deliveryApproved"])

    def test_identical_ranges_encode_once_and_legacy_tuple_has_no_new_fields(self) -> None:
        fixture = self.fixture
        fixture.authority["core"] = dict(fixture.authority["review"])
        result = self.compose()
        self.assertEqual(len(fixture.commands), 1)
        self.assertIs(result["ranges"]["core"], result["ranges"]["review"])
        fixture.commands.clear()
        with patch("guided_opening_picture.held_presenter_ranges") as acquisition:
            result = self.compose((fixture.root, fixture.authority, fixture.tools))
        acquisition.assert_not_called()
        self.assertNotIn("presenterLayers", result)
        self.assertIsNone(fixture.commands[0][2].presenter)

    def test_all_future_presenters_keep_explicit_record_without_premature_overlay(self) -> None:
        fixture = self.fixture
        fixture.authority["core"]["endFrameExclusive"] = 1
        fixture.authority["review"]["endFrameExclusive"] = 2
        result = self.compose()
        self.assertTrue(all(row[2].presenter is None for row in fixture.commands))
        self.assertIsNone(result["presenterLayers"]["graph"]["presenter"])
        self.assertEqual(len(result["presenterLayers"]["observations"]), 1)

    def test_base_hash_clock_and_plan_must_match_before_any_encoder(self) -> None:
        fixture = self.fixture
        bad = replace(fixture.context, presenter=replace(fixture.presenter,
            base=replace(fixture.presenter.base, sha256="0" * 64)))
        with self.assertRaisesRegex(RuntimeError, "identity changed"):
            self.compose(bad)
        fixture.authority["totalFrames"] = 47
        with self.assertRaisesRegex(RuntimeError, "clock"):
            self.compose()
        fixture.authority["totalFrames"] = 48
        fixture.plan["presenterLayouts"][0]["endFrameExclusive"] = 17
        with self.assertRaisesRegex(RuntimeError, "requested plan"):
            self.compose()
        self.assertEqual(fixture.commands, [])

    def test_changed_base_after_first_encode_stops_second_encode_and_result(self) -> None:
        fixture = self.fixture
        original = fixture.compose

        def change(base: str, clips: list, output: str, options: object) -> int:
            """Simulate a late dependent-file write at the actual command boundary."""
            result = original(base, clips, output, options)
            fixture.base.write_bytes(b"TEST late changed base")
            return result

        fixture.compose = change
        with self.assertRaisesRegex(RuntimeError, "held base changed"):
            self.compose()
        self.assertEqual(len(fixture.commands), 1)

    def test_expired_original_owner_cannot_use_successful_earlier_observation(self) -> None:
        self.fixture.source.deadline.expired = True
        with self.assertRaisesRegex(RuntimeError, "original deadline expired"):
            self.compose()
        self.assertEqual(self.fixture.commands, [])

    def test_added_actual_clip_cannot_escape_tuple_held_graph_record(self) -> None:
        fixture = self.fixture
        original = fixture.compose

        def change(base: str, clips: list, output: str, options: object) -> int:
            """Reproduce the independently found outer-list/tuple identity mismatch."""
            clips.append({"graphicId": "TEST-unbound", "outStart": 0})
            return original(base, clips, output, options)

        fixture.compose = change
        with self.assertRaisesRegex(RuntimeError, "actual clip inventory changed"):
            self.compose()
        self.assertEqual(len(fixture.commands), 1)

    def test_removed_reordered_and_replaced_actual_clips_cannot_publish(self) -> None:
        fixture = self.fixture
        clips = [{"graphicId": "a", "outStart": 0}, {"graphicId": "b", "outStart": 1}]
        mutations = (lambda rows: rows.pop(), lambda rows: rows.reverse(),
                     lambda rows: rows.__setitem__(0, {"graphicId": "other", "outStart": 0}))
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                def change(_base: str, supplied: list, _out: str, _options: object) -> int:
                    """Mutate the passed command list without editing the original plan."""
                    mutate(supplied)
                    return 1

                with patch("guided_opening_picture.composite", side_effect=change), \
                        patch("guided_opening_picture.observe_picture", side_effect=fixture.observed), \
                        self.assertRaisesRegex(RuntimeError, "actual clip inventory changed"):
                    compose_ranges(fixture.base, clips, fixture.context)
        self.assertEqual([row["graphicId"] for row in clips], ["a", "b"])


if __name__ == "__main__":
    unittest.main()

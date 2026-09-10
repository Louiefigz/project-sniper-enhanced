"""Held metadata replay tests; fake admission/native provenance remains explicit."""
from __future__ import annotations

import time
import unittest
from dataclasses import asdict, replace
from unittest.mock import patch

from _grade_bt709_identity_fixture import Bt709IdentityFixture
from _grade_project_owned_fixture import OwnedGradeFixture
from color import grade_bt709_identity_read as reader
from color.grade_project_completion import seal_completed_project_observation


class Bt709IdentityReadTests(unittest.TestCase):
    """The new evidence uses existing source/report holds and never renews a phase."""

    def setUp(self) -> None:
        """Keep one fake original overall clock and fresh canonical TEST-only files."""
        self.now = [1000.0]
        timer = patch.object(time, "monotonic", side_effect=lambda: self.now[0])
        timer.start()
        self.addCleanup(timer.stop)
        self.fixture = Bt709IdentityFixture()
        self.addCleanup(self.fixture.cleanup)
        self.fixture.context = replace(self.fixture.context, deadline=1300.0)

    def test_actual_held_read_is_separate_and_preserves_original_v1_observation(self) -> None:
        """Return actual same-object completed evidence without changing its historical data."""
        completed = self.fixture.completed()
        original = asdict(completed.observation)
        result = reader.read_bt709_identity_observation(completed)
        self.assertIs(result.completed, completed)
        self.assertIs(result.completed.observation, self.fixture.returned)
        self.assertEqual(asdict(completed.observation), original)
        self.assertIsNone(completed.observation.records.stream.source_metadata)
        self.assertEqual(result.metadata.decoded_frame_count, 180)
        self.assertEqual(result.metadata.rotation_observation, "no-stream-or-frame-rotation-metadata")
        self.assertEqual([result.executable, result.gamut_measured, result.grade_applicable,
                          result.base_render_applicable, result.delivery_approved], [False] * 5)
        result.assert_current()
        self.fixture.worker.assert_called_once()

    def test_old_work_phase_can_expire_without_renewing_original_completed_lifetime(self) -> None:
        """Read legitimate completed data after1120, but never at the original1300 cutoff."""
        completed = self.fixture.completed()
        self.assertEqual(completed.phase_deadline, 1120.0)
        self.now[0] = 1121.0
        result = reader.read_bt709_identity_observation(completed)
        result.assert_current()
        self.assertEqual(result.completed.phase_deadline, 1120.0)
        self.assertEqual(result.completed.context.deadline, 1300.0)
        self.now[0] = 1300.0
        with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            result.assert_current()

    def test_one_metadata_replay_and_no_source_hash_or_decode_on_later_checks(self) -> None:
        """Only three original JSON buffers plus one bounded frame stream are replayed."""
        completed = self.fixture.completed()
        with patch.object(reader, "read_bytes", wraps=reader.read_bytes) as raw, \
                patch.object(reader, "_lines", wraps=reader._lines) as lines, \
                patch("color.grade_project_owned.file_hash", side_effect=AssertionError("unexpected source hash")):
            result = reader.read_bt709_identity_observation(completed)
            result.assert_current()
            result.assert_current()
        self.assertEqual(raw.call_count, 3)
        self.assertEqual(lines.call_count, 1)
        self.assertEqual(result._read.loaded, [])
        self.fixture.worker.assert_called_once()

    def test_legacy_missing_geometry_is_still_observed_but_cannot_gain_new_evidence(self) -> None:
        """The original V1 read succeeds unchanged, while only this opt-in path rejects."""
        self.fixture.metadata_mutator = lambda probe, rows: rows[-1].pop("sample_aspect_ratio")
        completed = self.fixture.completed()
        self.assertEqual(completed.observation.records.decoded_record_count, 180)
        with self.assertRaisesRegex(ValueError, "explicit square SAR"):
            reader.read_bt709_identity_observation(completed)

    def test_bound_records_alone_or_data_constructor_cannot_mint_held_read(self) -> None:
        """A record, parsed JSON or public constructor supplies no persistent file owner."""
        completed = self.fixture.completed()
        for value in (None, {}, completed.observation):
            with self.subTest(value=type(value)), self.assertRaises(ValueError):
                reader.read_bt709_identity_observation(value)
        with self.assertRaises(TypeError):
            reader.HeldBt709IdentityObservation()

    def test_actual_v2_completed_object_is_not_relabelled_as_v1(self) -> None:
        """A genuine TEST-owned V2 wrapper still belongs to its original explicit class."""
        fixture = OwnedGradeFixture()
        self.addCleanup(fixture.cleanup)
        fixture.enable_v2()
        completed = seal_completed_project_observation(fixture.execute())
        with patch.object(reader, "read_bytes") as raw, self.assertRaisesRegex(ValueError, "relabel V2"):
            reader.read_bt709_identity_observation(completed)
        raw.assert_not_called()


if __name__ == "__main__":
    unittest.main()

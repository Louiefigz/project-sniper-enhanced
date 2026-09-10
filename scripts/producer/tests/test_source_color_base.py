"""All-source identity factory tests on genuine byte holds with native TEST stubs."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from _source_color_base_fixture import SourceColorBaseFixture
from _source_color_batch_fixture import current_batch_test_pins
import guided_source_color_base as base


class SourceColorBaseTests(unittest.TestCase):
    """Require complete actual original V1 evidence without grade or picture claims."""

    @classmethod
    def setUpClass(cls) -> None:
        """Hold current actual implementation pins for this metadata-only stable cohort."""
        cls.pins = current_batch_test_pins()

    def fixture(self, baseline: object = "ABSENT") -> SourceColorBaseFixture:
        """Use only generated TEST roots and inherited stub admission/native leaves."""
        result = SourceColorBaseFixture(self.pins, baseline)
        self.addCleanup(result.cleanup)
        return result

    def test_all_used_sources_and_original_completion_objects_are_retained(self) -> None:
        """Every source, including repeated original cuts, gets exactly one identity replay."""
        fixture = self.fixture()
        batch = fixture.execute()
        with patch.object(base, "read_bt709_identity_observation", wraps=base.read_bt709_identity_observation) as read:
            result = base.hold_bt709_base_identity(batch)
            result.assert_current()
        self.assertIs(result.batch, batch)
        self.assertIs(result.inputs, fixture.inputs)
        self.assertEqual(read.call_count, 2)
        self.assertEqual([row.completed.context.source.path for row in result.observations],
                         [row.source.path for row in batch.preparation.jobs])
        self.assertTrue(all(row.completed is old for row, old in zip(result.observations, batch.observations)))
        self.assertEqual([result.executable, result.gamut_measured, result.base_picture_observed,
                          result.grade_applicable, result.delivery_approved], [False] * 5)

    def test_literal_null_look_is_preserved_as_not_required(self) -> None:
        """Actual render/plan-lint null behavior stays distinct from a default-filled object."""
        fixture = self.fixture(None)
        result = fixture.identity()
        self.assertIn("baselineLook", result.inputs.documents["candidatePlan"])
        self.assertIsNone(result.inputs.documents["candidatePlan"]["baselineLook"])

    def test_non_null_look_is_rejected_before_supplemental_replay(self) -> None:
        """An explicit object cannot be silently removed or treated as identity defaults."""
        fixture = self.fixture({})
        batch = fixture.execute()
        with patch.object(base, "read_bt709_identity_observation") as read, \
                self.assertRaisesRegex(RuntimeError, "no new look"):
            base.hold_bt709_base_identity(batch)
        read.assert_not_called()
        self.assertEqual(fixture.inputs.documents["candidatePlan"]["baselineLook"], {})

    def test_prior_supplemental_return_mutation_during_next_source_refuses(self) -> None:
        """Snapshot each actual return before any following source callback can mutate it."""
        fixture = self.fixture()
        batch = fixture.execute()
        actual, returned = base.read_bt709_identity_observation, []

        def read(completed: object) -> object:
            """Mutate only the first TEST returned metadata object after the second read."""
            result = actual(completed)
            if returned:
                object.__setattr__(returned[0].metadata, "decoded_frame_count", 24.0)
            returned.append(result)
            return result

        with patch.object(base, "read_bt709_identity_observation", side_effect=read), \
                self.assertRaisesRegex(RuntimeError, "original held evidence"):
            base.hold_bt709_base_identity(batch)

    def test_no_serialized_batch_or_public_evidence_constructor(self) -> None:
        """Arbitrary metadata must not provide a same-process original source lifetime."""
        with self.assertRaisesRegex(RuntimeError, "actual completed"):
            base.hold_bt709_base_identity({"status": "complete"})
        with self.assertRaises(TypeError):
            base.HeldBt709BaseIdentity()


if __name__ == "__main__":
    unittest.main()

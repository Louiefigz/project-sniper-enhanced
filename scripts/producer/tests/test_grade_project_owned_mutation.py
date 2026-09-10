"""Exact post-callback mutation regressions; all media/decoder leaves are stubbed."""
from __future__ import annotations

from copy import deepcopy
from collections.abc import Callable
import unittest
from unittest.mock import patch

from _grade_project_owned_fixture import OwnedGradeFixture
from color import grade_project as project
from color.grade_project_owned import OwnedProjectObservationError


class OwnedGradeMutationTests(unittest.TestCase):
    """A frozen outer type does not make mutable nested caller objects trustworthy."""

    def setUp(self) -> None:
        """Use fresh tiny metadata and the actual typed reader return for each case."""
        self.fixture = OwnedGradeFixture()
        self.addCleanup(self.fixture.cleanup)

    def _after_publication(self, mutate: Callable[[], None]) -> None:
        """Keep the exact reviewer reproduction at the final original guard boundary."""
        def guard() -> None:
            """Mutate only after actual result JSON exists, not at an earlier easy gate."""
            if (self.fixture.job / "observation.json").exists():
                mutate()

        self.fixture.guard.side_effect = guard

    def test_source_sha_changed_by_final_guard_is_rejected_before_handoff(self) -> None:
        """Do not return an observation under a source identity changed by its guard."""
        self._after_publication(lambda: object.__setattr__(self.fixture.context.source, "sha256", "0" * 64))
        with self.assertRaisesRegex(RuntimeError, "original context changed during its guard"):
            self.fixture.execute()

    def test_context_deadline_replacement_is_not_consulted_after_callback(self) -> None:
        """A late guard cannot extend the original clock or replace its own callback."""
        original = self.fixture.context.deadline
        self._after_publication(lambda: object.__setattr__(self.fixture.context, "deadline", original + 120))
        with self.assertRaisesRegex(RuntimeError, "original context changed during its guard"):
            self.fixture.execute()
        self.assertEqual(self.fixture.worker.call_args.args[3], original)

    def test_context_callback_replacement_is_rejected_after_original_callback(self) -> None:
        """The final guard cannot substitute a new no-op ownership callback."""
        self._after_publication(lambda: object.__setattr__(self.fixture.context, "guard", lambda: None))
        with self.assertRaisesRegex(RuntimeError, "original context changed during its guard"):
            self.fixture.execute()

    def test_equal_numeric_source_coercion_is_not_original_typed_identity(self) -> None:
        """Python int/float equality cannot weaken the captured source size type."""
        size = self.fixture.context.source.size_bytes
        self._after_publication(lambda: object.__setattr__(self.fixture.context.source, "size_bytes", float(size)))
        with self.assertRaisesRegex(RuntimeError, "original context changed during its guard"):
            self.fixture.execute()

    def test_final_guard_observation_flags_and_geometry_mutation_are_rejected(self) -> None:
        """Exact reviewer repro: public JSON false/160 cannot cover changed true/158."""
        def mutate() -> None:
            """Alter the actual returned type, not a copied or reconstructed result."""
            object.__setattr__(self.fixture.returned, "grade_applicable", True)
            object.__setattr__(self.fixture.returned.records.stream, "width", 158)

        self._after_publication(mutate)
        with self.assertRaisesRegex(RuntimeError, "actual typed observation changed"):
            self.fixture.execute()

    def test_first_post_reader_mutation_cannot_be_adopted_as_original_binding(self) -> None:
        """Bind immediately when the real reader returns, before any later callbacks."""
        original = project.observe_project

        def observe(value: dict) -> dict:
            """Mutate at the existing final parent-read seam, before pending retention."""
            result = original(value)
            if self.fixture.returned is not None:
                object.__setattr__(self.fixture.returned.records.stream, "width", 158)
            return result

        with patch.object(project, "observe_project", side_effect=observe), \
                self.assertRaisesRegex(OwnedProjectObservationError, "actual typed observation changed") as error:
            self.fixture.execute()
        self.assertNotIn("observation", error.exception.result)

    def test_future_assert_current_rejects_same_object_nested_mutation(self) -> None:
        """The retained small binding remains effective after the handoff returns."""
        owned = self.fixture.execute()
        self.assertIs(owned.observation, self.fixture.returned)
        object.__setattr__(owned.observation.records.stream, "width", 158)
        with self.assertRaisesRegex(RuntimeError, "actual typed observation changed"):
            owned.assert_current()

    def test_future_guard_mutation_rejects_without_source_or_raw_hash_replay(self) -> None:
        """Only fixed-size typed facts and existing stat checks run on each guard."""
        owned = self.fixture.execute()
        self.fixture.guard.side_effect = lambda: object.__setattr__(owned.observation, "delivery_approved", True)
        with patch("color.grade_project_owned.file_hash", side_effect=AssertionError("no repeated hash")), \
                patch.object(project, "read_observation", side_effect=AssertionError("no replay")), \
                self.assertRaisesRegex(RuntimeError, "actual typed observation changed"):
            owned.assert_current()

    def test_equal_numeric_geometry_and_replaced_actual_object_are_not_original(self) -> None:
        """Strict types and actual root object identity are both retained."""
        owned = self.fixture.execute()
        changed = deepcopy(owned.observation)
        object.__setattr__(owned, "observation", changed)
        with self.assertRaisesRegex(RuntimeError, "actual typed observation changed"):
            owned.assert_current()
        object.__setattr__(owned, "observation", self.fixture.returned)
        object.__setattr__(owned.observation.records.stream, "width", float(owned.observation.records.stream.width))
        with self.assertRaisesRegex(RuntimeError, "actual typed observation changed"):
            owned.assert_current()

    def test_v2_nested_siting_mutation_is_not_hidden_by_observational_flags(self) -> None:
        """V2 metadata stays exact without inventing transform or camera authority."""
        self.fixture.enable_v2()
        owned = self.fixture.execute()
        object.__setattr__(owned.observation.records.stream.source_metadata, "decoded_chroma_location", "center")
        with self.assertRaisesRegex(RuntimeError, "actual typed observation changed"):
            owned.assert_current()


if __name__ == "__main__":
    unittest.main()

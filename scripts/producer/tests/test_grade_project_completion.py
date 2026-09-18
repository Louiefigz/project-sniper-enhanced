"""Completed-data lifetime faults using inert TEST-owned files and stubbed decoders."""
from __future__ import annotations

import os
import stat
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from _grade_project_owned_fixture import OwnedGradeFixture
from color import grade_project as project
from color.grade_project_completion import CompletedProjectObservation, seal_completed_project_observation
from color.grade_project_owned import OwnedProjectObservation


class GradeProjectCompletionTests(unittest.TestCase):
    """A completed observation can outlive its phase, never its original owner."""

    def setUp(self) -> None:
        """Use one fake monotonic clock and a fresh canonical inert project per case."""
        self.clock = [1000.0]
        timer = patch.object(time, "monotonic", side_effect=lambda: self.clock[0])
        timer.start()
        self.addCleanup(timer.stop)
        self.fixture = OwnedGradeFixture()
        self.addCleanup(self.fixture.cleanup)
        self.fixture.context = replace(self.fixture.context, deadline=1300.0)

    def _sealed(self) -> tuple[OwnedProjectObservation, CompletedProjectObservation]:
        """Exercise actual publication then sealing without running a media process."""
        owned = self.fixture.execute()
        return owned, seal_completed_project_observation(owned)

    def _append_fixture_file(self, path: Path) -> None:
        """Refuse any fault target outside the exact canonical owned temporary root."""
        root = Path(self.fixture.temporary.name).resolve(strict=True)
        if root != self.fixture.root or path != path.resolve(strict=True) or not path.is_relative_to(root):
            raise RuntimeError("fault target is not an exact TEST-root file")
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
            raise RuntimeError("fault target is not a single-link TEST-owned regular file")
        path.write_bytes(path.read_bytes() + b"\nTEST fixture-only mutation\n")

    def test_seal_keeps_actual_returned_objects_and_historical_cutoff(self) -> None:
        """No copied/reconstituted observation, context, source, artifacts or clock."""
        owned, completed = self._sealed()
        self.assertIs(completed.observation, self.fixture.returned)
        self.assertIs(completed.observation, owned.observation)
        self.assertIs(completed.context, owned.context)
        self.assertIs(completed.context.source, self.fixture.identity)
        self.assertIs(completed.context.guard, self.fixture.guard)
        self.assertIs(completed.files, owned.files)
        self.assertEqual((owned.deadline, completed.phase_deadline, completed.context.deadline), (1120.0, 1120.0, 1300.0))
        self.assertEqual(self.fixture.worker.call_args.args[3], 1120.0)
        self.assertEqual((completed.result_path, completed.result_sha256), (owned.result_path, owned.result_sha256))
        self.assertIs(completed.executable, False)
        self.assertIs(completed.grade_applicable, False)
        self.assertIs(completed.delivery_approved, False)

    def test_phase_expiry_keeps_old_owner_expired_but_completed_data_readable(self) -> None:
        """An existing per-phase cutoff is not reset when completed data is read."""
        owned, completed = self._sealed()
        self.clock[0] = 1120.001
        with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            owned.assert_current()
        completed.assert_current()
        self.assertEqual(completed.phase_deadline, 1120.0)
        self.assertEqual(completed.context.deadline, 1300.0)
        self.fixture.worker.assert_called_once()

    def test_completed_read_expires_at_exact_same_original_end_without_callback(self) -> None:
        """The inclusive expiry boundary cannot be renewed by reads or a caller guard."""
        _owned, completed = self._sealed()
        self.clock[0] = 1300.0
        count = self.fixture.guard.call_count
        with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            completed.assert_current()
        self.assertEqual(self.fixture.guard.call_count, count)

    def test_expired_owned_cannot_be_sealed_even_with_original_time_remaining(self) -> None:
        """No late sealing can resurrect completed-looking historical data."""
        owned = self.fixture.execute()
        self.clock[0] = 1120.0
        count = self.fixture.guard.call_count
        with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            seal_completed_project_observation(owned)
        self.assertEqual(self.fixture.guard.call_count, count)

    def test_phase_expiry_during_sealing_withholds_completed_value(self) -> None:
        """Charge callbacks to the original observation phase, including final checks."""
        owned = self.fixture.execute()
        self.fixture.guard.side_effect = lambda: self.clock.__setitem__(0, 1121.0)
        with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            seal_completed_project_observation(owned)

    def test_second_sealing_callback_expiry_cannot_leak_completed_data(self) -> None:
        """The final sealing check still uses the phase cutoff after overall-only checks."""
        owned = self.fixture.execute()
        calls = []

        def guard() -> None:
            """Expire only the second callback, after the old owned check passed."""
            calls.append(True)
            self.clock[0] = 1121.0 if len(calls) == 2 else 1000.0

        self.fixture.guard.side_effect = guard
        with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            seal_completed_project_observation(owned)
        self.assertEqual(len(calls), 2)

    def test_original_expiry_during_completed_callback_is_not_hidden(self) -> None:
        """A successful callback cannot cover an exhausted original overall clock."""
        _owned, completed = self._sealed()
        self.fixture.guard.side_effect = lambda: self.clock.__setitem__(0, 1300.0)
        with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            completed.assert_current()

    def test_original_owner_cancellation_still_rejects_after_phase(self) -> None:
        """Completed data does not waive the original project/resource/code guard."""
        _owned, completed = self._sealed()
        self.clock[0] = 1121.0
        self.fixture.guard.side_effect = RuntimeError("TEST original owner or implementation lost")
        with self.assertRaisesRegex(RuntimeError, "original owner or implementation lost"):
            completed.assert_current()

    def test_callback_cannot_replace_context_deadline(self) -> None:
        """Reject an attempted overall-clock extension before consulting the new value."""
        _owned, completed = self._sealed()
        self.fixture.guard.side_effect = lambda: object.__setattr__(completed.context, "deadline", 1600.0)
        with self.assertRaisesRegex(RuntimeError, "original context changed during its guard"):
            completed.assert_current()

    def test_callback_cannot_replace_original_guard(self) -> None:
        """Keep the same cancellation/ownership callback, not a new permissive one."""
        _owned, completed = self._sealed()
        self.fixture.guard.side_effect = lambda: object.__setattr__(completed.context, "guard", lambda: None)
        with self.assertRaisesRegex(RuntimeError, "original context changed during its guard"):
            completed.assert_current()

    def test_callback_cannot_replace_equal_valued_original_source(self) -> None:
        """The same verified source object is retained, not merely equal field values."""
        _owned, completed = self._sealed()
        changed = replace(completed.context.source)
        self.fixture.guard.side_effect = lambda: object.__setattr__(completed.context, "source", changed)
        with self.assertRaisesRegex(RuntimeError, "original returned owner references changed"):
            completed.assert_current()

    def test_callback_source_sha_mutation_remains_rejected(self) -> None:
        """The original reviewer's post-callback source mutation also fails after sealing."""
        _owned, completed = self._sealed()
        self.fixture.guard.side_effect = lambda: object.__setattr__(completed.context.source, "sha256", "0" * 64)
        with self.assertRaisesRegex(RuntimeError, "original context changed during its guard"):
            completed.assert_current()

    def test_completed_context_cannot_be_replaced_with_equivalent_context(self) -> None:
        """No caller can substitute a newly constructed overall lifetime after sealing."""
        _owned, completed = self._sealed()
        object.__setattr__(completed, "context", replace(completed.context))
        with self.assertRaisesRegex(RuntimeError, "original owner, metadata or seal changed"):
            completed.assert_current()

    def test_pre_seal_context_replacement_cannot_extend_original_lifetime(self) -> None:
        """Regression: replacing 1300 with a new 1600 context once allowed reads at 1400."""
        owned = self.fixture.execute()
        object.__setattr__(owned, "context", replace(owned.context, deadline=1600.0))
        with self.assertRaisesRegex(RuntimeError, "original returned owner references changed"):
            owned.assert_current()
        with self.assertRaisesRegex(RuntimeError, "original returned owner references changed"):
            seal_completed_project_observation(owned)

    def test_dataclass_replacement_is_not_the_actual_returned_owner(self) -> None:
        """A newly constructed same-valued wrapper has no finish_owned origin binding."""
        owned = self.fixture.execute()
        with self.assertRaisesRegex(RuntimeError, "original returned owner references changed"):
            seal_completed_project_observation(replace(owned))

    def test_pre_seal_artifact_tuple_replacement_is_not_original_ownership(self) -> None:
        """Even equivalent copied artifact rows cannot substitute for the held tuple."""
        owned = self.fixture.execute()
        object.__setattr__(owned, "files", tuple(list(owned.files)))
        with self.assertRaisesRegex(RuntimeError, "original returned owner references changed"):
            seal_completed_project_observation(owned)

    def test_original_owned_wrapper_cannot_be_rebound_during_seal_callback(self) -> None:
        """Snapshot original wrapper references before the first sealing callback."""
        owned = self.fixture.execute()
        changed = replace(owned.context)
        self.fixture.guard.side_effect = lambda: object.__setattr__(owned, "context", changed)
        with self.assertRaisesRegex(RuntimeError, "original returned owner references changed"):
            seal_completed_project_observation(owned)

    def test_completed_flags_cannot_gain_execution_or_approval_after_callback(self) -> None:
        """All three false scope fields remain exact after the original guard returns."""
        _owned, completed = self._sealed()

        def mutate() -> None:
            """Alter only this local data object; no filesystem or media mutation."""
            for name in ("executable", "grade_applicable", "delivery_approved"):
                object.__setattr__(completed, name, True)

        self.fixture.guard.side_effect = mutate
        with self.assertRaisesRegex(RuntimeError, "original owner, metadata or seal changed"):
            completed.assert_current()

    def test_original_observation_nested_geometry_mutation_after_callback_rejects(self) -> None:
        """Preserve the immutable small metadata binding of the actual returned object."""
        _owned, completed = self._sealed()
        self.fixture.guard.side_effect = lambda: object.__setattr__(completed.observation.records.stream, "width", 158)
        with self.assertRaisesRegex(RuntimeError, "actual typed observation changed"):
            completed.assert_current()

    def test_phase_cutoff_tampering_cannot_change_sealed_history(self) -> None:
        """The old wrapper's phase cutoff remains bound even when not the read clock."""
        owned, completed = self._sealed()
        object.__setattr__(owned, "deadline", 1240.0)
        with self.assertRaisesRegex(RuntimeError, "original returned owner references changed"):
            completed.assert_current()

    def test_real_fixture_raw_artifact_change_is_rejected_after_phase(self) -> None:
        """Completed reads still check exact originally held artifact identities."""
        _owned, completed = self._sealed()
        self.clock[0] = 1121.0
        self._append_fixture_file(self.fixture.job / "execution/result/frames.ffprobe")
        with self.assertRaisesRegex(RuntimeError, "held publication or evidence changed"):
            completed.assert_current()

    def test_real_fixture_source_change_is_rejected_after_phase(self) -> None:
        """An elapsed observation phase never grants permission to replace source bytes."""
        _owned, completed = self._sealed()
        self.clock[0] = 1121.0
        self._append_fixture_file(self.fixture.producer / ".sniper-external-media/source.media")
        with self.assertRaisesRegex(RuntimeError, "original source identity changed"):
            completed.assert_current()

    def test_reads_never_hash_raw_evidence_or_reenter_decoder(self) -> None:
        """Same-owner stat/small-metadata checks are the only repeated evidence work."""
        _owned, completed = self._sealed()
        self.clock[0] = 1121.0
        with patch("color.grade_project_owned.file_hash", side_effect=AssertionError("no repeated hash")), \
                patch.object(project, "read_observation", side_effect=AssertionError("no raw replay")), \
                patch.object(project, "run_isolated_grade", side_effect=AssertionError("no decoder")):
            completed.assert_current()
            completed.assert_current()

    def test_no_data_constructor_rehydration_or_reseal_entry_point(self) -> None:
        """Only the original still-current owned result can enter the sealing factory."""
        _owned, completed = self._sealed()
        with self.assertRaisesRegex(TypeError, "requires live seal"):
            CompletedProjectObservation()
        with self.assertRaisesRegex(ValueError, "actual returned owned observation"):
            seal_completed_project_observation({"observation": completed.observation})
        with self.assertRaisesRegex(ValueError, "actual returned owned observation"):
            seal_completed_project_observation(completed)

    def test_fault_helper_refuses_real_production_dependency_without_writing(self) -> None:
        """An accidental dependency-list target can never alter repository source."""
        with patch.object(Path, "write_bytes") as write, self.assertRaisesRegex(RuntimeError, "TEST-root"):
            self._append_fixture_file(Path(project.__file__).resolve(strict=True))
        write.assert_not_called()


if __name__ == "__main__":
    unittest.main()

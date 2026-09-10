"""Late callback/clock/raw-reference faults; every file target is named TEST-owned."""
from __future__ import annotations

import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

from _source_color_batch_fixture import current_batch_test_pins
from _source_color_opening_fixture import SourceColorOpeningFixture
import guided_source_color_opening as opening


class SourceColorOpeningFaultTests(unittest.TestCase):
    """No unbound metadata, renewed deadline or returned-object substitution is accepted."""

    @classmethod
    def setUpClass(cls) -> None:
        """Capture current code only for this stable inert TEST cohort."""
        cls.pins = current_batch_test_pins()

    def setUp(self) -> None:
        """Allocate fresh metadata and restrict all mutations to its existing allowlist."""
        self.fixture = SourceColorOpeningFixture(self.pins)
        self.addCleanup(self.fixture.cleanup)

    def test_explicit_reference_cannot_be_omitted_or_forged(self) -> None:
        """Neither a missing pair nor a valid-looking wrong raw SHA starts native work."""
        self.fixture.reference = None
        with self.assertRaises(opening.SourceColorOpeningError):
            self.fixture.execute()
        self.fixture.reference = (self.fixture.sidecar_path, "a" * 64)
        with self.assertRaises(opening.SourceColorOpeningError):
            self.fixture.execute()
        self.fixture.worker.assert_not_called()

    def test_first_callback_cannot_replace_original_clock(self) -> None:
        """Snapshot the actual clock before the first persistent guard invocation."""
        self.fixture.guard.side_effect = lambda: setattr(self.fixture.clock, "end", 1400.0)
        with self.assertRaisesRegex(opening.SourceColorOpeningError, "original input/claim/clock"):
            self.fixture.execute()
        self.fixture.worker.assert_not_called()

    def test_initial_staging_file_hold_precedes_first_caller_callback(self) -> None:
        """An adapter cannot introduce a callback ahead of the reader's original capture."""
        raw = self.fixture.sidecar_path.read_bytes()
        self.fixture.guard.reset_mock()

        def rewrite_once() -> None:
            """Rewrite only the exact TEST sidecar at the very first caller callback."""
            if self.fixture.guard.call_count == 1:
                self.fixture.change(self.fixture.sidecar_path, raw)

        self.fixture.guard.side_effect = rewrite_once
        with self.assertRaises(opening.SourceColorOpeningError):
            self.fixture.execute()
        self.fixture.worker.assert_not_called()

    def test_first_callback_cannot_replace_original_guard_or_inputs(self) -> None:
        """A matching-looking replacement context cannot establish a new baseline."""
        original = self.fixture.authority.guard
        self.fixture.guard.side_effect = lambda: object.__setattr__(self.fixture.authority, "guard", Mock())
        with self.assertRaisesRegex(opening.SourceColorOpeningError, "original input/claim/clock"):
            self.fixture.execute()
        object.__setattr__(self.fixture.authority, "guard", original)
        self.fixture.guard.side_effect = lambda: self.fixture.inputs.documents["candidatePlan"].update(TEST="changed")
        with self.assertRaisesRegex(opening.SourceColorOpeningError, "original input/claim/clock"):
            self.fixture.execute()
        self.fixture.worker.assert_not_called()

    def test_existing_timer_refused_without_replacing_or_running_work(self) -> None:
        """The adapter cannot put existing batch cleanup beneath an unrelated wall timer."""
        with patch.object(opening.signal, "getitimer", return_value=(10.0, 0.0)), \
                patch.object(opening.signal, "setitimer") as timer, \
                self.assertRaisesRegex(RuntimeError, "outside another phase timer"):
            self.fixture.execute()
        timer.assert_not_called()
        self.fixture.worker.assert_not_called()

    def test_original25_minute_cap_and_exact_numeric_type_are_retained(self) -> None:
        """Do not accept a longer entry allowance or late float-to-int clock substitution."""
        self.fixture.clock.end = 2500.1
        with self.assertRaisesRegex(ValueError, "original25-minute"):
            self.fixture.execute()
        self.fixture.clock.end = 1300.0
        self.fixture.guard.side_effect = lambda: setattr(self.fixture.clock, "end", 1300)
        with self.assertRaisesRegex(opening.SourceColorOpeningError, "original input/claim/clock"):
            self.fixture.execute()
        self.fixture.worker.assert_not_called()

    def test_all_staged_job_raw_sizes_and_implementation_hash_are_joined(self) -> None:
        """Preflight binds all staged ref fields to actual held files without re-reading."""
        original = deepcopy(self.fixture.sidecar)
        mutations = [(key, "sizeBytes") for key in ("input", "implementation", "launchClaim")]
        mutations.append(("implementation", "sha256"))
        for key, field in mutations:
            self.fixture.sidecar = deepcopy(original)
            ref = self.fixture.sidecar["jobs"][1][key]
            ref[field] = ref[field] + 1 if field == "sizeBytes" else "a" * 64
            self.fixture.republish_sidecar()
            self._assert_bad_raw_ref()
        self.fixture.worker.assert_not_called()

    def _assert_bad_raw_ref(self) -> None:
        """Keep the complete real preflight negative outside the test's mutation loop."""
        with self.assertRaisesRegex(opening.SourceColorOpeningError, "staged raw job reference differs"):
            self.fixture.execute()

    def test_late_reservation_mutation_stops_before_first_native_dispatch(self) -> None:
        """After preflight, a transient guard still requires the original active bytes."""
        actual = opening.prepare_source_color_batch

        def retire(preparation: object, refs: tuple) -> object:
            """Change only named TEST active.json after actual preflight returns."""
            result = actual(preparation, refs)
            self.fixture.retired_reservation()
            return result

        with patch.object(opening, "prepare_source_color_batch", side_effect=retire), \
                self.assertRaises(opening.SourceColorOpeningError):
            self.fixture.execute()
        self.fixture.worker.assert_not_called()

    def test_actual_runner_return_cannot_be_replaced_before_final_validation(self) -> None:
        """Final callback mutations do not bless changed actual completed observations."""
        actual = opening.run_source_color_batch
        returned = []

        def arm(batch: object) -> object:
            """Arm only after actual native-stub work and immutable completion return."""
            result = actual(batch)
            returned.append(result)
            self.fixture.guard.side_effect = mutate
            return result

        def mutate() -> None:
            """Mutate only synthetic TEST typed output, never source or dependency bytes."""
            object.__setattr__(returned[0].observations[0].observation, "grade_applicable", True)

        with patch.object(opening, "run_source_color_batch", side_effect=arm), \
                self.assertRaises(opening.SourceColorOpeningError) as caught:
            self.fixture.execute()
        self.assertEqual(caught.exception.stage, "completion")
        self.assertEqual(len(caught.exception.timings), 2)

    def test_prior_events_and_actual_event_list_cannot_be_rebased(self) -> None:
        """Maintain the original full opening event reference and unchanged prior rows."""
        self.fixture.clock.events.append({"stage": "TEST original", "elapsedMs": 1})
        self.fixture.guard.side_effect = lambda: self.fixture.clock.events[0].update(elapsedMs=0)
        with self.assertRaisesRegex(opening.SourceColorOpeningError, "event history changed"):
            self.fixture.execute()
        self.fixture.guard.side_effect = lambda: setattr(self.fixture.clock, "events", [])
        with self.assertRaisesRegex(opening.SourceColorOpeningError, "event history changed|clock/guard/events changed"):
            self.fixture.execute()
        self.fixture.worker.assert_not_called()

    def test_final_event_validation_cannot_extend_original_deadline(self) -> None:
        """Check original time after final event serialization, not only inside its phase."""
        actual = opening._phase

        def expire(read: object, name: str, operation: object) -> object:
            """Run the real phase and expire only after final completion bookkeeping."""
            result = actual(read, name, operation)
            if name == "completion":
                self.fixture.now = self.fixture.clock.end
            return result

        with patch.object(opening, "_phase", side_effect=expire), \
                self.assertRaises(opening.SourceColorOpeningError) as caught:
            self.fixture.execute()
        self.assertEqual(caught.exception.stage, "completion")
        self.assertEqual(len(caught.exception.timings), 2)


if __name__ == "__main__":
    unittest.main()

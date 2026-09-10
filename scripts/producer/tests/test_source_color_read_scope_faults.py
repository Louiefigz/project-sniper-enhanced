"""Adversarial finite outer scope checks, with no native or approval substitutes.

Pipeline discovery is an explicit inert TEST leaf. The final-call regression
stubs legacy media verification only to reach its immediate return boundary;
it does not claim a completed media read or a genuine consumption proof.
"""
from __future__ import annotations

from copy import copy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from _source_color_read_scope_fixture import ColdReadScopeFixture
import guided_source_color_read as reader
import guided_source_color_read_scope as module
from guided_source_color_read_scope import SourceColorReadScope


class ColdReadScopeFaultTests(unittest.TestCase):
    """Every filesystem mutation is an original allowlisted inert TEMP control."""

    def setUp(self) -> None:
        """Hold one original fake read clock while using actual metadata/file guards."""
        self.now = [1000.0]
        timer = patch("time.monotonic", side_effect=lambda: self.now[0])
        timer.start()
        self.addCleanup(timer.stop)
        self.f = ColdReadScopeFixture()
        self.addCleanup(self.f.cleanup)
        self.leaves = self.f.leaves()
        self.addCleanup(self.leaves.close)

    def test_scope_never_opens_retired_socket_active_or_source_bytes(self) -> None:
        """The actual finite scope uses metadata, not live resource or source-byte reads."""
        forbidden = {self.f.runtime["dockerPath"], self.f.runtime["dockerSocketPath"],
                     self.f.references["reservation"]["path"]}
        forbidden.update(row.path for row in self.f.inputs.verified_media.snapshots)
        original = module.read_bytes

        def read(path: Path, maximum: int) -> bytes:
            """Intercept only raw scope reads, leaving the actual bounded reader intact."""
            self.assertNotIn(str(path), forbidden)
            return original(path, maximum)

        with patch.object(module, "read_bytes", side_effect=read):
            scope = self.f.scope()
        with patch.object(module, "read_bytes", side_effect=AssertionError("raw replay")):
            scope.check()
            scope.assert_metadata()

    def test_later_claim_rewrite_is_not_a_new_file_baseline(self) -> None:
        """Same bytes do not excuse a changed original raw-file identity."""
        scope = self.f.scope()
        self.f.replace(self.f.held_claim.path)
        with self.assertRaisesRegex(RuntimeError, "file|ancestry"):
            scope.assert_metadata()

    def test_captured_file_inventory_cannot_be_cleared(self) -> None:
        """A mutable holder must not erase the earlier exact control-file proof."""
        scope = self.f.scope()
        scope.files.clear()
        with self.assertRaises(RuntimeError):
            SourceColorReadScope.assert_metadata(scope)

    def test_copied_scope_has_no_private_registration(self) -> None:
        """Copying Python fields does not copy the original read's private provenance."""
        scope = self.f.scope()
        with self.assertRaises((RuntimeError, ValueError, KeyError)):
            SourceColorReadScope.assert_metadata(copy(scope))

    def test_class_dispatched_check_cannot_delegate_to_shadowed_metadata_method(self) -> None:
        """Residual RED: original bound check still dynamically called an instance shadow."""
        scope = self.f.scope()
        self.f.replace(self.f.held_claim.path)
        scope.assert_metadata = lambda: None
        with self.assertRaises(RuntimeError):
            SourceColorReadScope.check(scope)

    def test_missing_replay_groups_cannot_report_a_complete_final_sweep(self) -> None:
        """Data capture alone never proves actual raw observations and base consumption."""
        scope = self.f.scope()
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            SourceColorReadScope.final_check(scope)

    def test_unregistered_replay_objects_cannot_supply_noop_final_guards(self) -> None:
        """Mutable DTOs cannot replace either actual privately registered child read."""
        scope = self.f.scope()
        scope.observations = SimpleNamespace(check=lambda: None, assert_metadata=lambda: None)
        scope.consumption = SimpleNamespace(check=lambda: None, assert_metadata=lambda: None)
        with self.assertRaisesRegex(RuntimeError, "holders"):
            SourceColorReadScope.final_check(scope)

    def test_late_capture_cannot_renew_an_existing_control_identity(self) -> None:
        """Setup is sealed before later read phases or arbitrary media callbacks."""
        scope = self.f.scope()
        with self.assertRaisesRegex(RuntimeError, "late|baseline|setup"):
            scope._capture(self.f.held_claim.path, self.f.held_claim.sha256, 128 * 1024)

    def test_source_parent_identity_is_checked_separately_from_source_file(self) -> None:
        """A TEST stat leaf changes only original source-ancestor identity, not bytes."""
        scope = self.f.scope()
        original = module._directory_states

        def states(paths: tuple) -> tuple:
            """Simulate an ancestor replacement without touching any fixture source."""
            value = original(paths)
            return (*value, ("TEST changed ancestor",)) if paths == scope.source_parents else value

        with patch.object(module, "_directory_states", side_effect=states):
            with self.assertRaisesRegex(RuntimeError, "ancestry"):
                scope.assert_metadata()

    def test_original_read_cutoff_cannot_be_replaced_with_longer_clock(self) -> None:
        """Historical phase expiry is unrelated to this exact current read cutoff."""
        scope = self.f.scope()
        self.f.clock.end = 1600.0
        with self.assertRaises(RuntimeError):
            scope.assert_metadata()

    def test_original_completed_stage_prefix_cannot_be_changed_later(self) -> None:
        """Permanent RED: stable list identity did not hold its original completed rows."""
        self.f.clock.events.append({"stage": "held-result", "status": "complete", "elapsedMs": 1})
        scope = self.f.scope()
        self.f.clock.events[0]["status"] = "failed"
        with self.assertRaises(RuntimeError):
            SourceColorReadScope.assert_metadata(scope)

    def test_actual_observation_child_retains_raw_files_without_replay(self) -> None:
        """Real bounded metadata replay works beneath the outer original-control scope."""
        scope = self.f.scope()
        SourceColorReadScope.replay_observations(scope)
        self.assertEqual(scope.observations.record, self.f.section)
        with patch("guided_source_color_observation_replay._lines", side_effect=AssertionError("second replay")):
            scope.observations.check()
        self.f.replace(Path(self.f.sections[0]["artifacts"]["frames"]["path"]))
        with self.assertRaisesRegex(RuntimeError, "metadata file"):
            scope.observations.assert_metadata()

    def test_final_legacy_callback_cannot_replace_outer_scope_final_method(self) -> None:
        """Permanent RED: direct instance dispatch skipped changed files and both groups."""
        scope = self.f.scope()

        def late(_context: tuple, _selected: tuple) -> None:
            """Exact named TEST claim rewrite at the final legacy-verification return."""
            self.f.replace(self.f.held_claim.path)
            scope.final_check = lambda: None

        context = self.f.output, self.f.authority, self.f.inputs, scope.pipeline, self.f.record
        with patch.object(reader, "_unchanged", side_effect=late):
            with self.assertRaises(RuntimeError):
                reader._verify(context, (None, None), scope)


if __name__ == "__main__":
    unittest.main()

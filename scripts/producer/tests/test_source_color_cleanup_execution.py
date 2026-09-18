"""Actual orchestration/readers with explicit TEST runtime/daemon boundaries."""
from __future__ import annotations

import os
import signal
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from _source_color_cleanup_execution_fixture import SourceColorCleanupExecutionFixture
from guided_opening_cleanup import cleanup
import guided_opening_cleanup as opening_cleanup
import guided_source_color_cleanup_execution as execution
import guided_source_color_staging_files as files


class SourceColorCleanupExecutionTests(unittest.TestCase):
    """No real executable, socket, daemon, media or process settlement is qualified."""

    def fixture(self, orders: tuple[int, ...] = ()) -> SourceColorCleanupExecutionFixture:
        """Allocate one exact private TEST root and retain failures until test cleanup."""
        value = SourceColorCleanupExecutionFixture(orders)
        self.addCleanup(value.close)
        return value

    def test_real_claim_cold_reader_coordinator_and_exact_v2_stage_order(self) -> None:
        """Partial staging is sufficient, with exact real metadata reads and virtual names."""
        f = self.fixture((1, 3))
        original = f.retained()
        with patch.object(files, "read_bytes", wraps=files.read_bytes) as reads:
            result = f.run()
        self.assertEqual(reads.call_count, 3)
        self.assertEqual({call.args[0] for call in reads.call_args_list}, f.base.allowed)
        self.assertEqual(result["schemaVersion"], 2)
        self.assertEqual([row["stage"] for row in result["stages"]], ["cleanup-claim-and-controls", "source-color-reservation-read",
                         "reconcile-graphic-1", "reconcile-graphic-3", "cleanup-controls-after", "reconcile-source-color-batch",
                         "source-color-reservation-after"])
        self.assertEqual([row["state"] for row in result["graphics"]], ["not-initialized", "not-initialized"])
        self.assertEqual([row["containerName"] for row in result["sourceColor"]["batch"]["jobs"]], list(f.names))
        self.assertEqual(result["processGroupStopped"], "requires-owned-server-observation")
        self.assertIs(result["openingApproved"], False)
        self.assertEqual(f.retained(), original)
        self.assertEqual(list(f.output.iterdir()), [])
        self.assertFalse(f.base.staging.sidecar_path.exists())
        self.assertTrue(all(not Path(row["directory"]).exists() for row in f.base.reservation["jobs"]))
        self.assertEqual(f.admission.call_count, 1)
        self.assertEqual(f.final_admission.call_count, 2)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)

    def test_claim_setup_consumes_original_allowance_before_any_native(self) -> None:
        """A completed slow metadata setup cannot mint a fresh cleanup clock."""
        f, original = self.fixture(), execution.read_execution_claim

        def delayed(paths: tuple, refs: tuple) -> object:
            """Delay only the TEST clock after the actual original claim reader."""
            result = original(paths, refs)
            f.sleep(31)
            return result

        with patch.object(execution, "read_execution_claim", side_effect=delayed):
            with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
                f.run()
        self.assertEqual(f.events, [])
        self.assertEqual(list(f.output.iterdir()), [])

    def test_original_tool_identity_is_captured_before_runtime_admission_callback(self) -> None:
        """Same bytes rewritten during admission cannot become a new tool baseline."""
        f = self.fixture()
        f.admission.side_effect = lambda *_: f.mutate_control(f.docker)
        with self.assertRaisesRegex(RuntimeError, "tool/socket/approval changed"):
            f.run()
        self.assertEqual(f.events, [])

    def test_tool_and_approval_changes_during_native_cleanup_are_rejected(self) -> None:
        """Every name shares initial stat/parents, not per-name rehashed current files."""
        for field in ("docker", "approval"):
            f = self.fixture()
            before = f.retained()
            f.before_remove.side_effect = lambda *_: f.mutate_control(getattr(f, field))
            with self.assertRaisesRegex(RuntimeError, "tool/socket/approval changed"):
                f.run()
            self.assertEqual(f.retained(), before)
            self.assertTrue(f.base.reservation_path.exists())

    def test_changed_request_or_actual_runtime_never_returns_cleanup_success(self) -> None:
        """Exact original metadata remains held across real coordinator leaf callbacks."""
        f = self.fixture()
        f.before_remove.side_effect = lambda *_: object.__setattr__(f.request, "source_color_hash", "0" * 64)
        with self.assertRaisesRegex(RuntimeError, "original invocation"):
            f.run()
        f = self.fixture()
        f.before_remove.side_effect = lambda runtime, *_: object.__setattr__(runtime, "user_id", "502:20")
        with self.assertRaisesRegex(RuntimeError, "original"):
            f.run()

    def test_final_runtime_callback_still_holds_original_reservation_stat(self) -> None:
        """A post-batch same-byte reservation write cannot escape the final outer hold."""
        f = self.fixture()

        def after(_runtime: dict, _snapshot: str) -> None:
            """Write only the explicit TEST reservation on the final runtime admission."""
            if f.final_admission.call_count == 2:
                path = f.base.reservation_path
                f.base.write(path, path.read_bytes())

        f.final_admission.side_effect = after
        with self.assertRaisesRegex(RuntimeError, "file or ancestry changed"):
            f.run()
        self.assertTrue(f.events)
        self.assertTrue(f.base.reservation_path.exists())

    def test_final_verification_and_exact_local_cleanup_are_in_total_original_time(self) -> None:
        """Truthful stage subsets do not hide final metadata/local-cleanup overhead."""
        f, original = self.fixture(), os.rmdir
        f.final_admission.side_effect = lambda *_: f.sleep(2) if f.final_admission.call_count == 2 else None

        def remove(path: Path) -> None:
            """Remove only the real owned TEST config and charge the same virtual clock."""
            self.assertEqual(path.parent, f.output)
            self.assertTrue(path.name.startswith("source-color-cleanup-"))
            original(path)
            f.sleep(1)

        with patch.object(execution.os, "rmdir", side_effect=remove):
            result = f.run()
        self.assertEqual(result["elapsedMs"], 6000)
        self.assertEqual(result["sourceColor"]["batch"]["elapsedMs"], 3000)
        self.assertEqual(result["stages"][-2]["elapsedMs"], 3000)
        self.assertEqual(list(f.output.iterdir()), [])

    def test_failure_or_expiry_never_deletes_original_reservation_or_claim(self) -> None:
        """Incomplete absence remains failure, retaining exact original metadata bytes."""
        f = self.fixture()
        before = f.retained()
        with self.assertRaisesRegex(RuntimeError, "deadline"):
            f.run(2.0)
        self.assertEqual(f.retained(), before)
        self.assertTrue(list(f.output.iterdir()))
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)

    def test_unknown_request_fields_and_bad_namespace_reject_before_any_read(self) -> None:
        """The new fourth argument is closed and cannot select arbitrary metadata."""
        f = self.fixture()
        bad = replace(f.request, reservation_path=f.root / "elsewhere.json")
        with patch.object(execution, "hold_launch_file") as reads:
            with self.assertRaisesRegex(ValueError, "resource reservation"):
                cleanup(f.paths, f.refs, 30, bad)
            with self.assertRaisesRegex(ValueError, "exact original invocation"):
                cleanup(f.paths, f.refs, 30, vars(f.request))
            object.__setattr__(f.request, "processesStopped", True)
            with self.assertRaises((ValueError, RuntimeError)):
                f.run()
        reads.assert_not_called()

    def test_original_wall_timer_interrupts_blocking_initial_claim_setup(self) -> None:
        """Actual SIGALRM bounds the TEST blocking leaf before any native cleanup."""
        real_sleep = time.sleep
        f = self.fixture()

        def blocked(_paths: tuple, _refs: tuple) -> None:
            """Sleep only within a tiny TEST setup leaf; no process is created."""
            self.assertGreater(signal.getitimer(signal.ITIMER_REAL)[0], 0)
            real_sleep(0.1)

        with patch.object(execution, "read_execution_claim", side_effect=blocked):
            with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
                f.run(0.02)
        self.assertEqual(f.events, [])
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)

    def test_failed_config_removal_preserves_primary_error_and_original_files(self) -> None:
        """Only the exact new config is a removal target; failures cannot erase claims."""
        f = self.fixture()
        before, failure = f.retained(), OSError("TEST exact config removal unavailable")
        with patch.object(execution.os, "rmdir", side_effect=failure) as remove:
            with self.assertRaises(OSError) as raised:
                f.run()
        self.assertIs(raised.exception, failure)
        self.assertEqual(f.retained(), before)
        self.assertTrue(raised.exception.__notes__)
        self.assertTrue(all(call.args[0].parent == f.output for call in remove.call_args_list))
        self.assertEqual(len(list(f.output.iterdir())), 1)

    def test_unknown_config_contents_are_retained_without_recursive_cleanup(self) -> None:
        """An unanticipated config artifact stays intact; no broad cleanup is inferred."""
        f, created = self.fixture(), []

        def artifact(_runtime: object, config: str, _name: str) -> None:
            """Create one new-only TEST file under the exact owned runtime config."""
            if created:
                return
            path = Path(config) / "TEST-retain-on-failure"
            self.assertEqual(path.parent.parent, f.output)
            self.assertEqual(path.parent.resolve(strict=True), path.parent)
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            os.close(descriptor)
            created.append(path)

        f.before_remove.side_effect = artifact
        with self.assertRaises(OSError):
            f.run()
        self.assertEqual(len(created), 1)
        self.assertTrue(created[0].is_file())
        self.assertTrue(f.base.reservation_path.is_file())

    def test_actual_graphic_return_cannot_drift_during_later_control_callback(self) -> None:
        """Preserve existing graphic evidence instead of baselining it after grade cleanup."""
        f, observed, original = self.fixture((1,)), [], opening_cleanup.reconcile_order

        def observe(claim: object, order: int) -> dict:
            """Retain the actual no-start graphic owner result, with no native stub."""
            row = original(claim, order)
            observed.append(row)
            return row

        f.final_admission.side_effect = lambda *_: observed[0].update(cleanupVerified=False)
        with patch.object(opening_cleanup, "reconcile_order", side_effect=observe):
            with self.assertRaisesRegex(RuntimeError, "original graphic result changed"):
                f.run()
        self.assertEqual(f.events, [])


    def _assert_final_claim_mutation(self, field: str) -> None:
        """Mutate only the actual returned TEST object after grade absence, not files."""
        f, returned, original = self.fixture(), [], execution.read_execution_claim
        before = f.retained()

        def capture(paths: tuple, refs: tuple) -> object:
            """Retain the same actual claim returned by the real metadata reader."""
            claim = original(paths, refs)
            returned.append(claim)
            return claim

        def change(_runtime: dict, _snapshot: str) -> None:
            """Change its raw reference only during the last runtime verification."""
            if f.final_admission.call_count == 2:
                value = "0" * 64 if field == "sha256" else f.root / "TEST-unrelated-claim.json"
                object.__setattr__(returned[0], field, value)

        f.final_admission.side_effect = change
        with patch.object(execution, "read_execution_claim", side_effect=capture):
            with self.assertRaisesRegex(RuntimeError, "original claim return changed"):
                f.run()
        self.assertEqual(f.final_admission.call_count, 2)
        self.assertTrue(f.events)
        self.assertEqual(f.retained(), before)

    def test_final_runtime_callback_cannot_change_actual_claim_sha(self) -> None:
        """A final same-object SHA mutation cannot be emitted as verified cleanup."""
        self._assert_final_claim_mutation("sha256")

    def test_final_runtime_callback_cannot_change_actual_claim_path(self) -> None:
        """A final same-object path mutation cannot redirect cleanup evidence."""
        self._assert_final_claim_mutation("path")


if __name__ == "__main__":
    unittest.main()

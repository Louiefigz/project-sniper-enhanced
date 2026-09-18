"""Actual three-file reads under TEST provenance; no cleanup, process or admission."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch

from _source_color_reservation_fixture import SourceColorReservationFixture
from guided_source_color_reservation_read import read_source_color_reservation
import guided_source_color_reservation_read as reader
import guided_source_color_staging_files as files


class SourceColorReservationReadTests(unittest.TestCase):
    """Cold controller metadata joins and unchanged original raw/stat lifetimes."""

    def setUp(self) -> None:
        """Create only fixture metadata and borrow a virtual original absolute clock."""
        self.fixture = SourceColorReservationFixture()
        self.addCleanup(self.fixture.close)
        timer = patch("color.deadline.time.monotonic", side_effect=lambda: self.fixture.staging.now)
        timer.start()
        self.addCleanup(timer.stop)

    def test_partial_publication_reads_exact_three_files_and_no_current_pid(self) -> None:
        """Old owner PID is inert; nonexistent sidecar and all job files are acceptable."""
        f = self.fixture
        with patch.object(files, "read_bytes", wraps=files.read_bytes) as reads, \
                patch("os.getppid", side_effect=AssertionError("no live controller PID check")), \
                patch("subprocess.Popen", side_effect=AssertionError("no process")):
            held = f.run()
            held.assert_current()
        self.assertEqual({call.args[0] for call in reads.call_args_list}, f.allowed)
        self.assertEqual(reads.call_count, 3)
        self.assertEqual(held.container_names, tuple(row["containerName"] for row in f.reservation["jobs"]))
        self.assertEqual(held.value["ownerPid"], 1234)
        self.assertEqual(held.size_bytes, f.reservation_path.stat().st_size)
        self.assertFalse(f.staging.sidecar_path.exists())
        self.assertTrue(all(not Path(row["directory"]).exists() for row in held.value["jobs"]))

    def test_raw_hashes_and_original_request_hash_cannot_be_replaced(self) -> None:
        """A semantic request or equivalent JSON is not the supplied raw reservation ref."""
        f = self.fixture
        with self.assertRaisesRegex(RuntimeError, "raw bytes differ"):
            read_source_color_reservation((f.reservation_path, "0" * 64), f.context)
        f.reservation["sourceColorHash"] = "0" * 64
        f.publish()
        with self.assertRaisesRegex(RuntimeError, "lineage differs"):
            f.run()

    def test_original_claim_runtime_and_all_opening_references_remain_exact(self) -> None:
        """Shape-valid mutually edited reservation fields cannot substitute original refs."""
        f = self.fixture
        f.reservation["runtime"]["userId"] = "502:20"
        f.publish()
        with self.assertRaisesRegex(RuntimeError, "lineage differs"):
            f.run()
        f.reservation["runtime"]["userId"] = f.context.opening.value["runtime"]["userId"]
        f.reservation["opening"]["claimSha256"] = "0" * 64
        f.publish()
        with self.assertRaisesRegex(RuntimeError, "lineage differs"):
            f.run()

    def test_first_callback_cannot_rebaseline_any_initial_file(self) -> None:
        """All three actual inode identities are captured before the original guard."""
        f = self.fixture
        f.staging.guard.side_effect = lambda: f.write(f.input_path, f.input_path.read_bytes())
        with patch.object(files, "read_bytes", wraps=files.read_bytes) as reads:
            with self.assertRaisesRegex(RuntimeError, "file or ancestry changed"):
                f.run()
        reads.assert_not_called()

    def test_context_replacement_and_expired_entry_fail_before_raw_reads(self) -> None:
        """No guard swap, fresh deadline or invalid cutoff is adopted by the reader."""
        f = self.fixture
        for deadline in (True, float("nan"), 1000.0):
            with patch.object(reader, "capture_staging_file") as captures, self.assertRaises((ValueError, RuntimeError)):
                read_source_color_reservation(f.reference, replace(f.context, deadline=deadline))
            captures.assert_not_called()
        f.staging.guard.side_effect = lambda: object.__setattr__(f.context, "deadline", 1400.0)
        with self.assertRaisesRegex(RuntimeError, "original context"):
            f.run()

    def test_wrong_namespace_never_reads_an_alternative_resource_or_input(self) -> None:
        """Only original canonical claim/input and supplied namespace can be opened."""
        f = self.fixture
        for context in (replace(f.context, resource_dir=f.root / "other/.sniper-color-resource"),
                        replace(f.context, producer_dir=f.root / "other-producer")):
            with patch.object(reader, "capture_staging_file") as capture, self.assertRaisesRegex(ValueError, "escaped original"):
                read_source_color_reservation(f.reference, context)
            capture.assert_not_called()

    def test_raw_claim_projection_and_input_semantic_hash_are_checked(self) -> None:
        """Typed claim metadata is not trusted in place of original bytes or input hash."""
        f = self.fixture
        f.context.opening.value["budgetAdmissionHash"] = "0" * 64
        with self.assertRaisesRegex(RuntimeError, "raw projection differs"):
            f.run()
        f.staging.input["executionInputHash"] = "0" * 64
        f.refresh()
        with self.assertRaisesRegex(RuntimeError, "input role/hash differs"):
            f.run()

    def test_actual_parser_return_is_retained_before_callback(self) -> None:
        """The actual parsed reservation cannot drift before a later projection baseline."""
        f, captured, original = self.fixture, [], reader.read_staging_file

        def observe(capture: object, sha: str, maximum: int) -> tuple:
            """Keep an actual TEST parsed return for the normal guard to mutate."""
            result = original(capture, sha, maximum)
            if capture.path == f.reservation_path:
                captured.append(result[1])
            return result

        f.staging.guard.side_effect = lambda: captured[0].update(ownerPid=5678) if captured else None
        with patch.object(reader, "read_staging_file", side_effect=observe):
            with self.assertRaisesRegex(RuntimeError, "parsed metadata changed"):
                f.run()

    def test_final_parser_result_and_final_filesystem_expiry_cannot_escape(self) -> None:
        """Detached parsed data and original remaining time both survive final callbacks."""
        f, captured, original = self.fixture, [], reader.validate_source_color_reservation

        def observe(value: object) -> dict:
            """Retain the actual pure validator output before the next guard."""
            result = original(value)
            captured.append(result)
            return result

        f.staging.guard.side_effect = lambda: captured[0].update(ownerPid=5678) if captured else None
        with patch.object(reader, "validate_source_color_reservation", side_effect=observe):
            with self.assertRaisesRegex(RuntimeError, "detached result changed"):
                f.run()
        f.staging.guard.side_effect = None
        held = f.run()
        with patch.object(reader, "check_staging_file", side_effect=lambda _: setattr(f.staging, "now", 1300.0)):
            with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
                held.assert_current()

    def test_planned_names_and_exact_files_remain_held_after_return(self) -> None:
        """Returned data grants no immutable-owner bypass or silent future file refresh."""
        f = self.fixture
        held = f.run()
        held.value["ownerPid"] = float(held.value["ownerPid"])
        with self.assertRaisesRegex(RuntimeError, "detached result changed"):
            held.assert_current()
        held.value["ownerPid"] = int(held.value["ownerPid"])
        f.write(f.reservation_path, f.reservation_path.read_bytes())
        with self.assertRaisesRegex(RuntimeError, "file or ancestry changed"):
            held.assert_current()


if __name__ == "__main__":
    unittest.main()

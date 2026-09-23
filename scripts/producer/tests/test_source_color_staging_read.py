"""Real four-file metadata reader with TEST input provenance and no native work."""
from __future__ import annotations

import os
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from _source_color_staging_read_fixture import SourceColorStagingReadFixture, _raw
from guided_source_color_staging_read import read_source_color_staging
import guided_source_color_staging_read as reader
import guided_source_color_staging_files as files


class SourceColorStagingReadTests(unittest.TestCase):
    """Original typed/raw bindings and data-only lifetime under one supplied clock."""

    def setUp(self) -> None:
        """Create inert metadata only and control the original monotonic clock."""
        self.fixture = SourceColorStagingReadFixture()
        self.addCleanup(self.fixture.close)
        timer = patch("color.deadline.time.monotonic", side_effect=lambda: self.fixture.now)
        timer.start()
        self.addCleanup(timer.stop)

    def test_exact_four_file_reader_does_not_read_jobs_sources_or_runtime(self) -> None:
        """Actual reads authenticate four raw files; declarations and jobs stay data."""
        f = self.fixture
        with patch.object(files, "read_bytes", wraps=files.read_bytes) as reads, \
                patch("subprocess.Popen", side_effect=AssertionError("no process")):
            held = f.run()
            held.assert_current()
        self.assertEqual({call.args[0] for call in reads.call_args_list}, f.allowed)
        self.assertEqual(reads.call_count, 4)
        self.assertEqual(held.value, f.sidecar)
        self.assertEqual([row["sourceId"] for row in held.value["jobs"]], ["raw-b", "raw-a"])
        self.assertIs(held.value["executable"], False)
        self.assertTrue(all(not Path(row["directory"]).exists() for row in held.value["jobs"]))

    def test_raw_sidecar_sha_and_reservation_sha_are_not_semantic_substitutes(self) -> None:
        """A caller or child ref must name the exact original bytes, not resealed JSON."""
        f = self.fixture
        with self.assertRaisesRegex(RuntimeError, "raw bytes differ"):
            read_source_color_staging((f.sidecar_path, "0" * 64), f.context)
        f.sidecar["reservation"]["sha256"] = "0" * 64
        f.republish_sidecar()
        with self.assertRaisesRegex(RuntimeError, "raw bytes differ"):
            f.run()

    def test_original_resource_path_is_fixed_before_reservation_read(self) -> None:
        """A syntactically valid alternative global marker cannot redirect a raw read."""
        f = self.fixture
        f.sidecar["reservation"]["path"] = str(f.root / "other/.sniper-color-resource/active.json")
        f.republish_sidecar()
        with patch.object(files, "read_bytes", wraps=files.read_bytes) as reads:
            with self.assertRaisesRegex(RuntimeError, "escaped original resource"):
                f.run()
        self.assertNotIn(Path(f.sidecar["reservation"]["path"]), [call.args[0] for call in reads.call_args_list])

    def test_size_and_runtime_must_match_actual_raw_and_original_claim(self) -> None:
        """No shape-valid raw size or runtime transplant becomes original evidence."""
        f = self.fixture
        f.sidecar["reservation"]["sizeBytes"] += 1
        f.republish_sidecar()
        with self.assertRaisesRegex(RuntimeError, "path/size differs"):
            f.run()
        f.reservation["runtime"]["userId"] = "502:20"
        f.republish_staging()
        with self.assertRaisesRegex(RuntimeError, "runtime/producer lineage"):
            f.run()

    def test_original_live_parent_pid_is_not_a_cold_cleanup_identity(self) -> None:
        """This live reader cannot adopt metadata from another or stopped controller."""
        f = self.fixture
        f.reservation["ownerPid"] = os.getppid() + 1
        f.republish_staging()
        with self.assertRaisesRegex(RuntimeError, "live parent/source order"):
            f.run()

    def test_same_set_different_job_order_rejects_original_first_kept_order(self) -> None:
        """Mutually edited plans still must equal the actual held cut first occurrences."""
        f = self.fixture
        f.sidecar["jobs"].reverse()
        f.reservation["jobs"].reverse()
        f.republish_staging()
        with self.assertRaisesRegex(RuntimeError, "live parent/source order"):
            f.run()

    def test_original_input_projection_and_clock_are_not_rebaselined(self) -> None:
        """Held typed inputs must match their actual raw record and original clock."""
        f = self.fixture
        f.inputs.value["profile"] = "TEST changed input"
        with self.assertRaisesRegex(RuntimeError, "raw projection differs"):
            f.run()
        f.inputs.value["profile"] = f.input["profile"]
        f.inputs.documents["authority"]["clockHash"] = "0" * 64
        with self.assertRaisesRegex(RuntimeError, "clock/order lineage"):
            f.run()

    def test_initial_all_four_stat_captures_precede_first_callback(self) -> None:
        """Same-byte reservation mutation in the first callback cannot become baseline."""
        f = self.fixture
        changed = []

        def mutate() -> None:
            """Touch only the explicitly allowed TEST reservation after initial capture."""
            if not changed:
                changed.append(True)
                f.write(f.reservation_path, f.reservation_path.read_bytes())

        f.guard.side_effect = mutate
        with patch.object(files, "read_bytes", wraps=files.read_bytes) as reads:
            with self.assertRaisesRegex(RuntimeError, "file or ancestry changed"):
                f.run()
        reads.assert_not_called()

    def test_late_original_files_and_returned_data_remain_held(self) -> None:
        """A successful data return never permits later raw or scalar-type changes."""
        f = self.fixture
        held = f.run()
        value = held.value["jobs"][0]["input"]
        value["sizeBytes"] = float(value["sizeBytes"])
        with self.assertRaisesRegex(RuntimeError, "detached result changed"):
            held.assert_current()
        value["sizeBytes"] = int(value["sizeBytes"])
        f.write(f.claim_path, f.claim_path.read_bytes() + b" ")
        with self.assertRaisesRegex(RuntimeError, "file or ancestry changed"):
            held.assert_current()

    def test_context_deadline_and_guard_replacements_are_not_adopted(self) -> None:
        """No callback can renew the same caller's remaining time or persistent guard."""
        f = self.fixture
        f.guard.side_effect = lambda: object.__setattr__(f.context, "deadline", 1400.0)
        with self.assertRaisesRegex(RuntimeError, "original context"):
            f.run()
        object.__setattr__(f.context, "deadline", 1300.0)
        f.guard.side_effect = lambda: object.__setattr__(f.context, "guard", lambda: None)
        with self.assertRaisesRegex(RuntimeError, "original context"):
            f.run()

    def test_actual_parser_return_is_held_before_later_callbacks(self) -> None:
        """A parser-return object cannot be mutated and then silently captured later."""
        f = self.fixture
        parsed = []
        original = reader.read_staging_file

        def observe(capture: object, sha: str, maximum: int) -> tuple:
            """Retain the actual TEST sidecar parser object without altering its raw bytes."""
            result = original(capture, sha, maximum)
            if capture.path == f.sidecar_path:
                parsed.append(result[1])
            return result

        f.guard.side_effect = lambda: parsed[0].update(executable=True) if parsed else None
        with patch.object(reader, "read_staging_file", side_effect=observe):
            with self.assertRaisesRegex(RuntimeError, "parsed metadata changed"):
                f.run()

    def test_contract_result_mutation_or_expiry_cannot_escape_final_guard(self) -> None:
        """Capture the pure projector return immediately and use the original cutoff."""
        f = self.fixture
        results = []
        original = reader.validate_source_color_staging

        def observe(sidecar: dict, reservation: dict) -> dict:
            """Retain only the actual detached pure result for a later TEST callback."""
            value = original(sidecar, reservation)
            results.append(value)
            return value

        f.guard.side_effect = lambda: results[0].update(executable=True) if results else None
        with patch.object(reader, "validate_source_color_staging", side_effect=observe):
            with self.assertRaisesRegex(RuntimeError, "detached result changed"):
                f.run()
        f.guard.side_effect = lambda: setattr(f, "now", 1300.0)
        with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            f.run()

    def test_final_filesystem_work_cannot_pass_expired_original_time(self) -> None:
        """The final retained stat sweep has a final original-deadline check."""
        f = self.fixture
        held = f.run()
        original = reader.check_staging_file

        def expire(value: object) -> None:
            """Expire only after a real TEST file stat check; no file is mutated."""
            original(value)
            f.now = 1300.0

        with patch.object(reader, "check_staging_file", side_effect=expire):
            with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
                held.assert_current()

    def test_additive_sidecar_budget_does_not_widen_original_input_budget(self) -> None:
        """A sidecar over128KiB is supported; original files retain their old cap."""
        f = self.fixture
        raw = b" " * (129 * 1024) + f.sidecar_path.read_bytes()
        f.reference = (f.sidecar_path, f.write(f.sidecar_path, raw))
        self.assertEqual(f.run().value, f.sidecar)
        raw = b" " * (129 * 1024) + f.input_path.read_bytes()
        input_sha = f.write(f.input_path, raw)
        f.claim["inputSha256"] = input_sha
        claim_sha = f.write(f.claim_path, _raw(f.claim))
        f.context = replace(f.context, inputs=replace(f.inputs, sha256=input_sha),
                            opening=replace(f.opening, sha256=claim_sha, value=f.claim))
        with self.assertRaisesRegex(RuntimeError, "exceeds byte limit: [0-9]+ > 131072"):
            f.run()

    def test_expired_or_malformed_context_does_not_read_files(self) -> None:
        """An expired original cutoff or boolean pseudo-cutoff is refused before IO."""
        f = self.fixture
        for deadline in (True, float("nan"), 1000.0):
            with patch.object(reader, "capture_staging_file") as captures, self.assertRaises((ValueError, RuntimeError)):
                read_source_color_staging(f.reference, replace(f.context, deadline=deadline))
            captures.assert_not_called()


if __name__ == "__main__":
    unittest.main()

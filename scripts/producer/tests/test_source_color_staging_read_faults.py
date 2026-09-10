"""Additional TEST-only metadata alias/parser/origin faults; no dependencies are mutated."""
from __future__ import annotations

import os
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from _source_color_staging_read_fixture import SourceColorStagingReadFixture
import guided_source_color_staging_read as reader


class SourceColorStagingReadFaultTests(unittest.TestCase):
    """Exact caller paths, original parser outputs and every held file remain closed."""

    def fixture(self) -> SourceColorStagingReadFixture:
        """Give every fault an independent exact temporary metadata tree."""
        result = SourceColorStagingReadFixture()
        self.addCleanup(result.close)
        timer = patch("color.deadline.time.monotonic", side_effect=lambda: result.now)
        timer.start()
        self.addCleanup(timer.stop)
        return result

    def test_symlink_and_hardlink_metadata_are_rejected_before_callback(self) -> None:
        """Alias faults link only fixture-owned bytes, never tools or external files."""
        for alias in ("symlink", "hardlink"):
            f = self.fixture()
            target = f.sidecar_path
            peer = target.with_name("TEST-owned-sidecar-copy.json")
            f.allowed |= {peer}
            f.write(peer, target.read_bytes())
            if alias == "symlink":
                target.unlink()
                target.symlink_to(peer)
            else:
                peer.unlink()
                os.link(target, peer)
            with self.assertRaisesRegex(RuntimeError, "private single-link"):
                f.run()
            f.guard.assert_not_called()

    def test_fault_writer_refuses_external_and_aliased_targets(self) -> None:
        """The mutation helper cannot write dependencies or follow a fixture alias."""
        f = self.fixture()
        with self.assertRaisesRegex(AssertionError, "explicit owned"):
            f.write(Path(__file__), b"TEST must never be written")
        f.sidecar_path.unlink()
        f.sidecar_path.symlink_to(f.claim_path)
        with self.assertRaisesRegex(AssertionError, "regular single-link"):
            f.write(f.sidecar_path, b"TEST must never follow an alias")

    def test_every_original_raw_file_remains_bound_after_return(self) -> None:
        """Mutating any one of the four named metadata files invalidates the lifetime."""
        for name in ("sidecar_path", "reservation_path", "claim_path", "input_path"):
            f = self.fixture()
            held = f.run()
            target = getattr(f, name)
            f.write(target, target.read_bytes() + b" ")
            with self.assertRaisesRegex(RuntimeError, "file or ancestry changed"):
                held.assert_current()

    def test_duplicate_keys_invalid_utf8_and_whole_sidecar_cap_reject(self) -> None:
        """No late-field JSON choice, replacement decoding or8MiB overflow is accepted."""
        f = self.fixture()
        for raw in (b'{"reservation":{},"reservation":{}}', b'{"TEST":"\xff"}', b" " * (8 * 1024 ** 2 + 1)):
            f.reference = (f.sidecar_path, f.write(f.sidecar_path, raw))
            with self.assertRaises((RuntimeError, ValueError, UnicodeDecodeError)):
                f.run()

    def test_wrong_execution_or_resource_context_never_reads_alternate_paths(self) -> None:
        """Known original refs fix the namespace before a reader can touch a substitute."""
        f = self.fixture()
        alternatives = (replace(f.context, producer_dir=f.root / "other-producer"),
                        replace(f.context, resource_dir=f.root / "wrong-resource"))
        for context in alternatives:
            with patch.object(reader, "capture_staging_file") as capture, self.assertRaisesRegex(ValueError, "escaped the original"):
                reader.read_source_color_staging(f.reference, context)
            capture.assert_not_called()

    def test_future_parent_pid_change_invalidates_live_read_only(self) -> None:
        """A stopped or reparented worker cannot reuse this live-context reader for cleanup."""
        f = self.fixture()
        held = f.run()
        with patch.object(reader.os, "getppid", return_value=os.getppid() + 1):
            with self.assertRaisesRegex(RuntimeError, "original context/files"):
                held.assert_current()

    def test_final_contract_serialization_expiry_never_returns_data(self) -> None:
        """The original deadline covers the pure final projection cost, without a new timer."""
        f = self.fixture()
        original = reader.validate_source_color_staging

        def expire(sidecar: dict, reservation: dict) -> dict:
            """Advance the same virtual clock after the actual detached parser return."""
            result = original(sidecar, reservation)
            f.now = 1300.0
            return result

        with patch.object(reader, "validate_source_color_staging", side_effect=expire):
            with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
                f.run()

    def test_candidate_cut_change_and_original_claim_swap_are_rejected(self) -> None:
        """No unchanged-source assumption is inferred from a typed input or claim wrapper."""
        f = self.fixture()
        f.inputs.documents["candidatePlan"]["cutTrack"].reverse()
        f.inputs.documents["candidatePlan"]["cutTrack"][0]["end"] = 2
        with self.assertRaisesRegex(RuntimeError, "unchanged nonempty"):
            f.run()
        f.inputs.documents["candidatePlan"] = deepcopy(f.inputs.documents["acceptedPlan"])
        f.guard.side_effect = lambda: object.__setattr__(f.context, "opening", replace(f.opening))
        with self.assertRaisesRegex(RuntimeError, "original context"):
            f.run()


if __name__ == "__main__":
    unittest.main()

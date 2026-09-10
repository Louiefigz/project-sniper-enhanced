"""Raw bootstrap run tokens must retain the existing pipeline-writer mapping."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cut_preview_io import digest, file_hash
from guided_opening_inputs import OpeningInputs
from guided_opening_pipeline import _pinned_run_id, observe_pipeline


class PinnedRunIdTest(unittest.TestCase):
    """Exercise JS non-Unicode regexp replacement, including UTF-16 truncation."""

    def test_real_bootstrap_token(self) -> None:
        """The actual failed integration token maps to its immutable lock token."""
        self.assertEqual(_pinned_run_id("2026-09-07T19:05:34.524Z:gg0gbuknmul"),
                         "2026-09-07T19_05_34.524Z_gg0gbuknmul")

    def test_historical_uuid_and_ascii_are_unchanged(self) -> None:
        """Previously working UUID/TEST tokens do not change their identity."""
        for value in ("test_RUN-v1.2", "514724fa-82e2-4270-bb74-daa8decac548"):
            with self.subTest(value=value):
                self.assertEqual(_pinned_run_id(value), value)

    def test_unsafe_ascii_and_unicode_use_utf16_units(self) -> None:
        """An astral character produces two underscores, like the TS writer."""
        self.assertEqual(_pinned_run_id("a:/\\\n\x00é😀z"), "a________z")
        self.assertEqual(_pinned_run_id("a\ud800b"), "a_b")

    def test_replacement_precedes_final_96_unit_slice(self) -> None:
        """Do not truncate Unicode code points or slice before replacement."""
        self.assertEqual(_pinned_run_id("discard" + "😀" + "z" * 95), "_" + "z" * 95)
        self.assertEqual(_pinned_run_id("x" * 200), "x" * 96)

    def test_empty_and_non_strings_reject(self) -> None:
        """No coercion of malformed authority identifiers into a lock token."""
        for value in ("", None, 1, True, [], {}):
            with self.subTest(value=value), self.assertRaisesRegex(RuntimeError, "run id is invalid"):
                _pinned_run_id(value)


class PipelineLockIdentityTest(unittest.TestCase):
    """The normalized token is only one check in the held lock/file closure."""

    def setUp(self) -> None:
        """Write one fresh real lock and independently bind its initial bytes."""
        self.directory = tempfile.TemporaryDirectory(prefix="sniper-run-id-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        (self.root / "files").mkdir()
        self.raw_id = "2026-09-07T19:05:34.524Z:gg0gbuknmul"
        self.rows = [{"path": "test-source.py", "hash": "a" * 64}]
        self.lock = {"schemaVersion": 1, "state": "pinned", "runId": _pinned_run_id(self.raw_id),
                     "digest": digest(self.rows), "files": self.rows}
        self.lock_path = self.root / "pipeline-lock.json"
        self.lock_path.write_text(json.dumps(self.lock), encoding="utf-8")
        value = {"pipeline": {"snapshotRoot": str(self.root / "files"),
                 "lockPath": str(self.lock_path), "lockSha256": file_hash(self.lock_path),
                 "digest": self.lock["digest"]}}
        self.inputs = OpeningInputs(self.root / "input.json", "b" * 64, value,
            {"authority": {"runId": self.raw_id}, "readinessPacket": {"proposal": {"schemaVersion": 6}}})

    def _observe(self) -> dict:
        """Stub the expensive file/tool closure, never the real held lock read."""
        with patch("guided_opening_pipeline._files", return_value={"test-source.py": "a" * 64}) as files, \
                patch("guided_opening_pipeline._execution_closure", return_value=[]) as closure, \
                patch("guided_opening_pipeline._tools", return_value={}):
            result = observe_pipeline(self.inputs)
        files.assert_called_once_with(self.lock, self.root / "files")
        closure.assert_called_once_with({"test-source.py": "a" * 64}, 6)
        return result

    def test_raw_bootstrap_token_with_writer_lock_passes(self) -> None:
        """The writer's actual token spelling reaches all remaining guards."""
        observed = self._observe()
        self.assertEqual(observed["pipelineDigest"], self.lock["digest"])
        self.assertEqual(observed["pinnedFileCount"], 1)
        self.assertEqual(self.inputs.documents["authority"]["runId"], self.raw_id)

    def test_other_run_rejects_before_file_or_tool_work(self) -> None:
        """Normalization does not permit an unrelated run to reuse this lock."""
        self.inputs.documents["authority"]["runId"] += "-other"
        with patch("guided_opening_pipeline._files") as files, \
                self.assertRaisesRegex(RuntimeError, "lock identity is stale"):
            observe_pipeline(self.inputs)
        files.assert_not_called()

    def test_raw_colon_lock_is_not_a_second_accepted_spelling(self) -> None:
        """Only the writer spelling works; there is no raw-or-normalized fallback."""
        self.lock["runId"] = self.raw_id
        self.lock_path.write_text(json.dumps(self.lock), encoding="utf-8")
        self.inputs.value["pipeline"]["lockSha256"] = file_hash(self.lock_path)
        with self.assertRaisesRegex(RuntimeError, "lock identity is stale"):
            observe_pipeline(self.inputs)

    def test_changed_lock_bytes_reject_with_original_held_hash(self) -> None:
        """A matching normalized token cannot bypass changed immutable bytes."""
        changed = copy.deepcopy(self.lock)
        changed["digest"] = "c" * 64
        self.lock_path.write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaises(RuntimeError):
            observe_pipeline(self.inputs)

    def test_file_guard_failure_still_propagates(self) -> None:
        """Accepting the token must not turn source drift into a valid pipeline."""
        with patch("guided_opening_pipeline._files", side_effect=RuntimeError("changed source")), \
                self.assertRaisesRegex(RuntimeError, "changed source"):
            observe_pipeline(self.inputs)

    def test_execution_closure_failure_still_propagates(self) -> None:
        """The invoked code check remains required after the pinned file check."""
        with patch("guided_opening_pipeline._files", return_value={}), \
                patch("guided_opening_pipeline._execution_closure", side_effect=RuntimeError("invoked drift")), \
                self.assertRaisesRegex(RuntimeError, "invoked drift"):
            observe_pipeline(self.inputs)


if __name__ == "__main__":
    unittest.main()

"""Shared reader/legacy alias parity with real tiny metadata, no observation.

Implementation closure discovery is explicitly TEST-stubbed to controlled rows;
the worker and shared reader entry hashes themselves are actual current bytes.
No source admission, decoder, process, timer or approval is produced here.
"""
from __future__ import annotations

import copy
import json
import os
import runpy
import stat
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from _grade_project_fixture import GradeProjectFixture
from color import grade_project as project
from color import grade_project_input as reader
from color.grade_observation_profile import V2, V2_PROFILE
from cut_preview_io import file_hash, write_new
from headless.durable_files import write_all


class GradeProjectInputTests(unittest.TestCase):
    """Retain actual immutable input/path/pin rules without invoking a worker."""

    def setUp(self) -> None:
        """Create fresh TEST-owned tiny bytes; no existing project is adopted."""
        self.fixture = GradeProjectFixture()
        self.addCleanup(self.fixture.cleanup)
        self.path = self.fixture.job / "input.json"
        self.entry = Path(reader.__file__).with_name("grade_project_worker.py").resolve()
        self.reader_path = Path(reader.__file__).resolve()
        self.code = self.fixture.root / "TEST-adapter.py"
        write_new(self.code, {"testOnly": True, "notSourceAdmission": True})
        self.rows = [{"path": str(path), "sha256": file_hash(path)}
                     for path in (self.code, self.entry, self.reader_path)]
        self.implementation = self.enterContext(patch.object(project, "implementation", return_value=self.rows[:1]))

    def _write(self, path: Path, value: object) -> str:
        """Fault only an exact owned regular TEST file, checking before truncation."""
        if not path.is_relative_to(self.fixture.root) or path.resolve(strict=True) != path:
            raise RuntimeError("TEST write escaped fixture")
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_uid != os.geteuid():
            raise RuntimeError("TEST write requires its single-link regular file")
        descriptor = os.open(path, os.O_WRONLY | os.O_NOFOLLOW)
        try:
            current = os.fstat(descriptor)
            if (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino):
                raise RuntimeError("TEST write target changed")
            raw = value if type(value) is bytes else json.dumps(value).encode("utf8")
            os.ftruncate(descriptor, 0)
            write_all(descriptor, raw)
        finally:
            os.close(descriptor)
        return file_hash(path)

    def _input(self, value: object, profile: str | None = None) -> dict:
        """Read only the newly authored exact TEST input hash."""
        return reader.read_grade_project_input(self.path, self._write(self.path, value), profile)

    def _inventory(self, rows: object) -> dict:
        """Publish TEST pins without fabricating implementation discovery."""
        path = self.fixture.job / "implementation.json"
        if path.exists():
            self._write(path, {"files": rows})
        else:
            write_new(path, {"files": rows})
        return {**self.fixture.value, "implementationSha256": file_hash(path)}

    def test_legacy_worker_names_are_the_same_shared_functions(self) -> None:
        """Preserve the historical callable names and exact current alias behavior."""
        from color import grade_project_worker as worker

        self.assertIs(worker._input, reader.read_grade_project_input)
        self.assertIs(worker._held_implementation, reader.verify_grade_project_implementation)
        expected = reader.read_grade_project_input(self.path, file_hash(self.path))
        self.assertEqual(worker._input(self.path, file_hash(self.path)), expected)
        self.assertEqual(expected, self.fixture.value)
        self.implementation.assert_not_called()

    def test_shared_module_loading_does_not_touch_path_or_import_worker(self) -> None:
        """Loading data helpers must not execute the worker's CLI import effects."""
        before_path, before_modules = sys.path[:], set(sys.modules)
        runpy.run_path(str(self.reader_path), run_name="TEST-shared-reader")
        self.assertEqual(sys.path, before_path)
        self.assertNotIn("color.grade_project_worker", set(sys.modules) - before_modules)
        self.implementation.assert_not_called()

    def test_raw_hash_required_not_only_matching_json(self) -> None:
        """Equivalent JSON spelling cannot replace the parent's original raw SHA."""
        original = file_hash(self.path)
        self._write(self.path, self.fixture.value)
        with self.assertRaisesRegex(RuntimeError, "differs from live owner"):
            reader.read_grade_project_input(self.path, original)

    def test_closed_top_level_rejects_omissions_extras_and_nonobject(self) -> None:
        """Keep every original key required without coercing nonobjects."""
        missing = {key: value for key, value in self.fixture.value.items() if key != "declaration"}
        for value in (missing, {**self.fixture.value, "allowRepair": True}, [], None, True):
            with self.subTest(value=type(value).__name__), self.assertRaisesRegex(RuntimeError, "schema is invalid"):
                self._input(value)

    def test_schema_numeric_and_owner_pid_types_remain_strict(self) -> None:
        """Equal-valued booleans/floats do not identify versions or real parents."""
        changes = (("schemaVersion", True), ("schemaVersion", 1.0), ("ownerPid", True),
                   ("ownerPid", float(os.getppid())), ("ownerPid", os.getppid() + 1))
        for key, value in changes:
            with self.subTest(key=key, value=value), self.assertRaises((RuntimeError, ValueError)):
                self._input({**self.fixture.value, key: value})

    def test_original_parent_pid_not_current_process_or_override(self) -> None:
        """A different actual parent rejects before implementation discovery."""
        with patch.object(reader.os, "getppid", return_value=self.fixture.value["ownerPid"] + 1):
            with self.assertRaisesRegex(RuntimeError, "held owner"):
                reader.read_grade_project_input(self.path, file_hash(self.path))
        self.implementation.assert_not_called()

    def test_v2_requires_exact_explicit_owner_profile(self) -> None:
        """Stored v2 metadata cannot activate its class without the owner flag."""
        value = {**self.fixture.value, "schemaVersion": 2, "policy": V2.project_policy, "profile": V2_PROFILE}
        with self.assertRaisesRegex(RuntimeError, "schema is invalid"):
            self._input(value)
        self.assertEqual(self._input(value, V2_PROFILE), value)
        with self.assertRaises((RuntimeError, ValueError)):
            self._input(self.fixture.value, V2_PROFILE)

    def test_unknown_profile_and_partial_v2_mirrors_reject(self) -> None:
        """All version, policy and profile mirrors must agree exactly."""
        value = {**self.fixture.value, "schemaVersion": 2, "policy": V2.project_policy, "profile": V2_PROFILE}
        for key, changed in (("schemaVersion", 1), ("profile", None), ("policy", self.fixture.value["policy"])):
            with self.subTest(key=key), self.assertRaises((RuntimeError, ValueError)):
                self._input({**value, key: changed}, V2_PROFILE)
        with self.assertRaises((RuntimeError, ValueError)):
            self._input({**value, "profile": "unknown"}, "unknown")

    def test_job_uuid_and_source_id_are_not_coerced_or_repaired(self) -> None:
        """Reject unsupported identity spellings instead of normalizing them."""
        changes = (("jobId", self.fixture.value["jobId"].upper()), ("jobId", 1),
                   ("sourceId", "../source"), ("sourceId", ""), ("sourceId", True))
        for key, value in changes:
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, "identities are invalid"):
                self._input({**self.fixture.value, key: value})

    def test_exact_expected_parent_set_and_raw_sha_values_required(self) -> None:
        """Plan, manifest and project parents retain their closed raw-hash map."""
        expected = self.fixture.value["expected"]
        cases = ([], {**expected, "extra": "a" * 64}, {**expected, "planSha256": True},
                 {**expected, "manifestSha256": "A" * 64}, {"planSha256": "a" * 64})
        for value in cases:
            with self.subTest(value=value), self.assertRaisesRegex(RuntimeError, "parent hashes"):
                self._input({**self.fixture.value, "expected": value})

    def test_original_job_path_cannot_be_a_valid_copy_elsewhere(self) -> None:
        """Correct raw bytes alone cannot authorize an unrelated attempt path."""
        path = self.fixture.root / "input.json"
        write_new(path, self.fixture.value)
        with self.assertRaisesRegex(RuntimeError, "owner-derived attempt"):
            reader.read_grade_project_input(path, file_hash(path))

    def test_bounded_utf8_and_hardlinked_inputs_reject(self) -> None:
        """Reject oversized, non-UTF8 and aliased inputs without invoking work."""
        for raw in (b"\xff", b" " * (128 * 1024 + 1)):
            self._write(self.path, raw)
            with self.assertRaises((RuntimeError, UnicodeError)):
                reader.read_grade_project_input(self.path, file_hash(self.path))
        self._write(self.path, self.fixture.value)
        os.link(self.path, self.fixture.root / "TEST-input-alias")
        with self.assertRaisesRegex(RuntimeError, "bounded regular file"):
            reader.read_grade_project_input(self.path, "a" * 64)

    def test_actual_worker_and_shared_reader_pins_both_required(self) -> None:
        """The extraction adds its own dependency without replacing the worker pin."""
        value = self._inventory(self.rows)
        reader.verify_grade_project_implementation(self.fixture.job, value)
        self.implementation.assert_called_once_with()
        for path, message in ((self.entry, "entry is absent"), (self.reader_path, "input reader is absent")):
            rows = [row for row in self.rows if row["path"] != str(path)]
            with self.subTest(path=path.name), self.assertRaisesRegex(RuntimeError, message):
                reader.verify_grade_project_implementation(self.fixture.job, self._inventory(rows))

    def test_wrong_current_worker_or_shared_raw_hash_cannot_borrow_other_pin(self) -> None:
        """Each exact entry needs its own actual current raw source digest."""
        for target in (self.entry, self.reader_path):
            rows = copy.deepcopy(self.rows)
            next(row for row in rows if row["path"] == str(target))["sha256"] = "a" * 64
            with self.subTest(target=target.name), self.assertRaisesRegex(RuntimeError, "absent from held source bytes"):
                reader.verify_grade_project_implementation(self.fixture.job, self._inventory(rows))

    def test_missing_or_changed_adapter_row_rejects_before_entry_fallback(self) -> None:
        """Entry pins cannot substitute for a missing actual adapter dependency."""
        for rows in (self.rows[1:], [{**self.rows[0], "sha256": "a" * 64}, *self.rows[1:]]):
            with self.assertRaisesRegex(RuntimeError, "code differs"):
                reader.verify_grade_project_implementation(self.fixture.job, self._inventory(rows))

    def test_inventory_bound_and_row_closure_remain_unchanged(self) -> None:
        """Keep row count, uniqueness, exact keys and scalar types bounded."""
        cases = ([], None, [self.rows[0]] * 4001, [self.rows[0], self.rows[0]],
                 [{**self.rows[0], "trusted": True}], [{"path": True, "sha256": "a" * 64}],
                 [{"path": str(self.code), "sha256": True}])
        for rows in cases:
            with self.subTest(rows=type(rows).__name__), self.assertRaisesRegex(RuntimeError, "inventory is invalid|rows are invalid"):
                reader.verify_grade_project_implementation(self.fixture.job, self._inventory(rows))

    def test_changed_raw_inventory_hash_rejects_before_discovery(self) -> None:
        """Reject raw inventory drift before consulting current implementation."""
        value = self._inventory(self.rows)
        self._write(self.fixture.job / "implementation.json", {"files": self.rows, "TEST-whitespace-change": True})
        with self.assertRaisesRegex(RuntimeError, "hash changed"):
            reader.verify_grade_project_implementation(self.fixture.job, value)
        self.implementation.assert_not_called()

    def test_null_or_malformed_implementation_hash_rejects_at_input(self) -> None:
        """Never admit None as permission to skip the subsequent raw hash check."""
        for sha in (None, True, 0, "", "a" * 63, "A" * 64, []):
            with self.subTest(sha=sha), self.assertRaisesRegex(RuntimeError, "implementation hash is invalid"):
                self._input({**self.fixture.value, "implementationSha256": sha})
        self.implementation.assert_not_called()

    def test_direct_implementation_verifier_requires_hash_before_io(self) -> None:
        """Protect the shared verifier even when a caller bypasses input parsing."""
        value = self._inventory(self.rows)
        for sha in (None, True, 0, "", "A" * 64):
            with patch.object(reader, "bound_json") as read, self.subTest(sha=sha), \
                    self.assertRaisesRegex(RuntimeError, "implementation hash is invalid"):
                reader.verify_grade_project_implementation(self.fixture.job, {**value, "implementationSha256": sha})
            read.assert_not_called()
        self.implementation.assert_not_called()


if __name__ == "__main__":
    unittest.main()

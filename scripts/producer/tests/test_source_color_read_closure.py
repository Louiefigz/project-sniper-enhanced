"""Actual static read-closure discovery and bounded hashing with TEST-only paths."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from _source_color_read_closure_fixture import ReadClosureFixture
import guided_opening_pipeline as pipeline
import render_effect_discovery as discovery


class SourceColorReadClosureTests(unittest.TestCase):
    """No old media inventory or snapshot is rewritten to satisfy current read code."""

    def setUp(self) -> None:
        """Retain one exact fake clock and actual inert current-code/lock inventory."""
        self.now = [1000.0]
        timer = patch("time.monotonic", side_effect=lambda: self.now[0])
        timer.start()
        self.addCleanup(timer.stop)
        self.f = ReadClosureFixture()
        self.addCleanup(self.f.cleanup)
        leaves = self.f.leaves()
        self.addCleanup(leaves.close)

    def test_real_ast_discovers_only_read_additions_without_rewriting_history(self) -> None:
        """Shared media receives no duplicate hash; actual current read-only code does."""
        before = deepcopy((self.f.lock, self.f.executed))
        refs = pipeline.read_closure_refs(self.f.lock, self.f.executed, self.f.capture_one)
        self.assertEqual([path.name for path, _sha in refs], ["guided_opening_read.py", "read_leaf.py"])
        self.f.capture(refs)
        with patch.object(pipeline, "file_hash", wraps=pipeline.file_hash) as hashed:
            pipeline.verify_read_closure(refs, self.f.guard)
        self.assertEqual([call.args[0] for call in hashed.call_args_list], [path for path, _sha in refs])
        self.assertEqual((self.f.lock, self.f.executed), before)

    def test_optional_ast_reader_parses_same_supplied_text_without_a_second_open(self) -> None:
        """Unhooked legacy discovery and explicitly supplied identical text produce equal roots."""
        entry = self.f.paths["guided_opening_read.py"]
        original = discovery.local_python_import_closure([entry])
        text = {path: path.read_text() for path in original}
        with patch.object(Path, "read_text", side_effect=AssertionError("second source-text open")):
            supplied = discovery.local_python_import_closure([entry], lambda path: text[path])
        self.assertEqual(supplied, original)

    def test_read_addition_is_captured_before_its_first_raw_ast_read(self) -> None:
        """The original callback fixes file identity before authenticated parsing, not after."""
        actual = pipeline.read_bytes

        def read(path: Path, maximum: int) -> bytes:
            """Inspect actual capture ordering while preserving the bounded byte reader."""
            if path.name != "shared.py":
                self.assertTrue(any(row.path == path for row in self.f.held))
            return actual(path, maximum)

        with patch.object(pipeline, "read_bytes", side_effect=read):
            pipeline.read_closure_refs(self.f.lock, self.f.executed, self.f.capture_one)

    def test_missing_original_read_only_pin_refuses_without_a_rebaseline(self) -> None:
        """An old lock cannot borrow an existing current read-only source file."""
        self.f.lock["files"] = [row for row in self.f.lock["files"] if not row["path"].endswith("read_leaf.py")]
        with self.assertRaisesRegex(RuntimeError, "absent or changed.*read_leaf"):
            pipeline.read_closure_refs(self.f.lock, self.f.executed, self.f.capture_one)

    def test_shared_media_mismatch_is_not_silently_skipped(self) -> None:
        """Skipping a shared byte pass still requires the original media/hash join."""
        self.f.executed["executionClosure"][1]["sha256"] = "9" * 64
        with self.assertRaisesRegex(RuntimeError, "absent or changed"):
            pipeline.read_closure_refs(self.f.lock, self.f.executed, self.f.capture_one)

    def test_changed_read_only_bytes_fail_the_actual_hash_pass(self) -> None:
        """Changed current code cannot be blessed by stat capture after the change."""
        self.f.change("read_leaf.py", b"VALUE = 9\n")
        with self.assertRaisesRegex(RuntimeError, "bytes changed.*read_leaf"):
            pipeline.read_closure_refs(self.f.lock, self.f.executed, self.f.capture_one)

    def test_late_same_byte_rewrite_is_seen_without_another_hash(self) -> None:
        """Original metadata remains held after the one successful read-code byte pass."""
        refs = pipeline.read_closure_refs(self.f.lock, self.f.executed, self.f.capture_one)
        self.f.capture(refs)
        pipeline.verify_read_closure(refs, self.f.guard)
        self.f.change("read_leaf.py")
        with patch.object(pipeline, "file_hash", side_effect=AssertionError("new hash")):
            with self.assertRaisesRegex(RuntimeError, "captured read closure"):
                self.f.guard()

    def test_callback_mutation_of_future_code_is_caught_before_its_hash(self) -> None:
        """Every future addition is already held before the first arbitrary callback."""
        refs = pipeline.read_closure_refs(self.f.lock, self.f.executed, self.f.capture_one)
        self.f.capture(refs)
        self.f.calls = 0

        def changed() -> None:
            """Rewrite only the last exact TEST code file after the original guard."""
            self.f.guard()
            if self.f.calls == 1:
                self.f.change("read_leaf.py")

        with patch.object(pipeline, "file_hash", wraps=pipeline.file_hash) as hashed:
            with self.assertRaisesRegex(RuntimeError, "captured read closure"):
                pipeline.verify_read_closure(refs, changed)
        hashed.assert_not_called()

    def test_actual_hash_tail_expiry_refuses_without_new_clock(self) -> None:
        """The original post-hash guard charges late byte work to the same deadline."""
        refs = pipeline.read_closure_refs(self.f.lock, self.f.executed, self.f.capture_one)
        self.f.capture(refs)
        actual = pipeline.file_hash

        def expired(path: Path, maximum: int) -> str:
            """Complete one actual TEST hash, then expire the original virtual clock."""
            value = actual(path, maximum)
            self.now[0] = 1300.0
            return value

        with patch.object(pipeline, "file_hash", side_effect=expired):
            with self.assertRaisesRegex(RuntimeError, "deadline"):
                pipeline.verify_read_closure(refs, self.f.guard)

    def test_shortened_ast_then_restored_bytes_cannot_omit_changed_read_dependency(self) -> None:
        """Permanent RED: post-discovery capture blessed an incompletely observed closure."""
        original = self.f.paths["guided_opening_read.py"].read_bytes()
        self.f.change("read_leaf.py", b"VALUE = 9\n")
        self.f.change("guided_opening_read.py", b"import shared\n")
        parse = discovery._imports

        def restored(path: Path, modules: dict, source: str | None = None) -> list:
            """Parse real shortened TEST imports, then restore the separately pinned bytes."""
            imports = parse(path, modules) if source is None else parse(path, modules, source)
            if path == self.f.paths["guided_opening_read.py"]:
                self.f.change("guided_opening_read.py", original)
            return imports

        with patch.object(discovery, "_imports", side_effect=restored):
            with self.assertRaises(RuntimeError):
                refs = pipeline.read_closure_refs(self.f.lock, self.f.executed, self.f.capture_one)
                self.f.capture(refs)
                pipeline.verify_read_closure(refs, self.f.guard)

    def test_original_local_module_cannot_vanish_during_current_enumeration(self) -> None:
        """Permanent RED: a restored changed import was misclassified as nonlocal code."""
        enumerate_modules = discovery._python_files

        def restored() -> dict:
            """Actually hide one TEST source during rglob, then restore changed owned bytes."""
            with self.f.temporarily_absent("read_leaf.py"):
                modules = enumerate_modules()
            self.f.change("read_leaf.py", b"VALUE = 9\n")
            return modules

        with patch.object(discovery, "_python_files", side_effect=restored):
            with self.assertRaises(RuntimeError):
                refs = pipeline.read_closure_refs(self.f.lock, self.f.executed, self.f.capture_one)
                pipeline.verify_read_closure(refs, self.f.guard)


if __name__ == "__main__":
    unittest.main()

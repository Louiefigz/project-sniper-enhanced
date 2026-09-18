"""Actual outer capture/hash lifetime around a tiny actual AST discovery.

Original lock/media provenance is explicitly substituted with a second tiny
TEST repository; those facts are not production-authenticated media evidence.
The scope, stat holds, AST parser and code byte verifier are actual. Every
fault targets an exact allowlisted inert file owned by that TEST repository.
"""
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
import unittest
from unittest.mock import patch

from _source_color_read_closure_fixture import ReadClosureFixture
from _source_color_read_scope_fixture import ColdReadScopeFixture
import guided_opening_pipeline as pipeline
import guided_source_color_read_scope as module


class SourceColorReadClosureScopeTests(unittest.TestCase):
    """Current read-only file holds survive original pipeline and later metadata phases."""

    def setUp(self) -> None:
        """Use only actual TEST controls, keeping source/claim/native qualification explicit."""
        self.now = [1000.0]
        timer = patch("time.monotonic", side_effect=lambda: self.now[0])
        timer.start()
        self.addCleanup(timer.stop)
        self.f, self.r = ColdReadScopeFixture(), ReadClosureFixture()
        self.addCleanup(self.f.cleanup)
        self.addCleanup(self.r.cleanup)
        scope_leaves, read_leaves = self.f.leaves(), self.r.leaves()
        self.addCleanup(scope_leaves.close)
        self.addCleanup(read_leaves.close)
        leaf = patch.object(module, "read_closure_refs", side_effect=self._read_refs)
        leaf.start()
        self.addCleanup(leaf.stop)

    def _read_refs(self, lock: dict, executed: dict, capture: Callable) -> tuple:
        """Only the pin provenance is a fixture seam; actual AST and capture stay unchanged."""
        self.assertEqual(lock, self.f.lock)
        self.assertEqual(executed, self.f.executed)
        return pipeline.read_closure_refs(self.r.lock, self.r.executed, capture)

    def test_current_read_additions_are_held_before_original_pipeline_callback(self) -> None:
        """The callback cannot rewrite a discovered read-only file before its first hold."""
        def changed(_inputs: object) -> dict:
            """Same bytes, changed original metadata; no real code is targeted."""
            self.r.change("read_leaf.py")
            return deepcopy(self.f.executed)

        with patch.object(module, "observe_pipeline", side_effect=changed):
            with self.assertRaisesRegex(RuntimeError, "file|ancestry"):
                self.f.scope()

    def test_later_read_addition_rewrite_cannot_hide_behind_unchanged_media_history(self) -> None:
        """Actual extra files remain held after the original one-time byte verification."""
        scope = self.f.scope()
        self.assertIn(str(self.r.paths["read_leaf.py"]), scope.files)
        self.assertEqual(scope.pipeline, self.f.executed)
        self.r.change("read_leaf.py")
        with patch.object(pipeline, "file_hash", side_effect=AssertionError("repeat hash")):
            with self.assertRaisesRegex(RuntimeError, "file|ancestry"):
                module.SourceColorReadScope.assert_metadata(scope)

    def test_additional_hash_tail_uses_original_scope_deadline(self) -> None:
        """Expire only original read time after an actual additional-file hash returns."""
        actual = pipeline.file_hash

        def expired(path: object, maximum: int) -> str:
            """No new scope or reset can hide the byte pass's final elapsed work."""
            value = actual(path, maximum)
            self.now[0] = 1300.0
            return value

        with patch.object(pipeline, "file_hash", side_effect=expired):
            with self.assertRaisesRegex(RuntimeError, "deadline"):
                self.f.scope()


if __name__ == "__main__":
    unittest.main()

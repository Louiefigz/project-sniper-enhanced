"""Capability freshness covers local CSS/JS closure, not only template HTML."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from graphics import comp_capability_artifact as artifact
from headless.source_closure import discover_source_set, discover_sources


class CapabilitySourceDependenciesTests(unittest.TestCase):
    """Tiny local TEST dependencies do not render or re-bless measured rows."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="sniper-catalog-css-", dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "compositions").mkdir()
        files = {"hyperframes.json": "{}", "package.json": "{}", "index.html": "<div></div>",
                 "compositions/TEST.html": '<link href="/layout.css"><script src="/local.js"></script>',
                 "layout.css": '@import "/nested.css"; .TEST { color: red; }',
                 "nested.css": ".TEST { width: 100px; }", "local.js": "const testValue = 1;"}
        for relative, content in files.items():
            (self.root / relative).write_text(content)
        self.addCleanup(patch.stopall)
        patch.object(artifact, "MOTION_DIR", str(self.root)).start()
        patch.object(artifact, "COMPOSITIONS_DIR", str(self.root / "compositions")).start()

    def test_declared_css_nested_css_and_js_changes_invalidate_digest(self) -> None:
        for relative in ("layout.css", "nested.css", "local.js"):
            before = artifact.current_source_digest()
            target = self.root / relative
            original = target.read_text()
            target.write_text(original + "\n/* TEST change */\n")
            self.assertNotEqual(artifact.current_source_digest(), before, relative)
            target.write_text(original)
            self.assertEqual(artifact.current_source_digest(), before)

    def test_undeclared_unregistered_css_is_not_a_hidden_dependency(self) -> None:
        before = artifact.current_source_digest()
        (self.root / "unread.css").write_text(".unused { color: blue; }")
        self.assertEqual(artifact.current_source_digest(), before)

    def test_missing_or_symlinked_declared_dependency_rejects(self) -> None:
        nested = self.root / "nested.css"
        nested.rename(self.root / "held-nested.css")
        with self.assertRaisesRegex(RuntimeError, "invalid motion source dependency"):
            artifact.current_source_digest()
        nested.symlink_to(self.root / "held-nested.css")
        with self.assertRaisesRegex(RuntimeError, "invalid motion source dependency"):
            artifact.current_source_digest()

    def test_remote_dependency_cannot_be_relabelled_as_current_local_catalog(self) -> None:
        (self.root / "layout.css").write_text('@import "https://example.invalid/style.css";')
        with self.assertRaisesRegex(RuntimeError, "remote render dependency"):
            artifact.current_source_digest()

    def test_many_roots_match_single_closures_and_read_shared_bytes_once(self) -> None:
        inputs = ['<link href="/layout.css">', '<script src="/local.js"></script><link href="/layout.css">']
        reads: list[str] = []

        def reader(relative: str) -> bytes:
            reads.append(relative)
            return (self.root / relative).read_bytes()

        expected = {}
        for source in inputs:
            expected.update(discover_sources(source, reader))
        reads.clear()
        self.assertEqual(discover_source_set(inputs, reader), expected)
        self.assertEqual(len(reads), len(set(reads)))
        self.assertEqual(set(reads), set(expected))
        reads.clear()
        (self.root / "nested.css").write_text(".TEST { width: 101px; }")
        self.assertNotEqual(discover_source_set(inputs, reader), expected)
        self.assertEqual(len(reads), len(expected))


if __name__ == "__main__":
    unittest.main()

"""Pure identity/TEST-harness integration; no tool or media process is started."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import captions.caption_pages as pages
import guided_caption_identity as identities
from caption_page_ab import _equivalent, _expected_rejection
from _caption_page_ab_support import TestPageDeadline, expected_json, file_observation


class PageIdentityTests(unittest.TestCase):
    """New page decode/proof/ownership logic must affect the compositor identity."""

    def test_compositor_pins_all_added_direct_proof_dependencies(self) -> None:
        """Changing each added helper invalidates reuse without resealing old receipts."""
        changed = {"path": ""}
        observed = []

        def fake_hash(path: str) -> str:
            """Return explicit TEST identity, not observed implementation bytes."""
            observed.append(Path(path).name)
            return "b" * 64 if Path(path).name == changed["path"] else "a" * 64

        with patch.object(pages, "_tools", return_value={"TEST": "no-tools"}), \
                patch.object(pages, "file_sha256", side_effect=fake_hash):
            initial = pages.caption_page_compositor_identity()[1]
            for name in ("caption_page_decode.py", "caption_page_proof.py", "audit_glitch_scan.py",
                         "process_runner.py"):
                changed["path"] = name
                self.assertNotEqual(initial, pages.caption_page_compositor_identity()[1])
                self.assertIn(name, observed)
        paths = pages.caption_page_implementation_paths()
        self.assertEqual(paths["processDeadline"], paths["ownedRunner"])
        self.assertTrue(paths["processDeadline"].endswith("headless/process_runner.py"))


    def test_held_projection_identity_matches_ordinary_compositor_and_closure(self) -> None:
        """The same explicit implementation map drives both production read paths."""
        tools = {name: {"path": "/TEST/" + name, "sha256": "a" * 64}
                 for name in ("ffmpeg", "ffprobe")}
        with patch.object(pages, "_tools", return_value=tools), \
                patch.object(pages, "file_sha256", return_value="a" * 64), \
                patch.object(identities, "tool_paths", return_value={name: Path(row["path"]) for name, row in tools.items()}):
            paths = identities.code_paths()
            all_paths = {*map(str, paths), *[row["path"] for row in tools.values()]}
            held = tuple(SimpleNamespace(path=path, sha256="a" * 64) for path in all_paths)
            projected = identities.projection_identities(held)
            self.assertEqual(projected["compositor"], pages.caption_page_compositor_identity()[1])
            self.assertTrue(set(pages.caption_page_implementation_paths().values()).issubset(all_paths))
            missing = next(path for path in all_paths if path.endswith("caption_page_decode.py"))
            with self.assertRaises(KeyError):
                identities.projection_identities(tuple(row for row in held if row.path != missing))


class PageAbHarnessTests(unittest.TestCase):
    """Negative test accounting must not report infrastructure failure as defect recall."""

    def test_expected_defect_requires_exact_semantic_error(self) -> None:
        """Only the explicitly requested proof error is acceptable rejection evidence."""
        prefix = "caption page framemd5 is frame-incomplete"
        _expected_rejection(prefix, {"status": "failed", "error": {"type": "RuntimeError", "message": prefix}})
        for kind, message in (("ProcessDeadlineError", prefix), ("ProcessOutputLimitError", prefix),
                              ("OSError", prefix), ("RuntimeError", "TEST original deadline"),
                              ("RuntimeError", "caption page stream facts are stale")):
            with self.subTest(kind=kind, message=message), self.assertRaises(RuntimeError):
                _expected_rejection(prefix, {"status": "failed", "error": {"type": kind, "message": message}})
        with self.assertRaises(RuntimeError):
            _expected_rejection(prefix, {"status": "complete"})

    def test_equality_requires_exact_raw_hash_channel_and_float_type(self) -> None:
        """A matching-looking dictionary never hides raw-byte or float transport drift."""
        with tempfile.TemporaryDirectory(prefix="caption-page-ab-test-") as directory:
            root = Path(directory)
            (root / "old-01.stdout").write_bytes(b"TEST raw bytes\n")
            (root / "new-01.stdout").write_bytes(b"TEST raw bytes\n")
            results = {key: {"status": "complete", "proof": {"alphaMax": 255.0}} for key in ("old", "new")}
            _equivalent(root, results)
            (root / "new-01.stdout").write_bytes(b"TEST raw bytes")
            with self.assertRaisesRegex(RuntimeError, "raw bytes"):
                _equivalent(root, results)
            results["new"]["proof"]["alphaMax"] = 255
            with self.assertRaisesRegex(RuntimeError, "float type"):
                _equivalent(root, results)

    def test_metadata_is_reread_against_held_bytes_not_a_new_hash(self) -> None:
        """Even the TEST driver rejects metadata mutation between initial hash and read."""
        with tempfile.TemporaryDirectory(prefix="caption-page-ab-test-") as directory:
            path = Path(directory, "facts.json")
            path.write_bytes(b'{"TEST": 1}')
            held = file_observation(str(path), lambda: None)
            self.assertEqual(expected_json(str(path), held, lambda: None), {"TEST": 1})
            path.write_bytes(b'{"TEST": 2}')
            with self.assertRaisesRegex(RuntimeError, "bytes changed"):
                expected_json(str(path), held, lambda: None)

    def test_expired_test_deadline_cannot_return_new_credit(self) -> None:
        """An expired test allowance is terminal, never a positive epsilon reset."""
        with self.assertRaisesRegex(RuntimeError, "expired"):
            TestPageDeadline(0).remaining()


if __name__ == "__main__":
    unittest.main()

"""Public Studio version refusals with exact TEMP records; no SDK or server."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from studio import studio_review, studio_server
from studio.view_manifest import FINGERPRINT_NAME, MANIFEST_NAME
from test_studio_review import _seal_manifest


class StudioReviewVersionTests(unittest.TestCase):
    """Bad generation metadata must not be adopted, forced, or lose a record."""

    def setUp(self) -> None:
        """Create only inert caller-owned metadata before invoking the CLI."""
        temporary = tempfile.TemporaryDirectory(prefix="sniper-review-versions-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.paths = studio_review.ProducerPaths.resolve(str(self.root))
        Path(self.paths.plan).write_text("TEST plan is never parsed", encoding="utf8")
        Path(self.paths.base).write_bytes(b"TEST base is never probed")
        self.studio = Path(self.paths.studio_dir)
        self.studio.mkdir()

    def _manifest(self, fields: dict) -> None:
        """Publish fixture metadata before the command; never alter live files."""
        value = {"files": {}, "media": {}, "entries": [], **fields}
        (self.studio / MANIFEST_NAME).write_text(json.dumps(value), encoding="utf8")

    def _refuses(self, argv: list[str], message: str) -> None:
        """Public dispatch reports an error before generation/serve and preserves bytes."""
        before = {file: file.read_bytes() for file in self.root.rglob("*") if file.is_file()}
        with mock.patch.object(studio_review, "generate_project") as generate, \
                mock.patch.object(studio_review, "_serve") as serve, \
                contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(studio_review.main(argv), 1)
        self.assertIn(message, error.getvalue())
        generate.assert_not_called()
        serve.assert_not_called()
        self.assertEqual({file: file.read_bytes() for file in self.root.rglob("*") if file.is_file()}, before)

    def test_missing_version_is_a_controlled_open_error(self) -> None:
        """An old incomplete TEST manifest is not a historical V1 manifest."""
        self._manifest({})
        self._refuses(["open", str(self.root)], "unknown Studio generation version")

    def test_force_cannot_adopt_unknown_generator_and_preserves_parked_record(self) -> None:
        """Explicit overwrite permission does not invent an unsupported generation."""
        self._manifest({"generator": "studio-project-v99"})
        record = studio_server.ServerRecord(3990, 12345, "TEST inert record", "TEST")
        studio_server.write_record(str(self.studio), record)
        self._refuses(["open", str(self.root), "--force"], "unknown Studio generation version")

    def test_status_refuses_missing_or_wrong_v2_normalizer(self) -> None:
        """Current generation requires its original explicit parser token."""
        for fields in ({"generator": "studio-project-v2"},
                       {"generator": "studio-project-v2", "compositionNormalizer": "hf-ids-0.7.33"}):
            self._manifest(fields)
            self._refuses(["status", str(self.root)], "metadata is inconsistent")

    def test_mixed_fingerprint_refuses_open(self) -> None:
        """A valid V1 manifest cannot borrow a valid V2 fingerprint."""
        self._manifest({"generator": "studio-project-v1"})
        fingerprint = {"generator": "studio-project-v2", "compositionNormalizer": "hf-ids-0.8.31"}
        (self.studio / FINGERPRINT_NAME).write_text(json.dumps(fingerprint), encoding="utf8")
        self._refuses(["open", str(self.root)], "generation versions differ")

    def test_historical_fixture_is_explicit_v1_not_relabelled_current(self) -> None:
        """Retain the old view contract used by existing status/open regressions."""
        _seal_manifest(str(self.studio))
        manifest = json.loads((self.studio / MANIFEST_NAME).read_text(encoding="utf8"))
        self.assertEqual(manifest["generator"], "studio-project-v1")
        self.assertNotIn("compositionNormalizer", manifest)
        self.assertEqual(studio_review._unsynced(str(self.studio)), [])


if __name__ == "__main__":
    unittest.main()

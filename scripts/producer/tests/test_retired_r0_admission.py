"""Real retired R0 boundaries: no source fixture or policy mocks during checks."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock
from types import SimpleNamespace

from _common import pl  # noqa: F401
from _current_build_release_fixture import current_manifest
from _retired_r0_artifact_fixture import inert_artifact_sources, store_test_artifact
from headless import render_admission_artifact as artifacts
from headless.overlay_source_seal import (
    OverlaySourceCapture, capture_overlay_source, effective_render_intent,
)
from headless.render_admission import RenderAdmissionMetadata, admit_render_artifact
from test_render_admission_artifact import _entry, _request


class RetiredR0AdmissionTests(unittest.TestCase):
    """Exercise public boundaries with genuine current source policy enabled."""

    def setUp(self) -> None:
        """Create only TEST-owned input bytes before the no-write snapshots."""
        temporary = tempfile.TemporaryDirectory(prefix="TEST-retired-r0-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.root.chmod(0o700)
        (self.root / "TEST-user-input").write_bytes(b"preserve")
        self.authority = self.root / "authority"
        self.authority.mkdir(mode=0o700)
        self.request = artifacts.RenderArtifactRequest(
            str(self.authority), "authority-mp4-v1", _request(("overlay-1", _entry())), SimpleNamespace(pipeline_root=str(self.root)))

    def _snapshot(self) -> dict:
        """Include directories so empty authority/build mutations also fail."""
        return {str(path.relative_to(self.root)): path.read_bytes() if path.is_file() else None
                for path in self.root.rglob("*")}

    def test_public_store_refuses_before_build_lock_or_authority_writes(self) -> None:
        before = self._snapshot()
        with mock.patch.object(artifacts, "current_render_build_manifest") as build, \
                mock.patch("subprocess.Popen", side_effect=AssertionError("no process")) as spawn:
            with self.assertRaisesRegex(ValueError, "section-marker.*retired"):
                artifacts.store_render_admission_artifact(self.request)
        build.assert_not_called()
        spawn.assert_not_called()
        self.assertEqual(self._snapshot(), before)

    def test_capture_refuses_before_live_source_read_or_snapshot(self) -> None:
        before = self._snapshot()
        request = OverlaySourceCapture(str(self.root), effective_render_intent(_entry()),
                                       "a" * 64, "overlay-1")
        with mock.patch("headless.overlay_source_seal._read_composition") as read, \
                mock.patch("headless.overlay_source_seal.create_snapshot") as archive:
            with self.assertRaisesRegex(ValueError, "section-marker.*retired"):
                capture_overlay_source(request, str(self.root))
        read.assert_not_called()
        archive.assert_not_called()
        self.assertEqual(self._snapshot(), before)

    def test_retained_metadata_does_not_grant_new_admission(self) -> None:
        """A synthetically stored old capsule stays rejected by the real reader."""
        with inert_artifact_sources(), mock.patch.object(
                artifacts, "current_render_build_manifest", return_value=current_manifest("TEST-history")):
            locator = store_test_artifact(self.request)
        metadata = RenderAdmissionMetadata(
            str(self.authority), "authority-mp4-v1", "11111111-1111-4111-8111-111111111111",
            "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333",
            "2026-07-19T12:00:00+00:00", "TEST-release", "TEST-policy", None)
        before = self._snapshot()
        with mock.patch("subprocess.Popen", side_effect=AssertionError("no process")) as spawn:
            with self.assertRaisesRegex(ValueError, "section-marker.*retired"):
                artifacts.load_render_admission_artifact(str(self.authority), locator)
            with self.assertRaisesRegex(ValueError, "section-marker.*retired"):
                admit_render_artifact(metadata, locator, "TEST-boot")
        spawn.assert_not_called()
        self.assertEqual(self._snapshot(), before)
        self.assertFalse((self.authority / "admissions").exists())
        self.assertFalse((self.authority / "attempts").exists())

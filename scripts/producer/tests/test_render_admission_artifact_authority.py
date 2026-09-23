"""Authority identity attacks against render-artifact capture."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _common import pl  # noqa: F401
from _retired_r0_artifact_fixture import inert_artifact_sources, store_test_artifact
from test_render_admission_artifact import BUILD_A, REPO_ROOT, _entry, _request
from headless import render_admission_artifact as artifact_module
from headless.render_admission_artifact import (
    RenderArtifactRequest,
    store_render_admission_artifact,
)
from headless.render_runtime import RendererRuntime


class _RequestSubclass(RenderArtifactRequest):
    pass


class RenderAdmissionArtifactAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.authority = Path(self.temporary.name).resolve()
        os.chmod(self.authority, 0o700)
        self.runtime = RendererRuntime(
            str(REPO_ROOT),
            str(REPO_ROOT),
            "/test/python",
            "/test/docker",
            "/test/docker.sock",
            "sha256:" + "1" * 64,
            "501:20",
            "/test/ffmpeg",
            "/test/ffprobe",
            30,
        )

    def _capture(self, authority_id: str):
        request = RenderArtifactRequest(
            str(self.authority),
            authority_id,
            _request(("overlay-1", _entry())),
            self.runtime,
        )
        with mock.patch.object(
            artifact_module,
            "current_render_build_manifest",
            return_value=BUILD_A,
        ), inert_artifact_sources():
            return store_test_artifact(request)

    def test_inert_storage_binds_authority_before_artifact_publication(
        self,
    ) -> None:
        first = self._capture("authority-mp4-v1")
        artifacts = self.authority / "render-admission-artifacts"
        before = frozenset(path.name for path in artifacts.iterdir())
        with self.assertRaisesRegex(RuntimeError, "authority root is bound to another ID"):
            self._capture("authority-other")
        after = frozenset(path.name for path in artifacts.iterdir())
        self.assertEqual(after, before)
        self.assertIn(first.artifact_digest, after)
        self.assertFalse(any(name.startswith(".pending-") for name in after))

    def test_current_admission_refuses_retired_source_without_writes(self) -> None:
        request = RenderArtifactRequest(str(self.authority), "authority-mp4-v1",
            _request(("overlay-1", _entry())), self.runtime)
        with mock.patch('subprocess.Popen') as spawn, self.assertRaisesRegex(
                ValueError, 'section-marker.*retired'):
            store_render_admission_artifact(request)
        spawn.assert_not_called()
        self.assertEqual(tuple(self.authority.iterdir()), ())

    def test_request_subclass_cannot_override_capture_fields(self) -> None:
        request = _RequestSubclass(
            str(self.authority),
            "authority-mp4-v1",
            _request(("overlay-1", _entry())),
            self.runtime,
        )
        with self.assertRaisesRegex(RuntimeError, "request is invalid"):
            store_render_admission_artifact(request)
        self.assertEqual(tuple(self.authority.iterdir()), ())


if __name__ == "__main__":
    unittest.main(verbosity=2)

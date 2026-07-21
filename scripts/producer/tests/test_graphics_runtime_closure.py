"""Offline runtime bytes must participate in graphics cache identity."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

PRODUCER_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PRODUCER_ROOT)

from graphics import graphics_render as gr  # noqa: E402

EXPECTED_GSAP_SHA256 = (
    "c174bfce53a729418d57a8ad8625e7247c793a22fef8e2851e3cfa3de9cd8280"
)


def _sha256(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


class GraphicsRuntimeClosureTests(unittest.TestCase):
    """The offline section-marker closure is local and content-addressed."""

    def test_section_marker_uses_exact_vendored_gsap(self) -> None:
        with open(gr.comp_path("section-marker"), encoding="utf-8") as handle:
            html = handle.read()
        self.assertIn('/vendor/gsap/gsap.min.js', html)
        self.assertNotIn('cdn.jsdelivr.net/npm/gsap', html)
        self.assertRegex(html, r'tl\.to\(\s*["\']#marker-stage["\']\s*,\s*\{')
        self.assertIn('D - (1 / RENDER_FPS)', html)
        self.assertEqual(_sha256(gr.GSAP_CORE), EXPECTED_GSAP_SHA256)

    def test_hyperframes_dependency_has_exact_integrity_lock(self) -> None:
        lock_path = os.path.join(gr.MOTION_DIR, "package-lock.json")
        with open(lock_path, encoding="utf-8") as handle:
            lock = json.load(handle)
        root = lock["packages"][""]["dependencies"]
        package = lock["packages"]["node_modules/hyperframes"]
        self.assertEqual(root["hyperframes"], "0.7.33")
        self.assertEqual(package["version"], "0.7.33")
        self.assertEqual(
            package["integrity"],
            "sha512-nuv5V3dGxnq395T3QBHtjCPNRgrzitGWo0ZInfdeAU6aTvfB9sXtC0PBOE"
            "TR46hhwRCJrZ8jVUUyn/apsE0hXg==",
        )

    def test_binary_resolves_from_runtime_not_pipeline_snapshot(self) -> None:
        expected = ("/runtime/repo/templates/motion/node_modules/hyperframes/"
                    "dist/cli.js")
        self.assertEqual(gr.hyperframes_bin("/runtime/repo"), expected)

    def test_gsap_bytes_invalidate_section_marker_cache_key(self) -> None:
        html = ("<html data-composition-variables='[]'>"
                '<script src="/vendor/gsap/gsap.min.js"></script></html>')
        with tempfile.TemporaryDirectory() as tmp:
            core = os.path.join(tmp, "gsap.min.js")
            with open(core, "wb") as handle:
                handle.write(b"gsap-a")
            with mock.patch.object(gr, "GSAP_CORE", core):
                before = gr.content_hash("section-marker", {}, 2.5, html)
                with open(core, "wb") as handle:
                    handle.write(b"gsap-b")
                after = gr.content_hash("section-marker", {}, 2.5, html)
        self.assertNotEqual(before, after)

    def test_container_image_identity_invalidates_render_cache_key(self) -> None:
        snapshot = gr.SealedInput("/sealed.tar", "a" * 64, ())
        with mock.patch.object(gr, "container_cache_identity",
                               side_effect=[b"image-a", b"image-b"]):
            before = gr._sealed_hash("section-marker", snapshot)
            after = gr._sealed_hash("section-marker", snapshot)
        self.assertNotEqual(before, after)

    def test_render_subprocess_has_pinned_tools_and_private_ambient_state(self) -> None:
        env_keys = gr._PINNED_TOOL_ENV.values()
        with tempfile.TemporaryDirectory() as tmp:
            runtime = os.path.join(tmp, "repo")
            os.mkdir(runtime)
            with open(os.path.join(runtime, ".env"), "w", encoding="utf-8") as handle:
                handle.write("OPENAI_API_KEY=sentinel-from-repo\n")
            paths = {}
            for index, key in enumerate(env_keys):
                path = os.path.join(tmp, f"tool-{index}")
                with open(path, "wb") as handle:
                    handle.write(b"executable")
                os.chmod(path, 0o700)
                paths[key] = path
            cli = os.path.join(tmp, "hyperframes.js")
            with open(cli, "wb") as handle:
                handle.write(b"cli")
            output = os.path.join(tmp, "card.mp4")
            with open(output, "wb") as handle:
                handle.write(b"output")
            with mock.patch.object(gr, "RUNTIME_ROOT", runtime), \
                    mock.patch.object(gr, "HYPERFRAMES_BIN", cli), \
                    mock.patch.object(gr.subprocess, "run") as run, \
                    mock.patch.dict(gr.os.environ, paths, clear=True):
                run.return_value = mock.Mock(returncode=0, stderr="", stdout="")
                gr._render_to("compositions/card.html", "mp4", {}, output)
        command = run.call_args.args[0]
        kwargs = run.call_args.kwargs
        self.assertEqual(command[:3], [os.path.realpath(paths["SNIPER_NODE_PATH"]),
                                       os.path.realpath(cli), "render"])
        self.assertNotEqual(kwargs["cwd"], runtime)
        self.assertEqual(kwargs["stdin"], gr.subprocess.DEVNULL)
        self.assertNotIn("HOME", kwargs["env"])
        self.assertTrue(kwargs["env"]["SNIPER_ISOLATED_USER_DIR"].startswith(
            kwargs["cwd"]))
        self.assertEqual(kwargs["env"]["NODE_OPTIONS"],
                         f"--require={gr.NODE_USER_PRELOAD}")
        self.assertTrue(kwargs["env"]["XDG_CACHE_HOME"].startswith(kwargs["cwd"]))
        self.assertNotIn("OPENAI_API_KEY", kwargs["env"])
        self.assertEqual(kwargs["env"]["HYPERFRAMES_BROWSER_PATH"],
                         os.path.realpath(paths["HYPERFRAMES_BROWSER_PATH"]))
        self.assertEqual(kwargs["env"]["TZ"], "UTC")
        self.assertEqual(kwargs["env"]["LC_ALL"], "C.UTF-8")
        self.assertEqual(kwargs["env"]["PRODUCER_LOW_MEMORY_MODE"], "false")
        self.assertIn("--strict-variables", command)
        self.assertNotIn("--strict-all", command)


if __name__ == "__main__":
    unittest.main(verbosity=2)

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
from graphics import hyperframes_invocation  # noqa: E402
from graphics import render_tools as rt  # noqa: E402
from graphics.comp_capability_artifact import (  # noqa: E402
    composition_paths,
    composition_source_closure,
)

EXPECTED_GSAP_SHA256 = (
    "c174bfce53a729418d57a8ad8625e7247c793a22fef8e2851e3cfa3de9cd8280"
)


def _sha256(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _fake_executable(directory: str, name: str) -> str:
    path = os.path.join(directory, name)
    with open(path, "wb") as handle:
        handle.write(b"executable")
    os.chmod(path, 0o700)
    return path


class GraphicsRuntimeClosureTests(unittest.TestCase):
    """The production comp closure is local and content-addressed."""

    def setUp(self) -> None:
        rt._memo = None

    def test_every_comp_uses_exact_vendored_gsap(self) -> None:
        for path in composition_paths():
            with self.subTest(comp=os.path.basename(path)), \
                    open(path, encoding="utf-8") as handle:
                html = handle.read()
                self.assertIn(
                    '<script src="/vendor/gsap/gsap.min.js"></script>', html)
                self.assertNotIn("cdn.jsdelivr.net/npm/gsap", html)
                closure = composition_source_closure(html)
                self.assertIn("vendor/gsap/gsap.min.js", closure)
        self.assertEqual(_sha256(gr.GSAP_CORE), EXPECTED_GSAP_SHA256)

    def test_section_marker_keeps_proved_terminal_fade(self) -> None:
        with open(gr.comp_path("section-marker"), encoding="utf-8") as handle:
            html = handle.read()
        self.assertRegex(html, r'tl\.to\(\s*["\']#marker-stage["\']\s*,\s*\{')
        self.assertIn('D - (1 / RENDER_FPS)', html)

    def test_terminal_policy_uses_measured_fade_physics(self) -> None:
        base = dict(entry={"kind": "synthetic"}, fmt="mov", dimensions=(1, 1),
                    duration=1, key="k", temp_rel="", temp_abs="", comp_html="",
                    spec={}, snapshot=None, fps=30.0)
        probe = gr._RenderWork(**base, capability_probe=True)
        normal = gr._RenderWork(**base, capability_probe=False)
        self.assertFalse(gr._terminal_clear_required(probe))
        for fade, expected in (
                ("fades-clean", True), ("hold-to-cut", False),
                ("partial-fade", False), (None, True)):
            with self.subTest(fade=fade), mock.patch.object(
                    gr, "measured_fade_class", return_value=fade):
                self.assertEqual(gr._terminal_clear_required(normal), expected)

    def test_hyperframes_dependency_has_exact_integrity_lock(self) -> None:
        lock_path = os.path.join(gr.MOTION_DIR, "package-lock.json")
        with open(lock_path, encoding="utf-8") as handle:
            lock = json.load(handle)
        root = lock["packages"][""]["dependencies"]
        package = lock["packages"]["node_modules/hyperframes"]
        self.assertEqual(root["hyperframes"], "0.8.31")
        self.assertEqual(package["version"], "0.8.31")
        self.assertEqual(
            package["integrity"],
            "sha512-DzTDG8sms/Ot5rt/ulEkhXg5MeBMEHznvT+d/lU0dK5ggJlzSonGOZTo/"
            "iRM5J4YRfd5htXSwXkFz9NFRiEVSQ==",
        )

    def test_binary_resolves_from_runtime_not_pipeline_snapshot(self) -> None:
        expected = ("/runtime/repo/templates/motion/node_modules/hyperframes/"
                    "dist/cli.js")
        self.assertEqual(gr.hyperframes_bin("/runtime/repo"), expected)

    def test_image_build_includes_all_observer_modules_without_install_scripts(self) -> None:
        with open(os.path.join(gr.MOTION_DIR, ".dockerignore"), encoding="utf-8") as handle:
            includes = set(handle.read().splitlines())
        observers = ("browser", "host", "launch", "loader", "patch")
        for role in observers:
            self.assertIn(f"!container/layout_observer_{role}.mjs", includes)
        with open(os.path.join(gr.MOTION_DIR, "Dockerfile.g2"), encoding="utf-8") as handle:
            dockerfile = handle.read()
        self.assertIn("npm ci --include=optional --ignore-scripts", dockerfile)
        self.assertIn('io.project-sniper.hyperframes-version="0.8.31"', dockerfile)

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

    def test_any_local_dependency_invalidates_cache_key(self) -> None:
        html = "<html data-composition-variables='[]'></html>"
        with mock.patch.object(
                gr, "discover_root_sources",
                side_effect=[{"vendor/plugin.js": b"a"},
                             {"vendor/plugin.js": b"b"}]), \
                mock.patch.object(gr, "live_tools_identity",
                                  return_value=b"tools"):
            before = gr.content_hash("synthetic", {}, 2.5, html)
            after = gr.content_hash("synthetic", {}, 2.5, html)
        self.assertNotEqual(before, after)

    def test_container_image_identity_invalidates_render_cache_key(self) -> None:
        snapshot = gr.SealedInput("/sealed.tar", "a" * 64, ())
        with mock.patch.object(gr, "container_cache_identity",
                               side_effect=[b"image-a", b"image-b"]):
            before = gr._sealed_hash("section-marker", snapshot, 30.0)
            after = gr._sealed_hash("section-marker", snapshot, 30.0)
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
                gr._render_to(
                    "compositions/card.html", "mp4", {}, output, 30.0)
        command = run.call_args.args[0]
        kwargs = run.call_args.kwargs
        # The render runs under the OS network boundary, then the pinned node + CLI.
        self.assertEqual(command[:3], [hyperframes_invocation.SANDBOX_EXEC, "-f",
                                       hyperframes_invocation.LOCALHOST_ONLY_PROFILE])
        self.assertEqual(command[3:6], [os.path.realpath(paths["SNIPER_NODE_PATH"]),
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

    def test_live_default_discovers_absolute_tools_without_env_pins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            node = _fake_executable(tmp, "node")
            ffmpeg = _fake_executable(tmp, "ffmpeg")
            ffprobe = _fake_executable(tmp, "ffprobe")
            cache = os.path.join(tmp, "cache", "mac_arm-152.0.7928.2",
                                 "chrome-headless-shell-mac-arm64")
            os.makedirs(cache)
            browser = _fake_executable(cache, "chrome-headless-shell")
            which = {"node": node, "ffmpeg": ffmpeg, "ffprobe": ffprobe}
            with mock.patch.dict(rt.os.environ, {}, clear=True), \
                    mock.patch.object(rt, "_BROWSER_CACHE_ROOTS",
                                      (os.path.join(tmp, "cache"),)), \
                    mock.patch.object(rt.shutil, "which", which.get):
                tools = rt.resolve_tools()
        self.assertEqual(tools, {
            "node": os.path.realpath(node),
            "ffmpeg": os.path.realpath(ffmpeg),
            "ffprobe": os.path.realpath(ffprobe),
            "browser": os.path.realpath(browser),
        })
        for path in tools.values():
            self.assertTrue(os.path.isabs(path))

    def test_browser_discovery_prefers_platform_arch_then_numeric_version(
            self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "cache")
            expected = None
            for version_dir in ("mac_arm-9.0.100.0", "mac_arm-10.0.2.0",
                                "mac_x64-999.0.0.0"):
                cache = os.path.join(root, version_dir, "shell")
                os.makedirs(cache)
                binary = _fake_executable(cache, "chrome-headless-shell")
                if version_dir == "mac_arm-10.0.2.0":
                    expected = binary
            with mock.patch.object(rt, "_BROWSER_CACHE_ROOTS", (root,)), \
                    mock.patch.object(rt, "_platform_token",
                                      return_value="mac_arm"):
                picked = rt._discover_browser()
        # Foreign-arch mac_x64 loses despite its higher version AND later
        # lexicographic sort; numeric ranking picks 10 over 9 within the arch.
        self.assertEqual(picked, os.path.realpath(expected))

    def test_live_explicit_pin_overrides_discovery_per_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            node = _fake_executable(tmp, "node")
            ffprobe = _fake_executable(tmp, "ffprobe")
            pinned_ffmpeg = _fake_executable(tmp, "pinned-ffmpeg")
            cache = os.path.join(tmp, "cache", "v1", "shell")
            os.makedirs(cache)
            _fake_executable(cache, "chrome-headless-shell")
            which = {"node": node, "ffprobe": ffprobe}
            env = {"HYPERFRAMES_FFMPEG_PATH": pinned_ffmpeg}
            with mock.patch.dict(rt.os.environ, env, clear=True), \
                    mock.patch.object(rt, "_BROWSER_CACHE_ROOTS",
                                      (os.path.join(tmp, "cache"),)), \
                    mock.patch.object(rt.shutil, "which", which.get):
                tools = rt.resolve_tools()
            self.assertEqual(tools["ffmpeg"], os.path.realpath(pinned_ffmpeg))
            self.assertEqual(tools["node"], os.path.realpath(node))

    def test_live_default_fails_loudly_when_a_tool_is_unfindable(self) -> None:
        with mock.patch.dict(rt.os.environ, {}, clear=True), \
                mock.patch.object(rt.shutil, "which", lambda name: None):
            with self.assertRaises(RuntimeError) as ctx:
                rt.resolve_tools()
        self.assertIn("node", str(ctx.exception))

    def test_sealed_mode_keeps_hard_fail_without_env_pins(self) -> None:
        env = {"SNIPER_RENDER_IMAGE_ID": "sha256:image"}
        with mock.patch.dict(rt.os.environ, env, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                rt.resolve_tools()
        self.assertIn("SNIPER_NODE_PATH", str(ctx.exception))
        self.assertIn("absolute executable path", str(ctx.exception))

    def test_sealed_mode_never_uses_discovery(self) -> None:
        env = {"SNIPER_RENDER_IMAGE_ID": "sha256:image"}
        with mock.patch.dict(rt.os.environ, env, clear=True), \
                mock.patch.object(rt, "_discovered_tool") as discovered:
            with self.assertRaises(RuntimeError):
                rt.resolve_tools()
        discovered.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)

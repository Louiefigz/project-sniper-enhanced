"""R0 retirement rejection and independent build/cache/environment contracts."""
from __future__ import annotations

import ast
import dataclasses
import os
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path
from unittest import mock

PRODUCER_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PRODUCER_DIR.parents[1]
TEST_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TEST_DIR))
sys.path.insert(0, str(PRODUCER_DIR))

from _render_lane_fixture import (  # noqa: E402
    CONTAINER_NAME,
    IMAGE_ID,
    RenderLaneFixture,
)

from headless.render_lane import (  # noqa: E402
    OverlayPreparationRequest,
    RenderExecutionPolicy,
    current_render_build_digest,
    launch_overlay,
)
from headless.render_lane import _child_environment, _validated_build
from headless.render_build_receipt import store_render_build
from headless.render_runtime import current_render_build_manifest, validate_renderer_runtime
from graphics.graphics_render import render_entry
from headless import render_build  # noqa: E402
from headless.render_lane_cache import (  # noqa: E402
    CacheOwnershipError,
    prepare_attempt_cache,
)


class RenderLaneTests(RenderLaneFixture):
    def _cache_identity(self) -> tuple[str, str, str, str]:
        """Synthetic cache ownership facts, never an admitted render request."""
        return ("attempt-a", self.artifact.request_digest, "a" * 64, IMAGE_ID)

    def test_child_environment_is_closed_and_parent_is_unchanged(self) -> None:
        """Exercise the pure environment builder without admitting retired work."""
        binding = prepare_attempt_cache(str(self.attempt), self._cache_identity())
        poison = {"ANTHROPIC_API_KEY": "secret", "SNIPER_RENDER_IMAGE_ID": "poison"}
        with mock.patch.dict(os.environ, poison, clear=False):
            before = dict(os.environ)
            child_env = _child_environment(self._runtime(), binding, CONTAINER_NAME)
            self.assertEqual(dict(os.environ), before)
        for key in ("ANTHROPIC_API_KEY", "HOME", "PYTHONPATH"):
            self.assertNotIn(key, child_env)
        self.assertEqual(child_env["SNIPER_RENDER_IMAGE_ID"], IMAGE_ID)
        self.assertEqual(child_env["SNIPER_RENDER_CONTAINER_NAME"], CONTAINER_NAME)
        self.assertEqual(child_env["TMPDIR"], binding.temp_dir)

    def test_invalid_mode_and_image_fail_before_spawn(self) -> None:
        """Mode rejects before touching a request; runtime approval is independent."""
        before = tuple(self.attempt.iterdir())
        with mock.patch("headless.render_lane.run_text") as run:
            with self.assertRaisesRegex(RuntimeError, "rendererMode"):
                launch_overlay(RenderExecutionPolicy("auto"), None, self._runtime())
            with self.assertRaisesRegex(RuntimeError, "approval"):
                validate_renderer_runtime(self._runtime("sha256:" + "0" * 64))
        run.assert_not_called()
        self.assertEqual(tuple(self.attempt.iterdir()), before)

    def test_build_drift_is_rejected_without_launching_retired_work(self) -> None:
        """A retained real build identity must still match the running tools."""
        runtime = self._runtime()
        build = store_render_build(str(self.attempt), current_render_build_manifest(runtime))
        request = SimpleNamespace(attempt_root=str(self.attempt), build=build,
                                  build_digest=build.build_digest)
        self.assertEqual(_validated_build(request, runtime), build.build_digest)
        Path(runtime.python).write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        with mock.patch("headless.render_lane.run_text") as run:
            with self.assertRaisesRegex(RuntimeError, "build drifted"):
                _validated_build(request, runtime)
        run.assert_not_called()

    def test_retired_render_entry_rejects_before_subprocess_or_cache_write(self) -> None:
        """The actual compatibility entry point enforces current source policy."""
        before = tuple(self.attempt.iterdir())
        with mock.patch("subprocess.run") as run:
            with self.assertRaisesRegex(ValueError, "retired"):
                render_entry(self._entry(), str(self.attempt / "cache"))
        run.assert_not_called()
        self.assertEqual(tuple(self.attempt.iterdir()), before)

    def test_tool_byte_change_changes_build_digest(self) -> None:
        runtime = self._runtime()
        before = current_render_build_digest(runtime)
        Path(runtime.python).write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        after = current_render_build_digest(runtime)
        self.assertNotEqual(before, after)

    def test_tool_path_and_loaded_release_are_part_of_build_identity(self) -> None:
        runtime = self._runtime()
        before = current_render_build_digest(runtime)
        alternate = self.root / "python-alternate"
        alternate.write_bytes(Path(runtime.python).read_bytes())
        alternate.chmod(0o700)
        moved = dataclasses.replace(runtime, python=str(alternate))
        self.assertNotEqual(before, current_render_build_digest(moved))
        changed = [dict(row) for row in render_build._LOADED_IMPLEMENTATION]
        changed[0] = {**changed[0], "sha256": "0" * 64}
        with mock.patch(
            "headless.render_build._implementation_rows", return_value=changed
        ), self.assertRaisesRegex(RuntimeError, "changed while hashing"):
            current_render_build_digest(runtime)

    def test_declared_build_contains_transitive_local_import_closure(self) -> None:
        declared = set(render_build._IMPLEMENTATION_FILES)

        def module_path(name: str) -> str | None:
            base = name.replace(".", "/")
            candidates = (
                f"scripts/producer/{base}.py",
                f"scripts/producer/{base}/__init__.py",
            )
            return next(
                (path for path in candidates if (REPO_ROOT / path).is_file()), None
            )

        missing = set()
        for relative in declared:
            if not relative.endswith(".py"):
                continue
            module = relative.removeprefix("scripts/producer/").removesuffix(".py")
            parts = module.split("/")
            package = parts[:-1] if parts[-1] != "__init__" else parts[:-1]
            tree = ast.parse((REPO_ROOT / relative).read_text())
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    prefix = (
                        package[: len(package) - node.level + 1] if node.level else []
                    )
                    base = ".".join([*prefix, *(node.module or "").split(".")])
                    names = [base]
                for name in names:
                    target = module_path(name)
                    if target and target not in declared:
                        missing.add(target)
        self.assertEqual(missing, set())

    def test_worker_bootstrap_ignores_pythonpath_startup_customization(self) -> None:
        poison = self.root / "poison"
        poison.mkdir()
        marker = self.root / "sitecustomize-ran"
        (poison / "sitecustomize.py").write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n"
        )
        bootstrap = REPO_ROOT / "scripts/producer/headless/render_worker_bootstrap.py"
        environment = {
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(poison),
        }
        proc = subprocess.run(
            [sys.executable, "-I", "-S", "-B", str(bootstrap)],
            input="{}",
            capture_output=True,
            text=True,
            env=environment,
            cwd=self.attempt,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("request schema is invalid", proc.stderr)
        self.assertFalse(marker.exists())

    def test_preparation_has_no_caller_entry_or_build_digest(self) -> None:
        fields = {field.name for field in dataclasses.fields(OverlayPreparationRequest)}
        self.assertNotIn("entry", fields)
        self.assertNotIn("request_digest", fields)
        self.assertNotIn("build_digest", fields)

    def test_r0_preparation_rejects_before_any_write_or_worker(self) -> None:
        """Retired input cannot persist a build, source capsule or cache artifact."""
        before = {str(path.relative_to(self.root)): path.read_bytes()
                  for path in self.root.rglob("*") if path.is_file()}
        directories = {str(path.relative_to(self.root))
                       for path in self.root.rglob("*") if path.is_dir()}
        with mock.patch("headless.render_lane.run_text") as run, mock.patch(
                "headless.render_lane.store_render_build") as store:
            with self.assertRaisesRegex(ValueError, "section-marker.*retired"):
                self._request()
        run.assert_not_called()
        store.assert_not_called()
        self.assertEqual({str(path.relative_to(self.root)): path.read_bytes()
                          for path in self.root.rglob("*") if path.is_file()}, before)
        self.assertEqual({str(path.relative_to(self.root))
                          for path in self.root.rglob("*") if path.is_dir()}, directories)

    def test_cache_is_bound_to_attempt_and_revalidates_warm(self) -> None:
        """Cache ownership remains testable independently of retired execution."""
        identity = self._cache_identity()
        first = prepare_attempt_cache(str(self.attempt), identity)
        self.assertEqual(first, prepare_attempt_cache(str(self.attempt), identity))
        wrong = ("attempt-b", *identity[1:])
        with self.assertRaisesRegex(CacheOwnershipError, "does not match"):
            prepare_attempt_cache(str(self.attempt), wrong)

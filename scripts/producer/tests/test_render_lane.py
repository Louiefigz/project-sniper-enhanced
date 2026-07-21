from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import os
import subprocess
import sys
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
    RENDERER_MODE,
    OverlayPreparationRequest,
    RenderExecutionPolicy,
    current_render_build_digest,
    launch_overlay,
)
from headless.overlay_seal import OverlayPrepareRequest, prepare_overlay  # noqa: E402
from headless import render_build  # noqa: E402
from headless.render_lane_cache import (  # noqa: E402
    CacheOwnershipError,
    prepare_attempt_cache,
)


class RenderLaneTests(RenderLaneFixture):
    def test_child_environment_is_closed_and_parent_is_unchanged(self) -> None:
        poison = {"ANTHROPIC_API_KEY": "secret", "SNIPER_RENDER_IMAGE_ID": "poison"}
        with mock.patch.dict(os.environ, poison, clear=False):
            before = dict(os.environ)
            with mock.patch(
                "headless.render_lane.run_text", side_effect=self._fake_success
            ) as run:
                result = launch_overlay(
                    RenderExecutionPolicy(RENDERER_MODE),
                    self._request(),
                    self._runtime(),
                )
            self.assertEqual(dict(os.environ), before)
        child = run.call_args.args[0]
        child_env = child.environment
        self.assertNotIn("ANTHROPIC_API_KEY", child_env)
        self.assertNotIn("HOME", child_env)
        self.assertNotIn("PYTHONPATH", child_env)
        self.assertEqual(child_env["SNIPER_RENDER_IMAGE_ID"], IMAGE_ID)
        self.assertEqual(child_env["SNIPER_RENDER_CONTAINER_NAME"], CONTAINER_NAME)
        self.assertEqual(result["rendererMode"], RENDERER_MODE)
        self.assertEqual(
            result["outputBinding"]["sha256"], hashlib.sha256(b"rendered").hexdigest()
        )
        self.assertEqual(child.cwd, str(self.attempt))
        self.assertEqual(
            child.command[1:6],
            ("-I", "-S", "-B", "-X", f"pycache_prefix={child_env['TMPDIR']}/pycache"),
        )
        payload = json.loads(child.stdin_text)
        self.assertNotIn("entry", payload)
        self.assertFalse(any(key.startswith("expected") for key in payload))
        self.assertEqual(
            set(payload),
            {
                "attemptId",
                "attemptRoot",
                "buildDigest",
                "cacheDir",
                "requestDigest",
                "sealPath",
                "sealSha256",
                "selectionId",
            },
        )

    def test_invalid_mode_and_image_fail_before_spawn(self) -> None:
        with mock.patch("headless.render_lane.run_text") as run:
            with self.assertRaisesRegex(RuntimeError, "rendererMode"):
                launch_overlay(
                    RenderExecutionPolicy("auto"), self._request(), self._runtime()
                )
            with self.assertRaisesRegex(RuntimeError, "approval"):
                launch_overlay(
                    RenderExecutionPolicy(RENDERER_MODE),
                    self._request(),
                    self._runtime("sha256:" + "0" * 64),
                )
        run.assert_not_called()

    def test_build_drift_before_or_during_worker_blocks_success(self) -> None:
        request = self._request()
        with mock.patch(
            "headless.render_lane._validated_build",
            side_effect=RuntimeError("admitted render build drifted"),
        ), mock.patch("headless.render_lane.run_text") as run, self.assertRaisesRegex(
            RuntimeError, "build drifted"
        ):
            launch_overlay(
                RenderExecutionPolicy(RENDERER_MODE), request, self._runtime()
            )
        run.assert_not_called()
        with mock.patch(
            "headless.render_lane._validated_build",
            side_effect=[request.build_digest, RuntimeError("render build drifted")],
        ), mock.patch(
            "headless.render_lane.run_text", side_effect=self._fake_success
        ), self.assertRaisesRegex(
            RuntimeError, "build drifted"
        ):
            launch_overlay(
                RenderExecutionPolicy(RENDERER_MODE), request, self._runtime()
            )

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

    def test_artifact_a_cannot_launch_a_caller_forged_entry_b(self) -> None:
        runtime = self._runtime()
        build = current_render_build_digest(runtime)
        forged_entry = self._entry()
        forged_entry["spec"]["line1"] = "ENTRY-B"
        locator = prepare_overlay(
            OverlayPrepareRequest(
                str(self.attempt),
                "attempt-a",
                self.artifact.request_digest,
                build,
                str(REPO_ROOT),
                forged_entry,
                "overlay-1",
            )
        )
        request = self._request()
        launch_request = type(request)(
            request.authority_root,
            request.attempt_root,
            request.attempt_id,
            request.build,
            request.request,
            request.overlay_id,
            locator,
        )
        with mock.patch("headless.render_lane.run_text") as run, self.assertRaisesRegex(
            RuntimeError, "selected request entry"
        ):
            launch_overlay(
                RenderExecutionPolicy(RENDERER_MODE), launch_request, runtime
            )
        run.assert_not_called()

    def test_cache_is_bound_to_attempt_and_revalidates_warm(self) -> None:
        request = self._request()
        identity = (
            request.attempt_id,
            request.request.request_digest,
            request.build_digest,
            IMAGE_ID,
        )
        first = prepare_attempt_cache(str(self.attempt), identity)
        second = prepare_attempt_cache(str(self.attempt), identity)
        self.assertEqual(first, second)
        wrong = (
            "attempt-b",
            request.request.request_digest,
            request.build_digest,
            IMAGE_ID,
        )
        with self.assertRaisesRegex(CacheOwnershipError, "does not match"):
            prepare_attempt_cache(str(self.attempt), wrong)

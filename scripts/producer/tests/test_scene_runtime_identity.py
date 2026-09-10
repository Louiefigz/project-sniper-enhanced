"""TEMP installed-runtime metadata tests; no renderer or media is executed."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from graphics import scene_executor as executor
from graphics import scene_render as renderer
from graphics.scene_bundle import capture_bundle
from graphics.scene_contract import SceneContractError, canonical_json
from scene_fixtures import fire_sparkles_scene

_FIXTURE = Path(__file__).parent / "fixtures" / "fire-sparkles-bundle"
_ASSETS = ("cli.js", "hyperframe.runtime.iife.js", "hyperframe-runtime.js",
           "runtimeVersion.js")


class SceneRuntimeIdentityTests(unittest.TestCase):
    """Version and exact runtime bytes must precede cache and spawn boundaries."""

    def setUp(self) -> None:
        """Create an explicit inert installed-package tree and original bundle."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.motion = self.root / "motion"
        self.package = self.motion / "node_modules" / "hyperframes"
        (self.package / "dist").mkdir(parents=True)
        for name in _ASSETS:
            (self.package / "dist" / name).write_bytes(b"// TEST runtime A\n")
        self.cli = self.package / "dist" / "cli.js"
        self.install_version("0.7.33")
        self.shared = self.motion / "index.html"
        self.shared.write_bytes(b"<!-- TEST shared runtime -->")
        shutil.copytree(_FIXTURE, self.root / "bundle")
        self.bundle = capture_bundle(str(self.root / "bundle"))
        self.scene = fire_sparkles_scene(self.bundle.digest)
        self.enterContext(mock.patch.dict(os.environ, {}, clear=True))
        self.enterContext(mock.patch.object(executor, "HYPERFRAMES_BIN", str(self.cli)))
        self.enterContext(mock.patch.object(executor, "_shared_sources", return_value=(
            ("index.html", str(self.shared)),)))
        self.enterContext(mock.patch.object(renderer, "live_tools_identity", return_value=b"TEST-tools"))
        self.native = self.enterContext(mock.patch.object(executor, "render_composition"))

    def install_version(self, version: str) -> None:
        """Write only this test's original installed package and lock files."""
        (self.package / "package.json").write_bytes(canonical_json({
            "name": "hyperframes", "version": version}))
        lock = {"lockfileVersion": 3, "packages": {
            "node_modules/hyperframes": {"version": version}}}
        for relative in ("package-lock.json", "node_modules/.package-lock.json"):
            (self.motion / relative).write_bytes(canonical_json(lock))

    def request(self) -> renderer.SceneRenderRequest:
        """Create a metadata-only scene request against its actual bundle."""
        return renderer.SceneRenderRequest(
            self.scene, self.bundle, str(self.root / "cache"))

    def execution(self) -> executor.SceneExecution:
        """Create the direct local invocation with an explicitly stubbed child."""
        relative = self.bundle.manifest["fullEntry"]
        html = (Path(self.bundle.path) / relative).read_text()
        return executor.SceneExecution(
            self.bundle, relative, html, "mov", {},
            str(self.root / "output.mov"), "30", 6, str(self.root), ())

    def sealed(self, version: object) -> SimpleNamespace:
        """Supply only TEST approval metadata; no Docker endpoint is used."""
        runtime = SimpleNamespace(approval={"probedClosure": {"hyperframesVersion": version}})
        self.enterContext(mock.patch.dict(os.environ, {"SNIPER_RENDER_IMAGE_ID": "TEST-image"}))
        self.enterContext(mock.patch.object(executor, "required_runtime", return_value=runtime))
        return runtime

    def test_cli_only_change_invalidates_scene_cache(self) -> None:
        """Changing only the installed CLI bytes cannot reuse a scene key."""
        before = renderer._prepare(self.scene, self.bundle, None).key
        stamp = self.cli.stat()
        self.cli.write_bytes(b"// TEST runtime B\n")
        os.utime(self.cli, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        after = renderer._prepare(self.scene, self.bundle, None).key
        self.assertNotEqual(before, after)
        self.native.assert_not_called()

    def test_version_mismatch_refuses_before_cache_lookup(self) -> None:
        """Readable old manifests do not authorize a new runtime rerender."""
        self.install_version("0.8.31")
        with mock.patch.object(renderer, "materialize", return_value=(
                str(self.root / "TEST-cached.mov"), True, {})) as cache:
            with self.assertRaisesRegex(SceneContractError, "runtime.*version"):
                renderer.render_scene(self.request())
        cache.assert_not_called()
        self.native.assert_not_called()
        self.assertFalse((self.root / "cache").exists())

    def test_direct_executor_refuses_runtime_version_mismatch(self) -> None:
        """Direct execution cannot bypass the same version join."""
        self.install_version("0.8.31")
        with self.assertRaisesRegex(SceneContractError, "runtime.*version"):
            executor.execute_scene(self.execution())
        self.native.assert_not_called()

    def test_packaged_runtime_and_lock_changes_invalidate_cache(self) -> None:
        """Selected packaged runtime assets and install-lock bytes bind the key."""
        before = renderer._prepare(self.scene, self.bundle, None).key
        (self.package / "dist" / "hyperframe-runtime.js").write_bytes(b"// TEST changed")
        changed = renderer._prepare(self.scene, self.bundle, None).key
        self.assertNotEqual(before, changed)
        lock_path = self.motion / "package-lock.json"
        lock = json.loads(lock_path.read_text())
        lock["packages"]["node_modules/TEST-leaf"] = {"version": "1.0.0"}
        lock_path.write_bytes(canonical_json(lock))
        self.assertNotEqual(changed, renderer._prepare(self.scene, self.bundle, None).key)

    def test_inconsistent_install_lock_refuses_before_native(self) -> None:
        """A package declaration alone cannot excuse a disagreeing install lock."""
        lock = {"packages": {"node_modules/hyperframes": {"version": "0.8.31"}}}
        (self.motion / "node_modules" / ".package-lock.json").write_bytes(canonical_json(lock))
        with self.assertRaisesRegex(SceneContractError, "runtime lock version"):
            executor.execute_scene(self.execution())
        self.native.assert_not_called()

    def test_shared_runtime_input_invalidates_cache(self) -> None:
        """The existing staged shared sources remain exact cache dependencies."""
        before = renderer._prepare(self.scene, self.bundle, None).key
        self.shared.write_bytes(b"<!-- TEST changed shared runtime -->")
        self.assertNotEqual(before, renderer._prepare(self.scene, self.bundle, None).key)

    def test_missing_runtime_asset_cannot_be_ignored(self) -> None:
        """The fixed installed asset set is mandatory, not discovered opportunistically."""
        (self.package / "dist" / "runtimeVersion.js").unlink()
        with self.assertRaises(FileNotFoundError):
            executor.execute_scene(self.execution())
        self.native.assert_not_called()

    def test_matching_local_runtime_reaches_only_explicit_test_child(self) -> None:
        """A coherent actual TEMP install passes both pre-staging and launch joins."""
        executor.execute_scene(self.execution())
        self.native.assert_called_once()
        self.assertEqual(self.native.call_args.args[1], str(self.cli))

    def test_runtime_change_during_staging_refuses_before_native(self) -> None:
        """A post-key or staging change does not get a fresh launch identity."""
        replace_entry = executor._replace_entry

        def change(request: executor.SceneExecution, root: str) -> None:
            """Change only the original inert CLI after actual entry staging."""
            replace_entry(request, root)
            self.cli.write_bytes(b"// TEST late runtime change")

        with mock.patch.object(executor, "_replace_entry", side_effect=change):
            with self.assertRaisesRegex(SceneContractError, "runtime.*changed"):
                executor.execute_scene(self.execution())
        self.native.assert_not_called()

    def test_cached_return_keeps_original_runtime_identity(self) -> None:
        """A cache callback cannot substitute the selected live runtime."""
        def cached(*_args: object) -> tuple[str, bool, dict]:
            """Simulate only the cache hit, changing the original TEMP CLI."""
            self.cli.write_bytes(b"// TEST cache-tail runtime change")
            return str(self.root / "TEST-cached.mov"), True, {}

        with mock.patch.object(renderer, "materialize", side_effect=cached):
            with self.assertRaisesRegex(SceneContractError, "runtime.*changed"):
                renderer.render_scene(self.request())
        self.native.assert_not_called()

    def test_new_bundle_and_matching_new_runtime_have_metadata_identity(self) -> None:
        """A deliberately new generation can target the matching new runtime."""
        self.install_version("0.8.31")
        path = self.root / "bundle" / "bundle.json"
        manifest = json.loads(path.read_text())
        manifest["runtime"]["hyperframesVersion"] = "0.8.31"
        path.write_bytes(canonical_json(manifest))
        bundle = capture_bundle(str(path.parent))
        scene = fire_sparkles_scene(bundle.digest)
        self.assertNotEqual(bundle.digest, self.bundle.digest)
        self.assertEqual(len(renderer._prepare(scene, bundle, None).key), 64)
        self.native.assert_not_called()

    def test_original_key_identity_cannot_rebaseline_at_direct_execution(self) -> None:
        """The cache-selected runtime remains binding when execution begins later."""
        original = renderer._prepare(self.scene, self.bundle, None).runtime_identity
        self.cli.write_bytes(b"// TEST post-key runtime change")
        request = replace(self.execution(), expected_runtime=original)
        with self.assertRaisesRegex(SceneContractError, "runtime.*changed"):
            executor.execute_scene(request)
        self.native.assert_not_called()

    def test_sealed_path_does_not_use_the_host_install(self) -> None:
        """The original stronger OCI identity stays separate from local metadata."""
        self.sealed("0.7.33")
        with mock.patch.object(renderer, "container_cache_identity", return_value=b"TEST-OCI"), \
                mock.patch.object(renderer, "scene_runtime_identity") as local:
            prepared = renderer._prepare(self.scene, self.bundle, None)
            self.assertIsNone(prepared.runtime_identity)
            local.assert_not_called()
        self.native.assert_not_called()

    def test_sealed_version_mismatch_refuses_before_cache(self) -> None:
        """An approved new image cannot reuse an old bundle's sealed cache."""
        self.sealed("0.8.31")
        with mock.patch.object(renderer, "container_cache_identity", return_value=b"TEST-OCI") as identity, \
                mock.patch.object(renderer, "materialize", return_value=("TEST-output", True, {})) as cache:
            with self.assertRaisesRegex(SceneContractError, "runtime.*version"):
                renderer.render_scene(self.request())
        identity.assert_not_called()
        cache.assert_not_called()
        self.assertFalse((self.root / "cache").exists())

    def test_sealed_version_mismatch_refuses_before_snapshot(self) -> None:
        """The direct sealed executor checks the approved version before staging."""
        self.sealed("0.8.31")
        with mock.patch.object(executor, "create_scene_snapshot") as snapshot, \
                mock.patch.object(executor, "render_in_container") as child:
            with self.assertRaisesRegex(SceneContractError, "runtime.*version"):
                executor.execute_scene(self.execution())
        snapshot.assert_not_called()
        child.assert_not_called()

    def test_sealed_approval_requires_an_exact_version(self) -> None:
        """Missing, unknown, or non-string versions cannot authorize execution."""
        runtime = self.sealed(None)
        for version in (None, True, 0.831, "0.8.32"):
            runtime.approval["probedClosure"]["hyperframesVersion"] = version
            with self.assertRaisesRegex(SceneContractError, "runtime.*version"):
                executor.assert_scene_container_version(self.bundle)
        self.native.assert_not_called()

    def test_new_bundle_matches_the_new_approved_image(self) -> None:
        """A deliberately authored new declaration reaches only the TEST child."""
        self.sealed("0.8.31")
        path = self.root / "bundle" / "bundle.json"
        manifest = json.loads(path.read_text())
        manifest["runtime"]["hyperframesVersion"] = "0.8.31"
        path.write_bytes(canonical_json(manifest))
        bundle = capture_bundle(str(path.parent))
        self.assertNotEqual(bundle.digest, self.bundle.digest)
        with mock.patch.object(executor, "create_scene_snapshot") as snapshot, \
                mock.patch.object(executor, "render_in_container") as child:
            executor.execute_scene(replace(self.execution(), bundle=bundle))
        snapshot.assert_called_once()
        child.assert_called_once()
        self.native.assert_not_called()

    def test_sealed_version_change_during_staging_refuses_launch(self) -> None:
        """The last sealed staging boundary cannot switch the approved version."""
        runtime = self.sealed("0.7.33")

        def staged(_request: executor.SceneSnapshotRequest) -> object:
            """Change only the explicit TEST approval leaf at the snapshot seam."""
            runtime.approval["probedClosure"]["hyperframesVersion"] = "0.8.31"
            return object()

        with mock.patch.object(executor, "create_scene_snapshot", side_effect=staged), \
                mock.patch.object(executor, "render_in_container") as child:
            with self.assertRaisesRegex(SceneContractError, "runtime.*version"):
                executor.execute_scene(self.execution())
        child.assert_not_called()

    def test_sealed_cache_return_cannot_change_the_approved_version(self) -> None:
        """A cached return still requires the bundle's approved runtime version."""
        runtime = self.sealed("0.7.33")

        def cached(*_args: object) -> tuple[str, bool, dict]:
            """Mutate only the explicit TEST approval, without opening media."""
            runtime.approval["probedClosure"]["hyperframesVersion"] = "0.8.31"
            return "TEST-output", True, {}

        with mock.patch.object(renderer, "container_cache_identity", return_value=b"TEST-OCI"), \
                mock.patch.object(renderer, "materialize", side_effect=cached):
            with self.assertRaisesRegex(SceneContractError, "runtime.*version"):
                renderer.render_scene(self.request())


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Private artifact roots must not become render-graph store authority."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from types import SimpleNamespace

from current_render_graph_build import GraphBuildInputs, compile_graph
from current_render_graph_cli import _parse, execute


class CurrentRenderGraphArtifactDirectoryTests(unittest.TestCase):
    """Graph generations can bind isolated child-plan render outputs."""

    def test_failed_readiness_stops_before_cache_reuse_or_child_work(self) -> None:
        """An old graph cannot waive current review after an intent/plan change."""
        inputs = SimpleNamespace(audio_clock_policy='legacy-v1', plan_path=Path('/TEST/plan'),
            manifest_path=Path('/TEST/manifest'), producer_dir=Path('/TEST/producer'))
        config = SimpleNamespace(inputs=inputs, command=('TEST',))
        with mock.patch('current_render_graph_cli.validate_audio_command'), \
                mock.patch('current_render_graph_cli.require_readiness',
                           side_effect=RuntimeError('TEST stale review')) as admission, \
                mock.patch('current_render_graph_cli._preflight') as preflight, \
                mock.patch('current_render_graph_cli._clean_graph_hit') as reuse, \
                mock.patch('current_render_graph_cli._run_child') as child:
            with self.assertRaisesRegex(RuntimeError, 'TEST stale review'):
                execute(config)
        admission.assert_called_once()
        preflight.assert_not_called()
        reuse.assert_not_called()
        child.assert_not_called()

    def test_cli_carries_explicit_artifact_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            authority, artifacts = root / "authority", root / "candidate"
            authority.mkdir()
            artifacts.mkdir()
            plan, manifest = artifacts / "edit_plan.json", root / "manifest.json"
            plan.write_text("{}")
            manifest.write_text("{}")
            config = _parse([
                "--phase", "assemble",
                "--producer-dir", str(authority),
                "--artifact-dir", str(artifacts),
                "--plan", str(plan),
                "--manifest", str(manifest),
                "--base", str(artifacts / "base_final.mp4"),
                "--output", str(artifacts / "final.mp4"),
                "--", "/bin/true",
            ])
            self.assertEqual(config.inputs.producer_dir, authority.resolve())
            self.assertEqual(config.inputs.artifact_root, artifacts.resolve())

    def test_private_sidecars_resolve_outside_authority_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            authority, artifacts, cache = (
                root / "authority", root / "candidate", root / "cache")
            for directory in (authority, artifacts, cache):
                directory.mkdir()
            plan = artifacts / "edit_plan.json"
            manifest = root / "asset_manifest.json"
            plan.write_text(json.dumps({"graphicsTrack": []}))
            manifest.write_text("{}")
            for name in ("timeline_map.json", "base_final.mp4", "final.mp4"):
                (artifacts / name).write_bytes(name.encode())
            source_receipt = root / "source-set.json"
            source_receipt.write_bytes(b"source authority")
            inputs = GraphBuildInputs(
                authority, plan, manifest, artifacts / "base_final.mp4",
                artifacts / "final.mp4", cache, artifact_dir=artifacts)
            with mock.patch(
                "current_render_graph_build.source_authority",
                return_value=({
                    "source.manifest": "1" * 64,
                    "source.set": "2" * 64,
                }, source_receipt),
            ), mock.patch(
                "current_render_graph_build.probe_video",
                return_value={"r_frame_rate": "24/1"},
            ), mock.patch(
                "current_render_graph_build.current_toolchain_hash",
                return_value="3" * 64,
            ):
                graph, receipts = compile_graph(inputs, [], None)
            by_id = {row["nodeId"]: row for row in receipts}
            self.assertEqual(
                by_id["node-timeline"]["path"],
                str((artifacts / "timeline_map.json").resolve()),
            )
            self.assertFalse((authority / "timeline_map.json").exists())
            self.assertEqual(graph["rootNodeId"], "node-final")


if __name__ == "__main__":
    unittest.main(verbosity=2)

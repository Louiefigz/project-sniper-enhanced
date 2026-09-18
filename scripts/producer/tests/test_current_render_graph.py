"""Durable current-render graph and actual-media oracle regressions."""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from current_render_graph_build import (
    GraphBuildInputs,
    classify_nodes,
    compile_graph,
)
from current_render_graph_contract import (
    file_hash,
    object_hash,
    validate_graph,
)
from current_render_graph_store import load_active, publish, verify_artifacts
from current_render_oracle import codec_floor_passes, prove


def _node(
    node_id: str,
    kind: str,
    dependencies: list[str],
    path: Path,
) -> dict:
    return {
        "nodeId": node_id, "kind": kind, "dependencies": dependencies,
        "inputDigests": {f"{node_id}.input": object_hash(node_id)},
        "outputArtifactHash": file_hash(path), "frameRange": None,
    }


def _graph(root: Path) -> tuple[dict, list[dict]]:
    names = ("source", "timeline", "base", "scene", "composite", "final")
    files = {}
    for name in names:
        path = root / f"{name}.bin"
        path.write_bytes(f"actual-{name}".encode())
        files[name] = path
    nodes = [
        _node("node-source", "source-snapshot", [], files["source"]),
        _node("node-timeline", "timeline-map", ["node-source"], files["timeline"]),
        _node("node-base", "base-segment",
              ["node-source", "node-timeline"], files["base"]),
        _node("node-scene-0000", "scene-unit",
              ["node-timeline"], files["scene"]),
        _node("node-composite", "composite-window",
              ["node-base", "node-scene-0000"], files["composite"]),
        _node("node-final", "final-export", ["node-composite"], files["final"]),
    ]
    graph = {
        "schemaVersion": 1, "graphId": "current-render-test",
        "toolchainHash": "a" * 64, "rootNodeId": "node-final",
        "nodes": nodes,
    }
    artifacts = [{
        "nodeId": row["nodeId"], "path": str(files[name].resolve()),
        "sha256": row["outputArtifactHash"],
        "sizeBytes": files[name].stat().st_size,
    } for row, name in zip(nodes, names)]
    return graph, artifacts


def _receipt(graph: dict, artifacts: list[dict]) -> dict:
    return {
        "schemaVersion": 1, "kind": "current-render-graph-execution",
        "graphHash": object_hash(graph), "executionMode": "incremental",
        "previousGraphHash": None,
        "dirtyNodeIds": [row["nodeId"] for row in graph["nodes"]],
        "reusedNodeIds": [], "artifacts": artifacts,
    }

def _build_inputs(root: Path, plan: dict) -> GraphBuildInputs:
    producer = root / "producer"
    cache = root / "cache"
    producer.mkdir()
    cache.mkdir()
    plan_path = producer / "edit_plan.json"
    manifest = root / "asset_manifest.json"
    plan_path.write_text(json.dumps(plan))
    manifest.write_text("{}")
    for name, payload in (
        ("timeline_map.json", b"timeline"),
        ("base_final.mp4", b"base-media"),
        ("final.mp4", b"final-media"),
    ):
        (producer / name).write_bytes(payload)
    return GraphBuildInputs(
        producer, plan_path, manifest, producer / "base_final.mp4",
        producer / "final.mp4", cache)

class CurrentRenderGraphTests(unittest.TestCase):
    def test_missing_scene_dependency_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            graph, _ = _graph(Path(tmp))
            broken = copy.deepcopy(graph)
            composite = next(
                row for row in broken["nodes"]
                if row["nodeId"] == "node-composite")
            composite["dependencies"].remove("node-scene-0000")
            with self.assertRaisesRegex(RuntimeError, "missing required"):
                validate_graph(broken)
    def test_active_pointer_hashes_fail_closed_before_path_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = root / ".render-graph-v1"
            store.mkdir()
            (store / "ACTIVE.json").write_text(json.dumps({
                "schemaVersion": 1, "graphHash": "../" + "a" * 61,
                "receiptHash": "b" * 64,
            }))
            with self.assertRaisesRegex(RuntimeError, "hashes are malformed"):
                load_active(root)
    def test_generation_rehashes_every_retained_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph, artifacts = _graph(root)
            graph_hash = publish(root, graph, _receipt(graph, artifacts))
            active = load_active(root)
            self.assertIsNotNone(active)
            self.assertEqual(object_hash(active[0]), graph_hash)
            verify_artifacts(*active)
            Path(artifacts[2]["path"]).write_bytes(b"mutated base")
            with self.assertRaisesRegex(RuntimeError, "corrupt"):
                verify_artifacts(*active)
    def test_invalidation_is_dependency_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            graph, artifacts = _graph(Path(tmp))
            previous = (copy.deepcopy(graph), _receipt(graph, artifacts))
            changed = copy.deepcopy(graph)
            scene = next(
                row for row in changed["nodes"]
                if row["nodeId"] == "node-scene-0000")
            scene["inputDigests"]["node-scene-0000.input"] = "b" * 64
            dirty, reused = classify_nodes(changed, previous, False)
            self.assertEqual(dirty, [
                "node-scene-0000", "node-composite", "node-final"])
            self.assertEqual(reused, [
                "node-source", "node-timeline", "node-base"])
    def test_changed_output_bytes_invalidate_dependency_closure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            graph, artifacts = _graph(Path(tmp))
            previous = (copy.deepcopy(graph), _receipt(graph, artifacts))
            changed = copy.deepcopy(graph)
            scene = next(
                row for row in changed["nodes"]
                if row["nodeId"] == "node-scene-0000")
            scene["outputArtifactHash"] = "b" * 64
            dirty, reused = classify_nodes(changed, previous, False)
            self.assertEqual(dirty, [
                "node-scene-0000", "node-composite", "node-final"])
            self.assertEqual(reused, [
                "node-source", "node-timeline", "node-base"])
    def test_graph_binds_actual_scene_cache_bytes_and_required_edge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = {"cutTrack": [
                {"sourceId": "raw", "start": 0, "end": 1},
                {"sourceId": "raw", "start": 1, "end": 2}],
                "graphicsTrack": [{
                    "kind": "statement-card", "outStart": 0.5,
                    "outEnd": 1.8, "exitOnCut": True,
                    "spec": {"text": "Proof"}}]}
            inputs = _build_inputs(root, plan)
            key = "1" * 40
            scene = inputs.cache_dir / f"{key}.mov"
            scene.write_bytes(b"actual-scene-media")
            source = root / "source-set.json"
            source.write_bytes(b"source authority")
            events = [{
                "stage": "graphics", "status": "rendered",
                "kind": "statement-card", "key": key, "fmt": "mov",
            }]
            with mock.patch(
                    "current_render_graph_build.source_authority",
                    return_value=({"source.manifest": "2" * 64,
                                   "source.set": "3" * 64}, source)), \
                    mock.patch(
                        "current_render_graph_build.probe_video",
                        return_value={"r_frame_rate": "24/1"}), \
                    mock.patch(
                        "current_render_graph_build.current_toolchain_hash",
                        return_value="4" * 64):
                graph, artifacts = compile_graph(inputs, events, None)
            composite = next(
                row for row in graph["nodes"]
                if row["nodeId"] == "node-composite")
            scene_node = next(
                row for row in graph["nodes"]
                if row["nodeId"] == "node-scene-0000")
            self.assertIn("node-scene-0000", composite["dependencies"])
            self.assertEqual(scene_node["outputArtifactHash"], file_hash(scene))
            self.assertEqual(scene_node["frameRange"], {
                "startFrame": 12, "endFrameExclusive": 24})
            self.assertIn(str(scene.resolve()), {
                row["path"] for row in artifacts})

    def test_graph_binds_caption_shard_and_caption_free_composite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = _build_inputs(root, {
                "graphicsTrack": [], "captionsTrack": {"schemaVersion": 1},
            })
            (inputs.producer_dir / "caption_shards.json").write_text("{}")
            shard = inputs.producer_dir / "caption-shard.mov"
            shard.write_bytes(b"actual-caption-alpha")
            composite = inputs.producer_dir / ".caption-free-composite.mp4"
            composite.write_bytes(b"actual-caption-free-composite")
            source = root / "source-set.json"
            source.write_bytes(b"source authority")
            manifest = {"entries": [{
                    "media": {"name": shard.name, "sha256": file_hash(shard)},
                    **{key: "5" * 64 for key in (
                        "mediaKey", "placedShardKey", "contentAssetKey",
                        "rendererHash", "fontClosureHash")},
                    "cueId": "cue-0000000000000000",
                    "startFrame": 10, "endFrameExclusive": 20,
                }]}
            patches = (
                mock.patch("current_render_graph_build.source_authority",
                           return_value=({
                               "source.manifest": "2" * 64,
                               "source.set": "3" * 64}, source)),
                mock.patch("current_render_graph_build.probe_video",
                           return_value={"r_frame_rate": "24/1"}),
                mock.patch("current_render_graph_build.current_toolchain_hash",
                           return_value="4" * 64),
                mock.patch(
                    "current_render_graph_build.has_explicit_caption_track",
                    return_value=True),
                mock.patch(
                    "current_render_graph_build.validate_caption_shard_manifest",
                    return_value=manifest),
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                graph, _ = compile_graph(inputs, [], None)
            caption = next(
                row for row in graph["nodes"]
                if row["nodeId"] == "node-caption-0000")
            composite_node = next(
                row for row in graph["nodes"]
                if row["nodeId"] == "node-composite")
            self.assertEqual(caption["outputArtifactHash"], file_hash(shard))
            self.assertIn("node-caption-0000", composite_node["dependencies"])
            self.assertEqual(
                composite_node["outputArtifactHash"], file_hash(composite))

@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg required")
class CurrentRenderOracleMediaTests(unittest.TestCase):
    def _media(self, path: Path, color: str = "blue") -> None:
        subprocess.run([
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i",
            f"color=c={color}:s=96x54:r=24:d=0.5,"
            "drawbox=x='mod(t*80,70)':y=12:w=20:h=20:color=white:t=fill",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:d=0.5",
            "-frames:v", "12", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
        ], check=True)

    def test_complete_decode_matches_forced_full_and_catches_picture_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            incremental = root / "incremental.mp4"
            forced = root / "forced.mp4"
            changed = root / "changed.mp4"
            self._media(incremental)
            self._media(forced)
            self._media(changed, "red")
            receipt = prove(incremental, forced, root / "oracle.json")
            self.assertTrue(receipt["passed"])
            self.assertTrue(
                receipt["pictureComparison"]["codecFloorEquivalent"])
            with self.assertRaisesRegex(RuntimeError, "not codec-floor"):
                prove(incremental, changed, root / "bad-oracle.json")

    def test_codec_floor_policy_accepts_observed_control_not_picture_drift(
            self) -> None:
        self.assertTrue(codec_floor_passes({
            "comparedFrames": 1350, "meanSsim": 0.997570375,
            "minimumFrameSsim": 0.991984,
        }))
        self.assertFalse(codec_floor_passes({
            "comparedFrames": 1350, "meanSsim": 0.994999,
            "minimumFrameSsim": 0.991984,
        }))
        self.assertFalse(codec_floor_passes({
            "comparedFrames": 1350, "meanSsim": 0.997570375,
            "minimumFrameSsim": 0.984999,
        }))
if __name__ == "__main__":
    unittest.main(verbosity=2)

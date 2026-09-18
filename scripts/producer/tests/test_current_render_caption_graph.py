"""P3 caption shards remain independently addressable in the current graph."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from current_render_graph_build import (
    GraphBuildInputs,
    classify_nodes,
    compile_graph,
)
from current_render_graph_contract import file_hash


def _inputs(root: Path, plan: dict) -> GraphBuildInputs:
    producer, cache = root / "producer", root / "cache"
    producer.mkdir()
    cache.mkdir()
    plan_path, manifest = producer / "edit_plan.json", root / "manifest.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    manifest.write_text("{}", encoding="utf-8")
    for name in ("timeline_map.json", "base_final.mp4", "final.mp4",
                 ".caption-free-composite.mp4"):
        (producer / name).write_bytes(name.encode())
    return GraphBuildInputs(
        producer, plan_path, manifest, producer / "base_final.mp4",
        producer / "final.mp4", cache)


def _row(root: Path, index: int, salt: str) -> dict:
    path = root / f"caption-{index}-{salt}.mov"
    path.write_bytes(f"caption-{index}-{salt}".encode())
    return {
        "cueId": f"cue-{index:016x}", "mediaKey": salt * 64,
        "placedShardKey": salt * 64, "contentAssetKey": salt * 64,
        "rendererHash": "a" * 64, "fontClosureHash": "b" * 64,
        "startFrame": index * 10, "endFrameExclusive": index * 10 + 8,
        "media": {"name": path.name, "sha256": file_hash(path)},
    }


class CurrentRenderCaptionGraphTests(unittest.TestCase):
    def test_one_caption_correction_dirties_only_its_shard_closure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = {
                "graphicsTrack": [], "captionsTrack": {"schemaVersion": 1},
                "captionCorrectionLedger": {"corrections": []},
            }
            inputs = _inputs(root, plan)
            (inputs.producer_dir / "caption_shards.json").write_text(
                "{}", encoding="utf-8")
            before_rows = [_row(inputs.producer_dir, 0, "c"),
                           _row(inputs.producer_dir, 1, "d")]
            after_rows = [copy.deepcopy(before_rows[0]),
                          _row(inputs.producer_dir, 1, "e")]
            source = root / "source-set.json"
            source.write_bytes(b"source authority")
            common = (
                mock.patch("current_render_graph_build.source_authority",
                           return_value=({"source.manifest": "1" * 64,
                                          "source.set": "2" * 64}, source)),
                mock.patch("current_render_graph_build.probe_video",
                           return_value={"r_frame_rate": "24/1"}),
                mock.patch("current_render_graph_build.current_toolchain_hash",
                           return_value="3" * 64),
                mock.patch("current_render_graph_build."
                           "has_explicit_caption_track", return_value=True),
            )
            validator = mock.patch(
                "current_render_graph_build.validate_caption_shard_manifest",
                side_effect=[{"entries": before_rows}, {"entries": after_rows}])
            with common[0], common[1], common[2], common[3], validator:
                before, artifacts = compile_graph(inputs, [], None)
                plan["captionCorrectionLedger"] = {"corrections": ["changed"]}
                inputs.plan_path.write_text(json.dumps(plan), encoding="utf-8")
                after, _ = compile_graph(inputs, [], None)
            dirty, reused = classify_nodes(
                after, (before, {"artifacts": artifacts}), False)
            self.assertEqual(dirty, [
                "node-caption-0001", "node-composite", "node-final"])
            self.assertIn("node-caption-0000", reused)
            self.assertIn("node-base", reused)


if __name__ == "__main__":
    unittest.main(verbosity=2)

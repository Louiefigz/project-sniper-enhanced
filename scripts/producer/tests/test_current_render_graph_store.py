"""Content-addressed current-render graph store regressions."""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from current_render_graph_contract import file_hash, object_hash
from current_render_graph_store import load_active, publish


def _generation(root: Path) -> tuple[dict, dict]:
    artifact = root / "final.mp4"
    artifact.write_bytes(b"retained-final")
    node = {
        "nodeId": "node-final",
        "kind": "final-export",
        "dependencies": [],
        "inputDigests": {"final.input": "a" * 64},
        "outputArtifactHash": file_hash(artifact),
        "frameRange": None,
    }
    graph = {
        "schemaVersion": 1,
        "graphId": "store-receipt-generation-test",
        "toolchainHash": "b" * 64,
        "rootNodeId": "node-final",
        "nodes": [node],
    }
    receipt = {
        "schemaVersion": 1,
        "kind": "current-render-graph-execution",
        "graphHash": object_hash(graph),
        "executionMode": "incremental",
        "previousGraphHash": None,
        "dirtyNodeIds": ["node-final"],
        "reusedNodeIds": [],
        "artifacts": [{
            "nodeId": "node-final",
            "path": str(artifact.resolve()),
            "sha256": node["outputArtifactHash"],
            "sizeBytes": artifact.stat().st_size,
        }],
    }
    return graph, receipt


class CurrentRenderGraphStoreTests(unittest.TestCase):
    def test_one_graph_retains_multiple_content_addressed_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph, first = _generation(root)
            second = copy.deepcopy(first)
            second["executionMode"] = "forced-full"
            publish(root, graph, first)
            publish(root, graph, second)
            active = load_active(root)
            self.assertIsNotNone(active)
            self.assertEqual(active[1], second)
            receipts = (
                root / ".render-graph-v1" / "generations"
                / object_hash(graph) / "receipts"
            )
            self.assertEqual(
                {path.stem for path in receipts.glob("*.json")},
                {object_hash(first), object_hash(second)},
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)

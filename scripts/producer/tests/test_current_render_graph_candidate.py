"""QC-gated current-render graph candidate regressions."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from current_render_graph_candidate import (
    activate_candidate,
    candidate_is_active,
    rollback_candidate,
    verify_candidate,
)
from current_render_graph_contract import file_hash, object_hash
from current_render_graph_store import (
    load_active,
    publish,
    stage_candidate,
    verify_artifacts,
)
from current_render_toolchain import current_toolchain_hash
from _ingest_admission_fixture import runner as admission_runner
from ingest_admission import IngressCandidate, admit_ingest_candidates


def _source_node(source_receipt: Path, admission: object) -> dict:
    source_entry = next(iter(admission.media_by_original.values()))
    return {
        "nodeId": "node-source",
        "kind": "source-snapshot",
        "dependencies": [],
        "inputDigests": {
            "source.manifest": "c" * 64,
            "source.set": admission.binding["sourceSetDigest"],
            "source.stageRoot": "d" * 64,
            "source.0000": source_entry.sha256,
        },
        "outputArtifactHash": file_hash(source_receipt),
        "frameRange": None,
    }


def _graph_and_receipt(
    candidate: Path,
    source_receipt: Path,
    source: dict,
) -> tuple[dict, dict]:
    final = {
        "nodeId": "node-final",
        "kind": "final-export",
        "dependencies": ["node-source"],
        "inputDigests": {"final.plan": "a" * 64},
        "outputArtifactHash": file_hash(candidate),
        "frameRange": None,
    }
    graph = {
        "schemaVersion": 1,
        "graphId": "qc-gated-candidate-test",
        "toolchainHash": current_toolchain_hash(),
        "rootNodeId": "node-final",
        "nodes": [source, final],
    }
    receipt = {
        "schemaVersion": 1,
        "kind": "current-render-graph-execution",
        "graphHash": object_hash(graph),
        "executionMode": "incremental",
        "previousGraphHash": None,
        "dirtyNodeIds": ["node-source", "node-final"],
        "reusedNodeIds": [],
        "artifacts": [
            {
                "nodeId": "node-source",
                "path": str(source_receipt.resolve()),
                "sha256": file_hash(source_receipt),
                "sizeBytes": source_receipt.stat().st_size,
            },
            {
                "nodeId": "node-final",
                "path": str(candidate.resolve()),
                "sha256": file_hash(candidate),
                "sizeBytes": candidate.stat().st_size,
            },
        ],
    }
    return graph, receipt


def _candidate_generation(
    root: Path,
) -> tuple[Path, dict, dict, Path]:
    root = root.resolve()
    candidate = root / "private" / "final.mp4"
    candidate.parent.mkdir()
    candidate.write_bytes(b"qc-private-candidate")
    original = root / "raw.mp4"
    original.write_bytes(b"source-before-review")
    admission = admit_ingest_candidates(
        [IngressCandidate(original, "source")], root, admission_runner)
    source_receipt = root / admission.binding["receiptPath"]
    source_entry = next(iter(admission.media_by_original.values()))
    graph, receipt = _graph_and_receipt(
        candidate, source_receipt, _source_node(source_receipt, admission))
    return candidate, graph, receipt, Path(source_entry.snapshot_path)


class CurrentRenderGraphCandidateTests(unittest.TestCase):
    def test_stage_does_not_advance_active_until_exact_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate, graph, receipt, _snapshot = _candidate_generation(root)
            expected = file_hash(candidate)
            graph_hash = stage_candidate(root, graph, receipt, candidate)
            self.assertEqual(graph_hash, object_hash(graph))
            self.assertIsNone(load_active(root))
            self.assertEqual(
                verify_candidate(root, candidate, expected), graph_hash)

            final = root / "final.mp4"
            candidate.rename(final)
            self.assertEqual(
                activate_candidate(root, candidate, final, expected),
                graph_hash)
            active = load_active(root)
            self.assertIsNotNone(active)
            verify_artifacts(*active)
            artifact = active[1]["artifacts"][1]
            self.assertEqual(artifact["path"], str(final.resolve()))
            self.assertEqual(artifact["sha256"], expected)
            self.assertTrue(
                candidate_is_active(root, candidate, final, expected))

            final.rename(candidate)
            self.assertIsNone(
                rollback_candidate(root, candidate, final, expected))
            self.assertIsNone(load_active(root))

    def test_tampered_candidate_cannot_advance_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate, graph, receipt, _snapshot = _candidate_generation(root)
            expected = file_hash(candidate)
            stage_candidate(root, graph, receipt, candidate)
            candidate.write_bytes(b"changed-after-qc")
            with self.assertRaisesRegex(RuntimeError, "bytes changed"):
                verify_candidate(root, candidate, expected)
            self.assertIsNone(load_active(root))

    def test_candidate_path_cannot_be_rebound_to_another_graph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate, graph, receipt, _snapshot = _candidate_generation(root)
            stage_candidate(root, graph, receipt, candidate)
            changed = json.loads(json.dumps(graph))
            changed["toolchainHash"] = "c" * 64
            changed_receipt = json.loads(json.dumps(receipt))
            changed_receipt["graphHash"] = object_hash(changed)
            with self.assertRaisesRegex(RuntimeError, "already staged"):
                stage_candidate(
                    root, changed, changed_receipt, candidate)

    def test_foreign_active_graph_blocks_late_candidate_activation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate, graph, receipt, _snapshot = _candidate_generation(root)
            expected = file_hash(candidate)
            stage_candidate(root, graph, receipt, candidate)
            foreign = json.loads(json.dumps(graph))
            foreign["toolchainHash"] = "d" * 64
            foreign_receipt = json.loads(json.dumps(receipt))
            foreign_receipt["graphHash"] = object_hash(foreign)
            publish(root, foreign, foreign_receipt)
            final = root / "final.mp4"
            candidate.rename(final)
            with self.assertRaisesRegex(RuntimeError, "changed after"):
                activate_candidate(root, candidate, final, expected)
            self.assertEqual(object_hash(load_active(root)[0]),
                             object_hash(foreign))
            final.rename(candidate)
            with self.assertRaisesRegex(RuntimeError, "foreign"):
                rollback_candidate(root, candidate, final, expected)

    def test_source_mutation_during_review_cannot_promote(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate, graph, receipt, snapshot = _candidate_generation(root)
            expected = file_hash(candidate)
            stage_candidate(root, graph, receipt, candidate)
            snapshot.write_bytes(b"source-changed-during-review")
            with self.assertRaisesRegex(RuntimeError, "snapshot"):
                verify_candidate(root, candidate, expected)
            final = root / "final.mp4"
            final.write_bytes(candidate.read_bytes())
            with self.assertRaisesRegex(RuntimeError, "snapshot"):
                activate_candidate(root, candidate, final, expected)
            self.assertIsNone(load_active(root))

    def test_toolchain_drift_blocks_verify_and_activation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate, graph, receipt, _snapshot = _candidate_generation(root)
            expected = file_hash(candidate)
            stage_candidate(root, graph, receipt, candidate)
            with mock.patch(
                    "current_render_graph_candidate.current_toolchain_hash",
                    return_value="0" * 64):
                with self.assertRaisesRegex(RuntimeError, "toolchain is stale"):
                    verify_candidate(root, candidate, expected)
                final = root / "final.mp4"
                final.write_bytes(candidate.read_bytes())
                with self.assertRaisesRegex(RuntimeError, "toolchain is stale"):
                    activate_candidate(root, candidate, final, expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)

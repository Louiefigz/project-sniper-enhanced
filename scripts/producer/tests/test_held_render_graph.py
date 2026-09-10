"""Regressions for the two metadata races Codex reproduced against the reuse path.

Real valid graph generations published by the actual store; no media. A generation
flip between validation and the raw read must reject, never pair master A with
generation B's files; the pointer hash is captured before the loader and any
pointer change during selection fails closed; later holds can never override the
original public hold.
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from audio import assemble_picture_reuse as picture
from audio import assemble_source_audio as assembly
from audio import held_render_graph as held
from audio import program_master_reuse as reuse
from current_render_graph_contract import object_hash
from current_render_graph_store import load_active, publish
from cut_preview_io import file_hash, write_new
from test_current_render_graph_store import _generation


def _pair(root: Path) -> tuple[tuple[dict, dict], tuple[dict, dict]]:
    """Two real valid generations A and B for the same output; ACTIVE ends on A."""
    root.mkdir()
    first, receipt = _generation(root)
    first["nodes"][0]["inputDigests"]["audio.programReceipt"] = "a" * 64
    receipt["graphHash"] = object_hash(first)
    second, second_receipt = copy.deepcopy(first), copy.deepcopy(receipt)
    second["nodes"][0]["inputDigests"]["audio.programReceipt"] = "b" * 64
    second_receipt["graphHash"] = object_hash(second)
    publish(root, second, second_receipt)
    publish(root, first, receipt)
    assert load_active(root) == (first, receipt)
    return (first, receipt), (second, second_receipt)


def _paths(root: Path, pair: tuple[dict, dict]) -> set[str]:
    graph, receipt = pair
    generation = root / held.GRAPH_DIR / "generations" / object_hash(graph)
    return {str(root / held.GRAPH_DIR / held.ACTIVE_NAME), str(generation / "graph.json"),
            str(generation / "receipts" / (object_hash(receipt) + ".json"))}


class HeldRenderGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="sniper-held-graph-", dir="/private/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve() / "producer"
        self.first, self.second = _pair(self.root)

    def test_single_read_holds_exactly_the_selected_generation_files(self) -> None:
        generation = held.held_active_generation(self.root)
        self.assertEqual((generation.graph, generation.execution), self.first)
        self.assertEqual(set(generation.files), _paths(self.root, self.first))
        for path, digest in generation.files.items():
            self.assertEqual(file_hash(Path(path)), digest)
        selection = reuse.held_program_selection(self.root, self.root / "final.mp4")
        self.assertEqual(selection[0], "a" * 64)
        self.assertEqual(set(selection[1]), _paths(self.root, self.first))

    def test_generation_flip_between_validation_and_raw_read_rejects(self) -> None:
        """Codex reproducer: A -> B -> A around the raw ACTIVE read. Old code returned A with B's files."""
        active = self.root / held.GRAPH_DIR / held.ACTIVE_NAME
        original = held.read_bytes

        def excursion(path: Path, *args, **kwargs) -> bytes:
            if path != active:
                return original(path, *args, **kwargs)
            publish(self.root, *self.second)
            raw = original(path, *args, **kwargs)
            publish(self.root, *self.first)
            return raw

        with patch.object(held, "read_bytes", side_effect=excursion):
            with self.assertRaisesRegex(RuntimeError, "no longer names the validated generation"):
                held.held_active_generation(self.root)
            with self.assertRaisesRegex(RuntimeError, "no longer names the validated generation"):
                reuse.held_program_selection(self.root, self.root / "final.mp4")
        self.assertEqual(load_active(self.root), self.first)

    def test_active_pointer_swapped_to_another_version_or_shape_rejects_like_load_active(self) -> None:
        """Codex residual: the raw ACTIVE bytes must satisfy the same closed v1 shape as
        load_active, not only name the right hashes. Same generation, different shape."""
        active = self.root / held.GRAPH_DIR / held.ACTIVE_NAME
        valid = json.loads(active.read_bytes())
        original = held.read_bytes
        for label, swapped in (("version-swap", {**valid, "schemaVersion": 2}),
                               ("extra-field", {**valid, "note": "TEST extra field"}),
                               ("missing-field", {key: value for key, value in valid.items() if key != "receiptHash"})):
            raw = json.dumps(swapped).encode()

            def substitute(path: Path, *args, **kwargs) -> bytes:
                return raw if path == active else original(path, *args, **kwargs)

            with self.subTest(label=label), patch.object(held, "read_bytes", side_effect=substitute), \
                    self.assertRaisesRegex(RuntimeError, "pointer is malformed"):
                held.held_active_generation(self.root)
        generation = held.held_active_generation(self.root)
        self.assertEqual((generation.graph, generation.execution), self.first, "valid v1 pointer still selects")

    def test_retained_generation_bytes_must_hash_back_to_the_validated_objects(self) -> None:
        generation = self.root / held.GRAPH_DIR / "generations" / object_hash(self.first[0])
        original = held.read_bytes
        swapped = json.dumps(self.second[0]).encode()

        def substitute(path: Path, *args, **kwargs) -> bytes:
            return swapped if path == generation / "graph.json" else original(path, *args, **kwargs)

        with patch.object(held, "read_bytes", side_effect=substitute):
            with self.assertRaisesRegex(RuntimeError, "differ from the validated read"):
                held.held_active_generation(self.root)

    def test_picture_reuse_authority_uses_the_same_single_read(self) -> None:
        record = {"pictureReuseInputHash": "c" * 64, "finalSha256": self.first[0]["nodes"][0]["outputArtifactHash"],
                  "programMasterReceiptHash": "a" * 64}
        self.first[0]["nodes"][0]["inputDigests"]["picture.reuse"] = "c" * 64
        self.first[1]["graphHash"] = object_hash(self.first[0])
        publish(self.root, *self.first)
        files = picture._graph_authority(self.root, self.root / "final.mp4", record)
        self.assertEqual(set(files), _paths(self.root, self.first))
        active = self.root / held.GRAPH_DIR / held.ACTIVE_NAME
        original = held.read_bytes

        def excursion(path: Path, *args, **kwargs) -> bytes:
            if path != active:
                return original(path, *args, **kwargs)
            publish(self.root, *self.second)
            raw = original(path, *args, **kwargs)
            publish(self.root, *self.first)
            return raw

        with patch.object(held, "read_bytes", side_effect=excursion), \
                self.assertRaisesRegex(RuntimeError, "no longer names the validated generation"):
            picture._graph_authority(self.root, self.root / "final.mp4", record)

    def test_pointer_changed_during_selection_fails_closed_with_the_original_hash_held(self) -> None:
        """Codex reproducer: the loader replaces the pointer A -> B; the late hash must never win."""
        path = self.root / reuse.PROGRAM_AUDIO_POINTER
        pointer = {"schemaVersion": 2, "kind": "ordinary-program-audio-pointer", "audioClockPolicy": "source-float-v2",
                   "programMasterReceiptPath": str(self.root / "TEST-master-A.json"), "programMasterReceiptHash": "a" * 64}
        write_new(path, pointer)
        write_new(self.root / "TEST-pointer-B.json", {**pointer, "programMasterReceiptHash": "b" * 64})
        job = SimpleNamespace(out=str(self.root / "final.mp4"), plan={})

        def swapping_loader(_bus: object, _plan: dict, selection: tuple) -> object:
            self.assertEqual(selection, (pointer["programMasterReceiptPath"], "a" * 64))
            os.replace(self.root / "TEST-pointer-B.json", path)
            return SimpleNamespace(receipt={"receiptHash": "a" * 64})

        with patch.object(reuse, "load_program_master", side_effect=swapping_loader):
            with self.assertRaisesRegex(RuntimeError, "pointer changed during master selection"):
                reuse.retained_program_master(job, object(), self.root)
        write_new(self.root / "TEST-pointer-A.json", pointer)
        os.replace(self.root / "TEST-pointer-A.json", path)
        before = file_hash(path)
        with patch.object(reuse, "load_program_master", return_value=SimpleNamespace(receipt={"receiptHash": "a" * 64})):
            master, reason, files = reuse.retained_program_master(job, object(), self.root)
        self.assertIsNone(reason)
        self.assertEqual(files[str(path)], before, "the hash held is the one captured BEFORE the loader")

    def test_later_holds_never_override_the_original_public_hold(self) -> None:
        job = SimpleNamespace(out=str(self.root / "final.mp4"), plan={}, plan_path=str(self.root / "edit_plan.json"))
        write_new(Path(job.plan_path), {})
        path = self.root / reuse.PROGRAM_AUDIO_POINTER
        write_new(path, {"schemaVersion": 2})
        original = file_hash(path)
        candidate = assembly._AssemblyCandidate(job, self.root, file_hash(Path(job.plan_path)), {str(path): original}, {})
        path.write_text(json.dumps({"schemaVersion": 2, "changed": True}))
        with self.assertRaisesRegex(RuntimeError, "conflicts with the original public hold"):
            assembly._hold(candidate, {str(path): file_hash(path)})
        same = assembly._hold(candidate, {str(self.root / "other.json"): "0" * 64})
        with self.assertRaisesRegex(RuntimeError, "held inputs or public outputs changed"):
            assembly._assert_held(same)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Controller materialization of multi-source caption dialogue timing."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest

from edit.cut_repair_dialogue_context import materialize_dialogue_context


def _write(path: str, words: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as stream:
        json.dump({"transcript": [{"words": words}]}, stream)


def _source(root: str, source_id: str, words: list[dict]) -> dict:
    transcript = f"{source_id}.json"
    _write(os.path.join(root, transcript), words)
    return {
        "id": source_id,
        "contentHash": hashlib.sha256(source_id.encode()).hexdigest(),
        "transcriptPath": transcript,
        "audio": {"sampleRate": 48_000},
    }


class CutRepairDialogueContextTests(unittest.TestCase):
    def test_only_explicit_captions_materialize_all_kept_sources(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            sources = {
                "source-a": _source(root, "source-a", [
                    {"word": "one", "start": 0.1, "end": 0.2}]),
                "source-b": _source(root, "source-b", [
                    {"word": "two", "start": 1.0, "end": 1.2}]),
            }
            plan = {
                "cutTrack": [
                    {"sourceId": "source-b"},
                    {"sourceId": "source-a"},
                ],
                "captionsTrack": {
                    "schemaVersion": 1,
                    "source": "kept-transcript",
                    "defaultPolicy": "karaoke",
                    "groups": [],
                },
            }
            value = materialize_dialogue_context(plan, sources, root)
        self.assertEqual(
            [row["sourceId"] for row in value["dialogueSources"]],
            ["source-a", "source-b"])
        self.assertRegex(value["sourceSnapshotSetHash"], r"^[0-9a-f]{64}$")
        self.assertRegex(
            value["dialogueSources"][0]["words"][0]["sourceWordId"],
            r"^w-[0-9a-f]{16}$")
        self.assertIsNone(materialize_dialogue_context(
            {"cutTrack": plan["cutTrack"]}, sources, root))

    def test_missing_kept_source_transcript_fails_with_exact_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            source = {
                "id": "source-a", "contentHash": "1" * 64,
                "audio": {"sampleRate": 48_000},
            }
            plan = {
                "cutTrack": [{"sourceId": "source-a"}],
                "captionsTrack": {},
            }
            with self.assertRaisesRegex(
                    ValueError, "CAPTION_DIALOGUE_SOURCE_TIMING_REQUIRED"):
                materialize_dialogue_context(
                    plan, {"source-a": source}, root)


if __name__ == "__main__":
    unittest.main(verbosity=2)

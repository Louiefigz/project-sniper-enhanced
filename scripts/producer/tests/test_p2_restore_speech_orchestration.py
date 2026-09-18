"""Closed resolver-to-candidate orchestration tests for P2."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from edit.cut_repair import RestoreSpeechInput, analyze_restore_speech
from edit.target_resolver import PhraseTarget, build_word_refs
from tests.test_p2_non_ripple import CLOCK, HASH, _context


class RestoreSpeechOrchestrationTests(unittest.TestCase):
    def test_resolver_and_candidate_receipt_are_one_closed_analysis(self) -> None:
        words = build_word_refs("raw", [
            {"word": "use", "startSample": 40_000,
             "endSampleExclusive": 47_000, "speaker": "host"},
            {"word": "automation", "startSample": 48_000,
             "endSampleExclusive": 52_800, "speaker": "host"},
        ], HASH)
        context = _context(180)
        result = analyze_restore_speech(RestoreSpeechInput(
            words=tuple(words),
            target=PhraseTarget("automation", occurrence=1),
            segments=context.segments,
            silences=context.silences,
            covered_picture=context.covered_picture,
            replaceable_audio=context.replaceable_audio,
            replaceable_audio_evidence_hash=(
                context.replaceable_audio_evidence_hash),
            dependents=context.dependents,
            clock=CLOCK,
            total_frames=context.total_frames,
            parent_timeline_map_hash=context.parent_timeline_map_hash,
            parent_picture_lock_hash=context.parent_picture_lock_hash,
            max_dirty_frames=context.max_dirty_frames,
            max_audio_overlap_frames=context.max_audio_overlap_frames,
        ))
        self.assertEqual(result["status"], "eligible")
        self.assertEqual(result["operation"], "cut.restoreSpeech")
        self.assertEqual(
            result["evidencePolicy"]["alignment"],
            "bounded-evidence-not-sole-audibility-proof")
        self.assertTrue(all("operationHash" in row
                            for row in result["candidates"]))
        schema_path = (Path(__file__).resolve().parents[3]
                       / "schemas" / "producer"
                       / "cut-restore-speech-v1.schema.json")
        with schema_path.open(encoding="utf-8") as handle:
            schema = json.load(handle)
        for row in result["candidates"]:
            operation = row["operation"]
            self.assertTrue(set(schema["required"]).issubset(operation))
            self.assertTrue(set(operation).issubset(schema["properties"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)

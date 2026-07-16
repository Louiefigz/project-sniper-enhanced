#!/usr/bin/env python3
"""Focused contracts for the transcript-first cut approval gate."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import transcript_cut_contract as contract


def _transcript(include_removed: bool = True) -> dict:
    words = [
        {"word": "Hello", "start": 0.2, "end": 0.5},
        {"word": "world", "start": 0.6, "end": 1.0},
        {"word": "um", "start": 1.5, "end": 1.7},
        {"word": "Restart", "start": 2.2, "end": 2.5},
        {"word": "now", "start": 2.6, "end": 2.9},
        {"word": "done", "start": 3.0, "end": 3.4},
    ]
    if not include_removed:
        words = [word for word in words if word["word"] != "um"]
    return {"transcript": [{"start": 0.2, "end": 3.4,
                             "text": "test", "words": words}]}


def _plan(kind: str = "filler") -> dict:
    return {
        "planVersion": 1,
        "cutTrack": [
            {"sourceId": "raw-1", "start": 0.0, "end": 1.1, "speed": 1,
             "rationale": "Keep the complete opening sentence."},
            {"sourceId": "raw-1", "start": 2.1, "end": 3.5, "speed": 1,
             "rationale": "Keep the clean restarted delivery."},
        ],
        "cutDecisions": {"schemaVersion": 1, "removals": [{
            "sourceId": "raw-1", "start": 1.1, "end": 2.1,
            "kind": kind, "rationale": "Remove the abandoned filler restart.",
            "evidence": {"beforeWord": "world", "afterWord": "Restart",
                         "removedText": "um"},
        }]},
    }


def _quality_transcript(words: list[str]) -> dict:
    timed = [{"word": word, "start": round(0.2 + index * 0.2, 3),
              "end": round(0.35 + index * 0.2, 3)}
             for index, word in enumerate(words)]
    return {"transcript": [{"start": timed[0]["start"], "end": timed[-1]["end"],
                             "text": " ".join(words), "words": timed}]}


def _single_cut(end: float = 1.5) -> dict:
    return {"planVersion": 1, "cutTrack": [{
        "sourceId": "raw-1", "start": 0.0, "end": end, "speed": 1,
        "rationale": "Keep the complete clean delivery for the approved edit.",
    }], "cutDecisions": {"schemaVersion": 1, "removals": []}}


class TranscriptCutContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.transcript_path = os.path.join(self.tmp.name, "raw.transcript.json")
        self.manifest_path = os.path.join(self.tmp.name, "asset_manifest.json")
        self.plan_path = os.path.join(self.tmp.name, "edit_plan.json")
        self._write(_plan(), _transcript())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write(self, plan: dict, transcript: dict,
               manifest: dict | None = None) -> None:
        with open(self.plan_path, "w") as handle:
            json.dump(plan, handle)
        with open(self.transcript_path, "w") as handle:
            json.dump(transcript, handle)
        manifest = manifest or {"sources": [{
            "id": "raw-1", "duration": 4.0,
            "transcriptPath": os.path.basename(self.transcript_path),
        }]}
        with open(self.manifest_path, "w") as handle:
            json.dump(manifest, handle)

    def _check(self) -> dict:
        return contract.check(self.plan_path, self.tmp.name, self.manifest_path)

    def test_clean_cut_passes_with_hash_bound_seam_receipt(self) -> None:
        verdict = self._check()
        self.assertTrue(verdict["ok"], verdict["errors"])
        receipt = verdict["metrics"]["receipt"]
        self.assertEqual(receipt["cuts"], 2)
        self.assertEqual(receipt["removals"][0]["removedWords"], 1)
        with open(self.plan_path, "rb") as handle:
            raw = handle.read()
        self.assertEqual(receipt["planHash"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(len(receipt["transcriptDigest"]), 64)
        self.assertEqual(receipt["seams"][1]["start"]["after"]["word"], "Restart")

    def test_mid_word_cut_fails_closed(self) -> None:
        plan = _plan()
        plan["cutTrack"][1]["start"] = 2.3
        plan["cutDecisions"]["removals"][0]["end"] = 2.3
        self._write(plan, _transcript())
        verdict = self._check()
        self.assertFalse(verdict["ok"])
        self.assertIn("cuts through word 'Restart'", " ".join(verdict["errors"]))

    def test_cut_source_and_range_must_resolve_to_manifest(self) -> None:
        plan = _plan()
        plan["cutTrack"][0]["sourceId"] = "invented"
        self._write(plan, _transcript())
        self.assertIn("has no transcript authority", " ".join(self._check()["errors"]))
        plan = _plan()
        plan["cutTrack"][1]["end"] = 4.5
        self._write(plan, _transcript())
        self.assertIn("outside source duration", " ".join(self._check()["errors"]))

    def test_backward_and_overlapping_source_ranges_fail(self) -> None:
        plan = _plan()
        plan["cutTrack"][0].update(start=0.5, end=1.1)
        plan["cutTrack"][1].update(start=0.2, end=0.8)
        plan["cutDecisions"]["removals"] = []
        self._write(plan, _transcript())
        errors = " ".join(self._check()["errors"])
        self.assertIn("moves backward", errors)
        self.assertIn("overlaps", errors)

    def test_each_kept_range_requires_rationale(self) -> None:
        plan = _plan()
        plan["cutTrack"][0].pop("rationale")
        self._write(plan, _transcript())
        self.assertIn("why this transcript range is kept",
                      " ".join(self._check()["errors"]))

    def test_adjacent_duplicate_in_kept_output_fails_closed(self) -> None:
        self._write(_single_cut(), _quality_transcript(
            ["Maybe,", "maybe", "this", "works."]))
        verdict = self._check()
        self.assertFalse(verdict["ok"])
        self.assertIn("adjacent duplicate word 'maybe'", " ".join(verdict["errors"]))
        quality = verdict["metrics"]["receipt"]["outputQuality"]
        self.assertEqual(quality["adjacentDuplicates"][0]["word"], "maybe")

    def test_intentional_repeated_emphasis_is_advisory_not_blocking(self) -> None:
        self._write(_single_cut(), _quality_transcript(
            ["This", "is", "very", "very", "useful."]))
        verdict = self._check()
        self.assertTrue(verdict["ok"], verdict["errors"])
        self.assertIn("adjacent duplicate word 'very'", " ".join(verdict["warnings"]))
        quality = verdict["metrics"]["receipt"]["outputQuality"]
        self.assertEqual(quality["adjacentDuplicates"][0]["severity"], "warning")

    def test_incomplete_final_subordinate_fragment_fails_closed(self) -> None:
        self._write(_single_cut(), _quality_transcript(
            ["This", "works,", "because", "most", "people."]))
        verdict = self._check()
        self.assertFalse(verdict["ok"])
        self.assertIn("incomplete final subordinate fragment",
                      " ".join(verdict["errors"]))
        self.assertTrue(verdict["metrics"]["receipt"]["outputQuality"]
                        ["incompleteFinalSubordinate"])

    def test_complete_short_subordinate_clause_is_not_rejected(self) -> None:
        self._write(_single_cut(), _quality_transcript(
            ["This", "works", "because", "it", "helps."]))
        verdict = self._check()
        self.assertTrue(verdict["ok"], verdict["errors"])

    def test_previsual_wall_rejects_retention_lanes(self) -> None:
        plan = _plan()
        plan["graphicsTrack"] = [{"outStart": 0, "outEnd": 2}]
        self._write(plan, _transcript())
        verdict = contract.check(
            self.plan_path, self.tmp.name, self.manifest_path, previsual=True)
        self.assertFalse(verdict["ok"])
        self.assertIn("populated downstream fields", " ".join(verdict["errors"]))
        plan = _plan()
        plan["futureVisualLane"] = [{"enabled": True}]
        self._write(plan, _transcript())
        future = contract.check(
            self.plan_path, self.tmp.name, self.manifest_path, previsual=True)
        self.assertIn("futureVisualLane", " ".join(future["errors"]))
        self.assertEqual(verdict["metrics"]["receipt"]["stage"], "previsual")

    def test_every_removed_gap_requires_exact_decision(self) -> None:
        plan = _plan()
        plan["cutDecisions"]["removals"] = []
        self._write(plan, _transcript())
        self.assertIn("missing cutDecisions.removals rationale/evidence",
                      " ".join(self._check()["errors"]))

    def test_removed_text_must_quote_the_removed_transcript(self) -> None:
        plan = _plan()
        plan["cutDecisions"]["removals"][0]["evidence"]["removedText"] = "invented"
        self._write(plan, _transcript())
        self.assertIn("not a verbatim removed transcript excerpt",
                      " ".join(self._check()["errors"]))

    def test_word_free_gap_must_be_explicit_dead_air(self) -> None:
        self._write(_plan("false_start"), _transcript(False))
        self.assertIn("word-free removal must be kind 'dead_air'",
                      " ".join(self._check()["errors"]))
        plan = _plan("dead_air")
        plan["cutDecisions"]["removals"][0]["evidence"]["removedText"] = ""
        self._write(plan, _transcript(False))
        self.assertTrue(self._check()["ok"], self._check()["errors"])

    def test_unmatched_or_malformed_decision_fails(self) -> None:
        plan = _plan()
        extra = copy.deepcopy(plan["cutDecisions"]["removals"][0])
        extra.update(start=3.6, end=3.8)
        plan["cutDecisions"]["removals"].append(extra)
        self._write(plan, _transcript())
        self.assertIn("does not match an actual inter-cut gap",
                      " ".join(self._check()["errors"]))

    def test_receipt_hashes_change_with_each_bound_authority(self) -> None:
        first = self._check()["metrics"]["receipt"]
        transcript = _transcript()
        transcript["transcript"][0]["words"][0]["word"] = "Hi"
        self._write(_plan(), transcript)
        second = self._check()["metrics"]["receipt"]
        self.assertNotEqual(first["transcriptDigest"], second["transcriptDigest"])
        plan = _plan()
        plan["cutTrack"][0]["rationale"] += " Exactly."
        self._write(plan, transcript)
        third = self._check()["metrics"]["receipt"]
        self.assertNotEqual(second["planHash"], third["planHash"])
        manifest = {"sources": [{"id": "raw-1", "duration": 4.0,
                                  "transcriptPath": "raw.transcript.json"}],
                    "authorityNote": "changed"}
        self._write(plan, transcript, manifest)
        fourth = self._check()["metrics"]["receipt"]
        self.assertNotEqual(third["manifestHash"], fourth["manifestHash"])

    def test_final_gate_binds_controller_previsual_receipt(self) -> None:
        previsual = contract.check(
            self.plan_path, self.tmp.name, self.manifest_path, previsual=True)
        approval_path = os.path.join(self.tmp.name, "cut-approval.json")
        with open(approval_path, "w") as handle:
            json.dump(previsual["metrics"]["receipt"], handle)
        plan = _plan()
        plan["graphicsTrack"] = [{"outStart": 0.0, "outEnd": 2.0}]
        self._write(plan, _transcript())
        final = contract.check(
            self.plan_path, self.tmp.name, self.manifest_path,
            approval_path=approval_path)
        self.assertTrue(final["ok"], final["errors"])
        with open(approval_path, "rb") as handle:
            approval_hash = hashlib.sha256(handle.read()).hexdigest()
        self.assertEqual(final["metrics"]["receipt"]["approvalHash"], approval_hash)
        plan["cutDecisions"]["removals"][0]["rationale"] += " Changed."
        self._write(plan, _transcript())
        changed_decision = contract.check(
            self.plan_path, self.tmp.name, self.manifest_path,
            approval_path=approval_path)
        self.assertFalse(changed_decision["ok"])
        self.assertIn("cutDecisionsDigest changed",
                      " ".join(changed_decision["errors"]))
        plan = _plan()
        plan["graphicsTrack"] = [{"outStart": 0.0, "outEnd": 2.0}]
        plan["cutTrack"][1]["start"] = 2.2
        plan["cutDecisions"]["removals"][0]["end"] = 2.2
        self._write(plan, _transcript())
        changed = contract.check(
            self.plan_path, self.tmp.name, self.manifest_path,
            approval_path=approval_path)
        self.assertFalse(changed["ok"])
        self.assertIn("cutTrackDigest changed", " ".join(changed["errors"]))

    def test_missing_transcript_fails_before_visual_planning(self) -> None:
        manifest = {"sources": [{"id": "raw-1", "duration": 4.0}]}
        self._write(_plan(), _transcript(), manifest)
        errors = " ".join(self._check()["errors"])
        self.assertIn("transcriptPath must resolve", errors)
        self.assertEqual(self._check()["scope"], "transcript_cut")


if __name__ == "__main__":
    unittest.main()

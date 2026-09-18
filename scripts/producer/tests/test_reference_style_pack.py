#!/usr/bin/env python3
"""Tests for meticulous reference review and style-pack release contracts."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

import cv2
import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_PRODUCER = os.path.dirname(_HERE)
sys.path.insert(0, _PRODUCER)

from reference_style_pack_lint import lint  # noqa: E402
from study.reference_review import (build_worklist, canonical_hash,
                                    stable_reference_id)  # noqa: E402
from study.reference_review_media import extract_review_media  # noqa: E402
from study.reference_style_pack import (PackInputs, compile_style_pack,
                                        template_registry_skeleton)  # noqa: E402


def _write_json(path: str, value: dict) -> str:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2)
    return path


def _video(path: str) -> None:
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"),
                             10.0, (320, 180))
    if not writer.isOpened():
        raise RuntimeError("test video writer unavailable")
    for index in range(20):
        frame = np.full((180, 320, 3), (20 + index * 5, 40, 80), np.uint8)
        cv2.putText(frame, str(index), (120, 100), cv2.FONT_HERSHEY_SIMPLEX,
                    1.0, (255, 255, 255), 2)
        writer.write(frame)
    writer.release()


def _deep(video: str) -> dict:
    return {
        "video": video,
        "params": {"fps": 10.0, "meticulous": True, "semantics": False},
        "source": {"width": 320, "height": 180, "fps": 10.0, "durationS": 2.0},
        "signals": {"frameCount": 20}, "unclassifiedRuns": 0,
        "events": [
            {"id": "ev-1", "t": 0.3, "frame": 3, "type": "graphic-in",
             "durationFrames": 3, "bbox": [0.0, 0.0, 0.4, 1.0]},
            {"id": "ev-2", "t": 0.5, "frame": 5, "type": "panel-in",
             "durationFrames": 2, "bbox": [0.0, 0.0, 0.4, 1.0]},
            {"id": "ev-3", "t": 1.8, "frame": 18, "type": "cut",
             "durationFrames": 1, "bbox": None},
        ],
    }


def _classification(item: dict) -> dict[str, str]:
    types = set(item.get("eventTypes") or [])
    if types & {"graphic-in", "panel-in"}:
        return {"kind": "graphic", "informationForm": "comparison",
                "layoutFamily": "beside-presenter", "transitionFamily": "none",
                "animationFamily": "stagger"}
    if "cut" in types:
        return {"kind": "cut", "informationForm": "none",
                "layoutFamily": "none", "transitionFamily": "hard-cut",
                "animationFamily": "step"}
    return {"kind": "stable", "informationForm": "none",
            "layoutFamily": "none", "transitionFamily": "none",
            "animationFamily": "none"}


def _review(worklist: dict, lens: str) -> dict:
    return {
        "schemaVersion": 1, "lens": lens,
        "worklistHash": canonical_hash(worklist),
        "sourceHash": worklist["source"]["sha256"],
        "items": [{"itemId": item["id"], "verdict": "pass",
                   "materialIssues": [], "confidence": 0.95,
                   "classification": _classification(item),
                   "observations": {"lens": lens}}
                  for item in worklist["items"]],
    }


class ReferenceReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.video = os.path.join(self.temp.name, "reference.mp4")
        self.deep_path = os.path.join(self.temp.name, "deep_study.json")
        _video(self.video)
        _write_json(self.deep_path, _deep(self.video))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _prepared(self) -> dict:
        worklist = build_worklist(self.video, self.deep_path)
        return extract_review_media(worklist, os.path.join(self.temp.name, "review"))

    def test_worklist_covers_source_and_extracts_every_event_frame(self) -> None:
        worklist = self._prepared()
        self.assertEqual(worklist["referenceId"], stable_reference_id(self.video))
        self.assertEqual(worklist["coverage"]["uncoveredFrames"], [])
        self.assertEqual(worklist["coverage"]["sourceFrames"], 20)
        self.assertEqual(worklist["items"][0]["eventIds"], ["ev-1", "ev-2"])
        for item in worklist["items"]:
            self.assertTrue(all(os.path.isfile(path) for path in item["contactSheets"]))
            if item["kind"] == "event-window":
                self.assertEqual(item["visualFrameCount"],
                                 item["endFrame"] - item["startFrame"])

    def test_compile_requires_two_agreeing_reviews_and_template_proof(self) -> None:
        worklist = self._prepared()
        worklist_path = _write_json(os.path.join(self.temp.name, "worklist.json"), worklist)
        mechanics = _write_json(os.path.join(self.temp.name, "mechanics.json"),
                                _review(worklist, "mechanics"))
        editorial = _write_json(os.path.join(self.temp.name, "editorial.json"),
                                _review(worklist, "editorial"))
        skeleton = template_registry_skeleton(worklist_path, mechanics, editorial)
        self.assertEqual(len(skeleton["bindings"]), 1)
        self.assertEqual(skeleton["bindings"][0]["status"], "pending")
        graphic = next(item for item in worklist["items"]
                       if _classification(item)["kind"] == "graphic")
        proof = graphic["visualFrames"][0]["path"]
        registry = {"schemaVersion": 1, "worklistHash": canonical_hash(worklist),
                    "bindings": [{"itemId": graphic["id"], "status": "matched",
                                  "templateId": "comparison-bars", "proofPath": proof,
                                  "structureOnly": True}]}
        templates = _write_json(os.path.join(self.temp.name, "templates.json"), registry)
        inputs = PackInputs(worklist_path, mechanics, editorial, templates, self.deep_path)
        pack = compile_style_pack(inputs)
        self.assertTrue(pack["releaseReady"])
        self.assertEqual(pack["releaseClass"], "reference-inspired")
        self.assertFalse(pack["verifiedMimicQualified"])
        self.assertEqual(pack["grammar"]["informationForms"], ["comparison"])
        plan = {"target": {"referenceId": worklist["referenceId"],
                           "referenceStrategy": "mimic"},
                "graphicsTrack": [{"referenceGrammarId": graphic["id"],
                                   "informationForm": "comparison",
                                   "kind": "comparison-bars"}],
                "transitions": [], "punchIns": []}
        verdict = lint(plan, pack, worklist["referenceId"])
        self.assertTrue(verdict["ok"])
        self.assertEqual(
            verdict["metrics"]["releaseClass"], "reference-inspired")
        claimed = {**pack, "releaseClass": "verified-mimic",
                   "verifiedMimicQualified": True}
        self.assertIn(
            "schema v1 style packs cannot claim verified mimic",
            lint(plan, claimed, worklist["referenceId"])["errors"],
        )

    def test_compile_rejects_review_disagreement_without_adjudication(self) -> None:
        worklist = self._prepared()
        worklist_path = _write_json(os.path.join(self.temp.name, "worklist.json"), worklist)
        mechanics_value = _review(worklist, "mechanics")
        editorial_value = _review(worklist, "editorial")
        editorial_value["items"][0]["classification"]["animationFamily"] = "fade"
        mechanics = _write_json(os.path.join(self.temp.name, "mechanics.json"), mechanics_value)
        editorial = _write_json(os.path.join(self.temp.name, "editorial.json"), editorial_value)
        templates = _write_json(os.path.join(self.temp.name, "templates.json"),
                                {"schemaVersion": 1,
                                 "worklistHash": canonical_hash(worklist), "bindings": []})
        inputs = PackInputs(worklist_path, mechanics, editorial, templates, self.deep_path)
        with self.assertRaisesRegex(ValueError, "requires adjudication"):
            compile_style_pack(inputs)


if __name__ == "__main__":
    unittest.main()

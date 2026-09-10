"""Source-bound timing uncertainty must not be resolved by deleting a word."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from transcript_cut_contract import check
from transcript_cut_evidence import _load_words


def _transcript() -> dict:
    """Retain reported C0679 If observations; following words are TEST context."""
    rows = [
        ("If", 0.37, 8.64, 0.3575), ("If", 11.54, 13.62, 0.7),
        ("you", 13.62, 13.85, 0.9), ("run", 13.85, 14.10, 0.9),
        ("content", 14.10, 14.50, 0.9), ("for", 14.50, 14.69, 0.9),
        ("clients.", 14.69, 15.28, 0.9),
    ]
    return {"transcript": [{"start": 0.37, "end": 15.28,
                             "words": [{"word": word, "start": start, "end": end,
                                        "confidence": confidence}
                                       for word, start, end, confidence in rows]}]}


def _plan(start: float) -> dict:
    return {"planVersion": 1, "target": {"mode": "longform", "scope": "produced"},
            "cutTrack": [{"sourceId": "raw-1", "start": start, "end": 15.28,
                          "speed": 1, "rationale": "TEST opening boundary candidate."}],
            "cutDecisions": {"schemaVersion": 1, "removals": []}}


class TimingReviewGateTests(unittest.TestCase):
    """Exercise actual gate I/O without audio, ASR, or admitted-file mutation."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="sniper-word-timing-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.transcript = self.root / "raw.transcript.json"
        self.transcript.write_text(json.dumps(_transcript()))
        self.manifest = self.root / "asset_manifest.json"
        self.manifest.write_text(json.dumps({"sources": [{
            "id": "raw-1", "duration": 16,
            "transcriptPath": self.transcript.name,
        }]}))
        self.plan = self.root / "edit_plan.json"

    def _check(self, start: float) -> dict:
        self.plan.write_text(json.dumps(_plan(start)))
        before = {path: path.read_bytes() for path in
                  (self.plan, self.manifest, self.transcript)}
        verdict = check(str(self.plan), str(self.root), str(self.manifest))
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        return verdict

    def test_exact_first_if_kept_requires_review_and_preserves_duplicate_guard(self) -> None:
        result = self._check(0.37)
        self.assertFalse(result["ok"])
        self.assertIn("adjacent duplicate word 'if'", " ".join(result["errors"]))
        finding = result["metrics"]["receipt"]["outputQuality"]["suspiciousWordSpans"][0]
        self.assertEqual((finding["start"], finding["end"]), (0.37, 8.64))
        self.assertEqual(finding["confidence"], 0.3575)
        self.assertEqual(finding["position"], "kept_opening")

    def test_kept_restart_and_excluded_first_if_both_require_review(self) -> None:
        result = self._check(11.54)
        self.assertFalse(result["ok"])
        rows = result["metrics"]["receipt"]["outputQuality"]["suspiciousWordSpans"]
        self.assertEqual([(row["start"], row["position"]) for row in rows],
                         [(11.54, "kept_opening"), (0.37, "excluded_before_opening")])

    def test_exact_thirteen_sixtytwo_cut_cannot_pass_by_dropping_if(self) -> None:
        result = self._check(13.62)
        self.assertFalse(result["ok"])
        self.assertEqual(sum("opening timing review required" in error for error in result["errors"]), 2)
        quality = result["metrics"]["receipt"]["outputQuality"]
        self.assertEqual([row["start"] for row in quality["suspiciousWordSpans"]], [0.37, 11.54])
        finding = quality["suspiciousWordSpans"][1]
        self.assertEqual((finding["start"], finding["end"]), (11.54, 13.62))
        self.assertEqual(finding["position"], "excluded_before_opening")
        self.assertEqual(quality["forbiddenOpeningStarts"], [])
        self.assertNotIn("requiredStartAtOrAfter", finding)

    def test_confidence_changes_derived_evidence_and_original_file_digest(self) -> None:
        first = self._check(0.37)["metrics"]["receipt"]
        payload = _transcript()
        payload["transcript"][0]["words"][0]["confidence"] = 0.2
        self.transcript.write_text(json.dumps(payload))
        expected = hashlib.sha256(self.transcript.read_bytes()).hexdigest()
        second = self._check(0.37)["metrics"]["receipt"]
        self.assertNotEqual(first["transcriptDigest"], second["transcriptDigest"])
        self.assertEqual(hashlib.sha256(self.transcript.read_bytes()).hexdigest(), expected)
        self.assertEqual(second["outputQuality"]["suspiciousWordSpans"][0]["confidence"], 0.2)


class TimingConfidenceEvidenceTests(unittest.TestCase):
    """Confidence is optional metadata, not a calibrated speech-presence score."""

    def test_loading_preserves_optional_confidence_without_mutating_payload(self) -> None:
        payload = _transcript()
        del payload["transcript"][0]["words"][1]["confidence"]
        before = copy.deepcopy(payload)
        errors: list[str] = []
        words = _load_words(payload, "TEST", errors)
        self.assertEqual(errors, [])
        self.assertEqual(words[0]["confidence"], 0.3575)
        self.assertNotIn("confidence", words[1])
        self.assertEqual(payload, before)

    def test_invalid_confidence_is_not_silently_promoted_or_coerced(self) -> None:
        for value in (True, "0.5", None, float("nan"), float("inf"), -0.1, 1.1, 10**400):
            payload = _transcript()
            payload["transcript"][0]["words"][0]["confidence"] = value
            errors: list[str] = []
            _load_words(payload, "TEST", errors)
            self.assertTrue(any("invalid confidence" in error for error in errors))


if __name__ == "__main__":
    unittest.main(verbosity=2)

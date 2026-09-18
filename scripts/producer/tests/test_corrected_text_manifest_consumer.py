"""TEST ONLY source-faithful text revisions through the existing manifest/cut route."""
from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest.mock import patch

from _corrected_manifest_fixture import CorrectedManifestFixture
from captions.caption_operations import new_caption_track
from captions.caption_plan_pipeline import PlanCaptionContext, compile_plan_caption_track
from captions.caption_words import CaptionFrameRate
from compile_timeline import compile_plan
from transcript_cut_evidence import source_evidence
from transcript_source_authority import bind_result, observe_source, verify_result
import transcript_correction_read as consumer


class CorrectedTextManifestTests(unittest.TestCase):
    """Exercise actual local transactions with conspicuous fake-media attestations."""

    def setUp(self) -> None:
        """Keep the original fixture, replacing only the explicitly proposed class."""
        self.fixture = CorrectedManifestFixture()
        self.addCleanup(self.fixture.close)
        self.fixture.proposed.update(schemaVersion=2, operation="propose-source-word-text-correction",
                                     corrections=[{"sourceWordIndex": 2, "newWord": "You"}])
        self.fixture.commit()
        self.fixture.publish()

    def evidence(self) -> tuple[dict, list[str]]:
        """Read the actual manifest route, not just a correction self-hash."""
        fx = self.fixture
        errors: list[str] = []
        sources, _files = source_evidence(fx.revised(), str(fx.target), str(fx.manifest.parent), {"raw-1"}, errors)
        return sources, errors

    def test_text_revision_reaches_real_cut_words_without_claiming_model_confidence(self) -> None:
        """V2 changes one text token but retains all original word timings."""
        fx = self.fixture
        sources, errors = self.evidence()
        self.assertEqual(errors, [])
        words = sources["raw-1"].words
        self.assertEqual(words[2], {"word": "You", "start": 13.62, "end": 13.85})
        self.assertIn("confidence", words[1])
        corrected = json.loads(Path(fx.committed["revision"]["path"]).read_text())
        self.assertIn("sourceWordCorrectionAuthority", corrected)
        self.assertNotIn("timingCorrectionAuthority", corrected)
        self.assertEqual(fx.originals, {path: path.read_bytes() for path in fx.originals})
        self.assertTrue(fx.publish()["replayed"])

    def test_removing_v2_marker_still_requires_the_committed_text_record(self) -> None:
        """The reserved route cannot revert to digest-only trust for v2 words."""
        fx = self.fixture
        path = Path(fx.committed["revision"]["path"])
        payload = json.loads(path.read_text())
        payload.pop("sourceWordCorrectionAuthority")
        payload.pop("sourceMediaAuthority")
        source = fx.revised()["sources"][0]
        observed = observe_source(fx.media, (source["sourceSha256"], source["sourceSizeBytes"]))
        rebound = bind_result(payload, observed)
        path.write_text(json.dumps(rebound))
        self.assertIsNone(verify_result(rebound, source, str(path)))
        _sources, errors = self.evidence()
        self.assertTrue(any("cannot omit its correction authority" in row for row in errors))

    def test_two_correction_markers_fail_before_expensive_source_read(self) -> None:
        """V1 and v2 markers cannot be combined to select the weaker interpretation."""
        fx = self.fixture
        path = Path(fx.committed["revision"]["path"])
        payload = json.loads(path.read_text())
        payload["timingCorrectionAuthority"] = {}
        with patch.object(consumer, "inspect_current") as inspect:
            error = consumer.correction_error(payload, fx.revised()["sources"][0], str(path), str(fx.target))
            self.assertIn("exactly one correction authority", error)
            inspect.assert_not_called()

    def test_text_decision_corruption_blocks_existing_new_manifest(self) -> None:
        """Successful earlier publication does not authorize stale review records."""
        fx = self.fixture
        record = Path(fx.committed["revision"]["recordPath"])
        record.write_bytes(record.read_bytes() + b" ")
        _sources, errors = self.evidence()
        self.assertTrue(any("correction authority blocked" in row for row in errors))

    def test_committed_text_reaches_both_caption_presets_without_display_replacement(self) -> None:
        """Real pure caption compilation uses corrected source words, not an independent text ledger."""
        fx = self.fixture
        _sources, errors = self.evidence()
        self.assertEqual(errors, [])
        before = {path: path.read_bytes() for path in fx.originals}
        for policy in ("line", "karaoke"):
            plan = json.loads(fx.plan.read_text())
            plan.update(captions={"burn": True}, captionsTrack=new_caption_track(policy))
            context = PlanCaptionContext(plan, fx.revised(), compile_plan(plan),
                                         CaptionFrameRate(24, 1), str(fx.target.parent))
            result = compile_plan_caption_track(context)
            tokens = [token for cue in result["cues"] for token in cue["tokens"]]
            self.assertEqual([row["text"] for row in tokens], ["You", "run", "content", "for", "clients."])
            self.assertEqual(result["coverage"]["suppressedWordIds"], [])
            self.assertEqual(result["coverage"]["omittedWordIds"], [])
            self.assertNotIn("captionCorrectionLedger", plan)
            mode = "line" if policy == "line" else "karaoke-word"
            self.assertTrue(all(cue["mode"] == mode for cue in result["cues"]))
        self.assertEqual(before, {path: path.read_bytes() for path in before})


if __name__ == "__main__":
    unittest.main()

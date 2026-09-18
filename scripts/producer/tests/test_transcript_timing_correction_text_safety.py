"""V2 explicit human lexical authority, real CLI and immutable-store negatives."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from _timing_correction_fixture import TimingCorrectionFixture
from test_transcript_timing_correction_text import text_proposal, text_submission
import transcript_timing_correction_store as store


class TimingCorrectionTextSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = TimingCorrectionFixture()
        self.addCleanup(self.fixture.close)

    def test_repeated_original_text_is_addressed_by_exact_index_not_replace_all(self) -> None:
        parent = json.loads(self.fixture.transcript.read_bytes())
        parent["transcript"][0]["text"] = " ".join(w["word"] for w in parent["transcript"][0]["words"])
        self.fixture.rebind_test_payload(parent)
        text_proposal(self.fixture, "Whether")
        self.fixture.proposed["corrections"][0]["sourceWordIndex"] = 1
        prepared = self.fixture.correct()
        result = self.fixture.correct("record", text_submission(self.fixture, prepared))
        revised = json.loads(Path(result["revision"]["path"]).read_bytes())
        self.assertEqual(revised["transcript"][0]["words"][0], parent["transcript"][0]["words"][0])
        self.assertTrue(revised["transcript"][0]["text"].startswith("If Whether you"))

    def test_both_explicit_comparison_and_source_faithfulness_are_required(self) -> None:
        text_proposal(self.fixture)
        prepared = self.fixture.correct()
        original = text_submission(self.fixture, prepared)
        for key in ("comparedOriginalAndProposedText", "confirmsSourceFaithfulTranscription"):
            sent = copy.deepcopy(original)
            sent["reviews"][0][key] = 1
            with self.assertRaises(RuntimeError):
                self.fixture.correct("record", sent)
            sent["reviews"][0].pop(key)
            with self.assertRaises(RuntimeError):
                self.fixture.correct("record", sent)
        self.assertFalse((self.fixture.correction_root / "record-claim.json").exists())

    def test_unreviewed_new_text_is_rejected_by_exact_reconstruction(self) -> None:
        text_proposal(self.fixture)
        prepared = self.fixture.correct()
        result = self.fixture.correct("record", text_submission(self.fixture, prepared))
        path = Path(result["revision"]["path"])
        payload = json.loads(path.read_bytes())
        payload["transcript"][0]["words"][3]["word"] = "unreviewed"
        path.write_bytes(store._bytes(payload))
        with self.assertRaisesRegex(RuntimeError, "differs from held authority"):
            self.fixture.correct("status")

    def test_text_failure_after_output_stays_fenced_and_cannot_gain_timing_authority(self) -> None:
        text_proposal(self.fixture)
        prepared = self.fixture.correct()
        sent = text_submission(self.fixture, prepared)
        original_write = store.write_new

        def fail_after_output(path: Path, payload: dict) -> None:
            original_write(path, payload)
            if path.name == "corrected-transcript.json":
                raise RuntimeError("TEST text publication deadline failure")

        with patch.object(store, "write_new", side_effect=fail_after_output):
            with self.assertRaisesRegex(RuntimeError, "deadline failure"):
                self.fixture.correct("record", sent)
        failed = json.loads((self.fixture.correction_root / "failure.json").read_bytes())
        self.assertEqual((failed["schemaVersion"], failed["kind"]), (2, "source-word-text-correction-failed"))
        self.assertFalse((self.fixture.correction_root / "commit.json").exists())
        with self.assertRaisesRegex(RuntimeError, "incomplete|fenced"):
            self.fixture.correct("record", sent)

    def test_no_chained_correction_or_multiword_original_is_reinterpreted(self) -> None:
        original = json.loads(self.fixture.transcript.read_bytes())
        for extra in ("timingCorrectionAuthority", "sourceWordCorrectionAuthority"):
            payload = {**original, extra: {"TEST": True}}
            self.fixture.rebind_test_payload(payload)
            text_proposal(self.fixture)
            with self.assertRaisesRegex(RuntimeError, "unsupported"):
                self.fixture.correct()
        original["transcript"][0]["words"][3]["word"] = "New York"
        self.fixture.rebind_test_payload(original)
        text_proposal(self.fixture)
        with self.assertRaisesRegex(RuntimeError, "lexical|whitespace"):
            self.fixture.correct()

    def test_changed_word_aliases_or_unknown_metadata_reject_instead_of_staying_stale(self) -> None:
        parent = json.loads(self.fixture.transcript.read_bytes())
        fields = {"text": "run", "token": "run", "p": .9, "probability": .9,
                  "customEvidence": {"oldText": "run"}, "speaker": {"name": "run"},
                  "id": {"probability": .9}}
        for key, value in fields.items():
            payload = copy.deepcopy(parent)
            payload["transcript"][0]["words"][3][key] = value
            self.fixture.rebind_test_payload(payload)
            text_proposal(self.fixture)
            with patch("transcript_timing_correction.verify_sources") as verify:
                with self.assertRaisesRegex(RuntimeError, "metadata is unsupported"):
                    self.fixture.correct()
                verify.assert_not_called()
            self.assertFalse(self.fixture.correction_root.exists())

    def test_benign_changed_word_identity_and_unaffected_unknown_metadata_are_preserved(self) -> None:
        parent = json.loads(self.fixture.transcript.read_bytes())
        parent["transcript"][0]["words"][3].update(id="word-3", speaker=0)
        parent["transcript"][0]["words"][2]["customEvidence"] = {"original": True}
        self.fixture.rebind_test_payload(parent)
        text_proposal(self.fixture)
        prepared = self.fixture.correct()
        result = self.fixture.correct("record", text_submission(self.fixture, prepared))
        revised = json.loads(Path(result["revision"]["path"]).read_bytes())
        words = revised["transcript"][0]["words"]
        self.assertEqual((words[3]["id"], words[3]["speaker"]), ("word-3", 0))
        self.assertEqual(words[2], parent["transcript"][0]["words"][2])

    def test_actual_standalone_text_cli_uses_explicit_v2_and_returns_no_selection(self) -> None:
        text_proposal(self.fixture, "OpenAI")
        prepared = self.fixture.correct()
        proposed = self.fixture.root / "TEST-text-proposal.json"
        proposed.write_text(json.dumps(self.fixture.proposed))
        sent = self.fixture.root / "TEST-simulated-source-review.json"
        sent.write_text(json.dumps(text_submission(self.fixture, prepared)))
        script = Path(__file__).resolve().parents[1] / "transcript_timing_correction.py"
        command = [sys.executable, str(script), "record", str(self.fixture.plan),
                   str(self.fixture.manifest), str(self.fixture.transcript), str(proposed), str(sent)]
        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        environment.pop("PYTHONPATH", None)
        result = subprocess.run(command, env=environment, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        body = json.loads(result.stdout)
        self.assertEqual(body["request"]["schemaVersion"], 2)
        self.assertEqual(body["state"], "committed")
        self.assertFalse(body["selected"])
        self.assertFalse(body["cutApproved"])


if __name__ == "__main__":
    unittest.main()

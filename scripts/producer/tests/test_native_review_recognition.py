"""Raw recognition remains reusable text while timestamp rejection stays explicit."""
from __future__ import annotations
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from studio import native_review_recognition as recognition
from studio.native_runtime import digest


class NativeReviewRecognitionTests(unittest.TestCase):
    """No recognition or media subprocess is needed for these raw-evidence contracts."""

    def test_collapsed_words_keep_text_without_approving_timestamps(self) -> None:
        """Collapsed words keep text without approving timestamps."""
        raw = {'transcription': [{'text': ' these words are collapsed', 'offsets': {'from': 0, 'to': 10}}]}
        result = recognition.interpret(raw)
        self.assertEqual(result['recognizedText'], 'these words are collapsed')
        self.assertEqual(result['timingQuality']['status'], 'fail')
        self.assertFalse(result['timingApproved'] or result['wordSyncApproved'] or result['humanListeningApproved'])

    def test_passing_timing_policy_still_is_not_acoustic_approval(self) -> None:
        """Passing timing policy still is not acoustic approval."""
        raw = {'transcription': [{'text': ' clear words', 'offsets': {'from': 0, 'to': 1000}}]}
        result = recognition.interpret(raw)
        self.assertEqual(result['timingQuality']['status'], 'pass')
        self.assertFalse(result['timingApproved'] or result['humanListeningApproved'])

    def test_existing_raw_is_reused_without_new_recognition_and_rejects_mutation(self) -> None:
        """Existing raw is reused without new recognition and rejects mutation."""
        root = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp')))
        audio = root / 'audio.m4a'; audio.write_bytes(b'TEST AAC')
        raw = root / 'raw.json'; raw.write_text(json.dumps({'transcription': [{'text': ' collapsed words', 'offsets': {'from': 0, 'to': 10}}]}))
        result = {'audio': str(audio), 'audioSha256': digest(audio), 'raw': str(raw), 'rawSha256': digest(raw),
                  **recognition.interpret(json.loads(raw.read_text()))}
        output = root / 'recognition.json'; output.write_text(json.dumps(result))
        project = root / 'owner-input'; project.mkdir(); request = project / 'request.json'
        request.write_text(json.dumps({'audio': str(audio), 'audioSha256': digest(audio)}))
        pins = {str(request): digest(request)}
        owner = root / 'owner.json'; owner.write_text(json.dumps({'status': recognition.STATUS, 'exitCode': 0,
            'output': str(output), 'cleanup': {'verified': True}, 'leaseCleanupVerified': True,
            'additionalFilePinsBefore': pins, 'additionalFilePinsAfter': pins}))
        receipt = root / 'RECOGNITION-RECEIPT.json'; receipt.write_text(json.dumps({'status': recognition.STATUS,
            'audio': str(audio), 'audioSha256': digest(audio), 'owner': str(owner), 'ownerSha256': digest(owner),
            'result': str(output), 'resultSha256': digest(output)}))
        with mock.patch.object(recognition, '_run_whisper') as run:
            actual = recognition.read_existing(receipt, audio)
        run.assert_not_called(); self.assertEqual(actual['timingQuality']['status'], 'fail')
        raw.write_text('{"changed":true}')
        with self.assertRaises((ValueError, RuntimeError)): recognition.read_existing(receipt, audio)


if __name__ == '__main__': unittest.main()

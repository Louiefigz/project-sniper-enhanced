"""Long-form research can retain all motion while avoiding redundant region OCR."""
from __future__ import annotations

from argparse import Namespace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import Mock, patch

from study import study_deep


class StudyTextScopeTests(TestCase):
    """Scope is explicit in the output; the legacy default still performs all OCR."""

    def test_invalid_scope_cannot_silently_skip_ocr(self) -> None:
        """Programmatic callers must use a supported measurement scope too."""
        with self.assertRaisesRegex(ValueError, "text_scope must be"):
            study_deep._text_pass("TEST", None, ([], {}), Namespace(text_scope="unknown"))

    def test_states_scope_keeps_every_state_and_marks_skipped_measurements(self) -> None:
        """Skipping event OCR must not look like evidence that no graphics exist."""
        states = [{"index": index} for index in range(222)]
        options = Namespace(eff_fps=60, skip_captions=True, text_scope="states")
        with patch.object(study_deep, "require_tesseract"), \
                patch.object(study_deep, "graphics_text") as graphics, \
                patch.object(study_deep, "states_text", return_value=states) as read_states, \
                patch.object(study_deep, "caption_stats") as captions:
            result = study_deep._text_pass("TEST", Mock(), ([], {"states": states}), options)
        graphics.assert_not_called()
        captions.assert_not_called()
        read_states.assert_called_once_with({"states": states})
        self.assertEqual(len(result["states"]), 222)
        self.assertIn("unmeasured", result["graphicsSkipped"])
        self.assertEqual(result["captions"]["skipped"], "--skip-captions")

    def test_legacy_default_preserves_full_ocr_and_caption_passes(self) -> None:
        """An older caller without text_scope keeps the existing behavior."""
        options = Namespace(eff_fps=30, skip_captions=False)
        with patch.object(study_deep, "require_tesseract"), \
                patch.object(study_deep, "graphics_text", return_value=[{"text": "TEST"}]) as graphics, \
                patch.object(study_deep, "states_text", return_value=[]), \
                patch.object(study_deep, "caption_stats", return_value={"detected": True}) as captions:
            result = study_deep._text_pass("TEST", None, ([], {}), options)
        graphics.assert_called_once_with("TEST", None, [], 30)
        captions.assert_called_once_with("TEST", None)
        self.assertNotIn("graphicsSkipped", result)
        self.assertTrue(result["captions"]["detected"])

    def test_states_scope_retains_the_entire_event_sequence_and_word_lock(self) -> None:
        """OCR scope changes neither native-cadence motion nor transcript alignment."""
        events = [{"id": f"event-{i}", "t": i * 0.6} for i in range(1500)]
        info = Mock(width=1920, height=1080, fps=60, duration=900)
        signal = Mock(frames=54000); signal.to_json.return_value = {"TEST": [1, 2]}
        with TemporaryDirectory() as directory, \
                patch.object(study_deep, "probe_video", return_value=info), \
                patch.object(study_deep, "_fingerprint", return_value={}), \
                patch.object(study_deep, "collect_signals", return_value=signal), \
                patch("study.study_cuts.detect_cuts", return_value=[]), \
                patch.object(study_deep, "detect_events", return_value={"events": events, "unclassifiedRuns": 4}), \
                patch.object(study_deep, "_text_pass", return_value={"graphics": [], "captions": {}}), \
                patch.object(study_deep, "load_words", return_value=([], {})), \
                patch.object(study_deep, "word_lock_stats", return_value={"TEST": "retained"}), \
                patch.object(study_deep, "freeze_runs", return_value=[]):
            opts = Namespace(video="TEST", out_dir=directory, meticulous=True, fps=None,
                             semantics=False, transcript=None, text_scope="states")
            study_deep.run_deep(opts)
            saved = json.loads((Path(directory) / "deep_study.json").read_text())
        self.assertEqual(saved["events"], events)
        self.assertEqual(saved["params"]["fps"], 60)
        self.assertEqual(saved["params"]["textScope"], "states")
        self.assertEqual(saved["wordLock"], {"TEST": "retained"})
        self.assertEqual(saved["unclassifiedRuns"], 4)


if __name__ == "__main__":
    main()

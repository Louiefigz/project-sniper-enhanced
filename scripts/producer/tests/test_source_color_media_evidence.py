"""Actual live evidence publication with inert TEST media and selection/native proof leaves."""
from __future__ import annotations

from dataclasses import replace
from contextlib import ExitStack, redirect_stderr
from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from _source_color_batch_fixture import current_batch_test_pins
from _source_color_media_evidence_fixture import SourceColorMediaEvidenceFixture
from cut_preview_io import file_hash, write_new
import guided_source_color_media_evidence as evidence
import guided_opening_media as worker


class SourceColorMediaEvidenceTests(unittest.TestCase):
    """No test result here proves decoded video, listening, color grading or delivery quality."""

    @classmethod
    def setUpClass(cls) -> None:
        """Capture current source pins once; each case owns fresh unrelated TEST artifacts."""
        cls.pins = current_batch_test_pins()

    def setUp(self) -> None:
        """Keep fault writes outside original sources and actual implementation files."""
        self.fixture = SourceColorMediaEvidenceFixture(self.pins)
        self.addCleanup(self.fixture.cleanup)

    def test_actual_hook_returns_publish_exact_detached_source_and_base_refs(self) -> None:
        """Retain real data provenance while explicitly leaving all quality/approval flags false."""
        f = self.fixture
        prepared = f.ready()
        ref = evidence.write_source_color_media_evidence(f.context, prepared, f.root)
        path = Path(ref["path"])
        value = json.loads(path.read_bytes())
        self.assertEqual(file_hash(path), ref["sha256"])
        self.assertEqual(path.stat().st_size, ref["sizeBytes"])
        self.assertEqual(value["receiptHash"], ref["receiptHash"])
        self.assertEqual(value["pictureConsumption"]["basePublication"]["receipt"]["sha256"], f.base_sha)
        self.assertEqual(value["fullProgram"]["base"], prepared.evidence["base"])
        self.assertEqual([row["sourceId"] for row in value["observations"]["sources"]], ["raw-b", "raw-a"])
        self.assertTrue(all(value[key] is False for key in ("gamutMeasured", "gradeApplied", "colorQualified", "openingApproved", "deliveryApproved")))
        evidence.verify_source_color_media_evidence(f.context, ref)

    def test_missing_consumption_cannot_publish_from_source_observations_alone(self) -> None:
        """A context/metadata holder without actual base hooks is not a finished edit."""
        f = self.fixture
        from guided_opening_prepare import OpeningPreparation
        prepared = OpeningPreparation(f.base_path, object(), {})
        self.assertRaisesRegex(RuntimeError, "incomplete", evidence.write_source_color_media_evidence, f.context, prepared, f.root)
        self.assertFalse((f.root / evidence.EVIDENCE_NAME).exists())

    def _finish_worker(self, source_color: bool) -> tuple[dict, dict]:
        """Run actual shared finish/publication with explicit TEST AV/selection/native leaves."""
        f = self.fixture
        prepared = f.ready()
        prepared = replace(prepared, selection=SimpleNamespace(master=SimpleNamespace(source_bus=f.live.ctx.source_audio_bus)))
        audio_root = f.root / "audio"
        audio_root.mkdir(mode=0o700)
        write_new(audio_root / "audio-result.json", {"TEST": "not an audio qualification"})
        values = {"_audio": {"receiptHash": "a" * 64}, "screen_context": None,
            "render_opening_graphics": {"clips": [], "evidence": []}, "compose_ranges": {}, "mux_ranges": {},
            "_unchanged": None}
        with ExitStack() as stack:
            stack.enter_context(redirect_stderr(StringIO()))
            for name, value in values.items():
                stack.enter_context(patch.object(worker, name, return_value=value))
            result = worker._finish_execution(f.source.inputs, f.root, f.source.clock,
                (f.source.opening, {"TEST": "pipeline not independently qualified"}, [], prepared,
                 f.context if source_color else None))
        media_path = Path(result["receiptPath"])
        return result, json.loads(media_path.read_bytes())

    def test_worker_schema2_completion_binds_actual_source_color_section(self) -> None:
        """Exercise real schema2 receipt/completion publication, not native media qualification."""
        f = self.fixture
        result, media_record = self._finish_worker(True)
        self.assertEqual(result["schemaVersion"], 2)
        self.assertEqual(media_record["schemaVersion"], 2)
        self.assertEqual(media_record["sourceColorEvidence"], result["sourceColorEvidence"])
        self.assertEqual(file_hash(Path(result["receiptPath"])), result["receiptSha256"])
        self.assertEqual(media_record["receiptHash"], result["receiptHash"])
        self.assertFalse(result["openingApproved"])
        self.assertFalse(result["deliveryApproved"])
        evidence.verify_source_color_media_evidence(f.context, result["sourceColorEvidence"])

    def test_worker_without_source_context_keeps_schema1_and_never_calls_color_writer(self) -> None:
        """The real no-source finish path retains legacy output; AV/selection leaves are TEST stubs."""
        with patch.object(worker, "write_source_color_media_evidence") as writer, \
                patch.object(worker, "verify_source_color_media_evidence") as verifier:
            result, media_record = self._finish_worker(False)
        writer.assert_not_called()
        verifier.assert_not_called()
        self.assertEqual(result["schemaVersion"], 1)
        self.assertEqual(media_record["schemaVersion"], 1)
        self.assertNotIn("sourceColorEvidence", result)
        self.assertNotIn("sourceColorEvidence", media_record)
        self.assertFalse((self.fixture.root / evidence.EVIDENCE_NAME).exists())
        self.assertEqual(file_hash(Path(result["receiptPath"])), result["receiptSha256"])
        self.assertEqual(media_record["receiptHash"], result["receiptHash"])
        self.assertFalse(result["openingApproved"])
        self.assertFalse(result["deliveryApproved"])

    def test_preexisting_evidence_is_never_overwritten(self) -> None:
        """A second publication does not turn an earlier artifact into a new result."""
        f, sentinel = self.fixture, b"TEST existing output must survive"
        prepared = f.ready()
        path = f.root / evidence.EVIDENCE_NAME
        path.write_bytes(sentinel)
        self.assertRaises(FileExistsError, evidence.write_source_color_media_evidence, f.context, prepared, f.root)
        self.assertEqual(path.read_bytes(), sentinel)

    def test_foreign_preparation_output_refuses_before_artifact_reads(self) -> None:
        """Equal metadata cannot redirect the same live context outside its claim output."""
        f = self.fixture
        prepared = replace(f.ready(), base=Path("/TEST-unopened/foreign/final.mp4"))
        with patch.object(evidence, "held_ref") as reader:
            self.assertRaisesRegex(RuntimeError, "output ownership", evidence.write_source_color_media_evidence, f.context, prepared, f.root)
        reader.assert_not_called()

    def test_publisher_byte_substitution_is_not_a_successful_ref(self) -> None:
        """Mutate only the newly created exact TEST evidence file after the real writer returns."""
        f = self.fixture
        prepared, original = f.ready(), evidence.write_new

        def changed(path: Path, value: dict) -> None:
            """Do not write to a source, dependency, alternate directory or unknown target."""
            original(path, value)
            f.change(path, b"TEST substituted evidence")

        with patch.object(evidence, "write_new", side_effect=changed):
            self.assertRaisesRegex(RuntimeError, "publication bytes changed", evidence.write_source_color_media_evidence,
                                   f.context, prepared, f.root)

    def test_postwrite_original_deadline_expiry_retains_unselectable_file_not_success(self) -> None:
        """No new clock or success result is granted after an original publication deadline."""
        f = self.fixture
        prepared, original = f.ready(), evidence.write_new

        def expired(path: Path, value: dict) -> None:
            """Advance only the inherited virtual TEST clock after its real publication."""
            original(path, value)
            f.source.now = f.source.clock.end

        with patch.object(evidence, "write_new", side_effect=expired):
            self.assertRaisesRegex(RuntimeError, "deadline|time budget", evidence.write_source_color_media_evidence,
                                   f.context, prepared, f.root)
        self.assertTrue((f.root / evidence.EVIDENCE_NAME).is_file())


if __name__ == "__main__":
    unittest.main()

"""Candidate-bound automated QC uses real FFmpeg and fails closed."""
from __future__ import annotations

import json
import os
import shutil
import unittest
from unittest import mock

from edit.cut_repair_candidate_qc import run_candidate_qc
from edit.cut_repair_candidate_qc_bundle import load_automated_qc_bundle
from edit.cut_repair_candidate_qc_pin import PinRequest, pin_tool_manifest
from edit.cut_repair_candidate_qc_tools import (
    approved_visual_oracle_files,
    load_qc_tools,
    reobserve_tools,
)
from edit.cut_repair_candidate_qc_types import CandidateQcContractError
from edit.cut_repair_context_sources import stable_file_digest
from tests._p2_candidate_qc_fixture import CandidateQcFixture
from tests._p2_candidate_qc_options import CandidateQcOptions


class CutRepairCandidateQcTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CandidateQcFixture()

    def tearDown(self) -> None:
        self.fixture.clean()

    def _run(self) -> dict:
        return run_candidate_qc(
            self.fixture.producer,
            self.fixture.preparation_hash,
            self.fixture.tool_manifest_path)

    def test_real_ffmpeg_candidate_produces_four_bound_receipts(self) -> None:
        result = self._run()
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "automated-qc-passed")
        with open(result["manifestPath"], encoding="utf-8") as stream:
            manifest = json.load(stream)
        self.assertFalse(manifest["operatorAuditionProduced"])
        self.assertEqual(
            set(manifest["lanes"]),
            {"alignment", "vad", "retranscription", "seam"})
        for lane in manifest["lanes"].values():
            self.assertEqual(lane["status"], "bounded-pass")
            self.assertEqual(len(lane["receiptHash"]), 64)
            self.assertTrue(os.path.isfile(lane["receiptPath"]))
        self.assertFalse(os.path.exists(os.path.join(
            result["qcDirectory"], "audition.json")))
        alignment = result["alignment"]["receipt"]
        self.assertEqual(
            alignment["alignmentProtocol"],
            "deterministic-source-waveform-v1")
        self.assertEqual(
            alignment["evidenceSemantics"],
            "transcript-bound-source-waveform-presence-not-audibility")
        self.assertEqual(
            alignment["sourceMediaSha256"], self.fixture.source_hash)
        self.assertGreaterEqual(
            alignment["bestScorePpm"], alignment["minimumScorePpm"])
        for lane in ("alignment", "vad", "retranscription", "seam"):
            self.assertEqual(set(result[lane]), {
                "status", "receiptHash",
                "candidateCompositeSha256", "receipt"})
            self.assertEqual(
                result[lane]["candidateCompositeSha256"],
                self.fixture.candidate_hash)
        reopened, value_hash, value_path = load_automated_qc_bundle(
            self.fixture.producer, self.fixture.preparation_hash)
        self.assertEqual(value_hash, result["automatedQcBundleHash"])
        self.assertEqual(value_path, result["automatedQcBundlePath"])
        self.assertEqual(reopened["alignment"], result["alignment"])

    def test_same_authority_replays_same_immutable_manifest(self) -> None:
        first = self._run()
        second = self._run()
        self.assertEqual(first["manifestHash"], second["manifestHash"])
        self.assertEqual(first["manifestPath"], second["manifestPath"])

    def test_absent_independent_aligner_is_precise_blocker(self) -> None:
        self.fixture.clean()
        self.fixture = CandidateQcFixture(
            CandidateQcOptions(aligner=False))
        result = self._run()
        self.assertFalse(result["ok"])
        self.assertEqual(
            result["blockers"]["alignment"]["code"],
            "INDEPENDENT_ALIGNMENT_TOOL_UNAVAILABLE")
        self.assertNotIn("retranscription", result["blockers"])
        self.assertFalse(os.path.exists(os.path.join(
            result["qcDirectory"], "alignment.json")))

    def test_ambiguous_bounded_retranscription_fails_closed(self) -> None:
        self.fixture.clean()
        self.fixture = CandidateQcFixture(
            CandidateQcOptions(
                whisper_text="restore this phrase restore this phrase"))
        result = self._run()
        self.assertEqual(
            result["blockers"]["retranscription"]["code"],
            "RETRANSCRIPTION_TARGET_AMBIGUOUS")
        self.assertFalse(os.path.exists(os.path.join(
            result["qcDirectory"], "retranscription.json")))

    def test_ambiguous_alignment_fails_closed(self) -> None:
        self.fixture.clean()
        self.fixture = CandidateQcFixture(
            CandidateQcOptions(duplicate_alignment=True))
        result = self._run()
        self.assertEqual(
            result["blockers"]["alignment"]["code"],
            "ALIGNMENT_BOUNDARY_NOT_UNIQUE")

    def test_44100_source_span_is_resampled_and_located_once(self) -> None:
        self.fixture.clean()
        self.fixture = CandidateQcFixture(
            CandidateQcOptions(source_rate=44_100))
        result = self._run()
        self.assertTrue(result["ok"])
        receipt = result["alignment"]["receipt"]
        self.assertEqual(receipt["observedOccurrenceCount"], 1)
        self.assertEqual(receipt["referenceSampleCount"], 24_000)

    def test_phase_demo_early_middle_late_real_candidates(self) -> None:
        cases = (
            ("early", 12_000, 0),
            ("middle", 48_000, 30),
            ("late", 156_000, 90),
        )
        for label, source_start, dirty_start in cases:
            with self.subTest(position=label):
                self.fixture.clean()
                self.fixture = CandidateQcFixture(
                    CandidateQcOptions(
                        target_start_sample=source_start,
                        dirty_start_frame=dirty_start))
                result = self._run()
                self.assertTrue(result["ok"])
                self.assertEqual(
                    result["alignment"]["receipt"]
                    ["observedOccurrenceCount"], 1)

    def test_source_media_tamper_is_rejected_before_alignment(self) -> None:
        with open(self.fixture.source_path, "ab") as stream:
            stream.write(b"tamper")
        with self.assertRaisesRegex(
                CandidateQcContractError, "source media bytes are stale"):
            self._run()

    def test_weakened_or_foreign_alignment_policy_cannot_be_pinned(self) -> None:
        copied_policy = os.path.join(
            self.fixture.tools_dir, "weakened-policy.json")
        shutil.copyfile(self.fixture.aligner_policy, copied_policy)
        with open(copied_policy, "w", encoding="utf-8") as stream:
            json.dump({
                "schemaVersion": 1,
                "kind": "cut-repair-source-waveform-alignment-policy",
                "frameSamples": 480, "hopSamples": 240,
                "minimumScorePpm": 0,
                "peakSeparationRatioPpm": 1,
                "maximumObservationSamples": 1_440_000,
            }, stream)
        request = PinRequest(
            os.path.realpath(shutil.which("ffmpeg") or ""),
            self.fixture.whisper_path,
            self.fixture.whisper_model,
            self.fixture.aligner_runtime,
            self.fixture.aligner_implementation,
            copied_policy,
            self.fixture.visual_runtime,
            self.fixture.visual_implementation,
            self.fixture.visual_policy,
        )
        with self.assertRaisesRegex(
                ValueError, "repository-approved"):
            pin_tool_manifest(os.path.join(
                self.fixture.producer, "foreign-tools.json"), request)

    def test_candidate_byte_tamper_is_rejected_before_ffmpeg(self) -> None:
        with open(self.fixture.candidate_path, "ab") as stream:
            stream.write(b"tamper")
        with self.assertRaisesRegex(
                CandidateQcContractError, "candidate bytes are stale"):
            self._run()

    def test_pinned_tool_drift_is_rejected(self) -> None:
        with open(self.fixture.whisper_path, "ab") as stream:
            stream.write(b"\n# drift\n")
        with self.assertRaisesRegex(
                CandidateQcContractError, "TOOL_DRIFT"):
            self._run()

    def test_visual_dependency_drift_fails_terminal_reobservation(self) -> None:
        tools = load_qc_tools(
            self.fixture.producer, self.fixture.tool_manifest_path)
        media_path = approved_visual_oracle_files()[1][1]

        def observed(path: str, label: str) -> str:
            if path == media_path:
                return "0" * 64
            return stable_file_digest(path, label)

        with mock.patch(
                "edit.cut_repair_candidate_qc_tools.stable_file_digest",
                side_effect=observed):
            with self.assertRaisesRegex(
                    CandidateQcContractError, "TOOL_DRIFT_DURING_QC"):
                reobserve_tools(tools)

    def test_visual_adapter_drift_fails_terminal_reobservation(self) -> None:
        tools = load_qc_tools(
            self.fixture.producer, self.fixture.tool_manifest_path)
        adapter_path = dict(
            approved_visual_oracle_files())["candidate-qc-visual-adapter"]

        def observed(path: str, label: str) -> str:
            if path == adapter_path:
                return "0" * 64
            return stable_file_digest(path, label)

        with mock.patch(
                "edit.cut_repair_candidate_qc_tools.stable_file_digest",
                side_effect=observed):
            with self.assertRaisesRegex(
                    CandidateQcContractError, "TOOL_DRIFT_DURING_QC"):
                reobserve_tools(tools)

    def test_visual_choice_scope_and_value_type_drift_are_closed(self) -> None:
        tools = load_qc_tools(
            self.fixture.producer, self.fixture.tool_manifest_path)
        oracle = tools.visual_oracle
        self.assertIsNotNone(oracle)
        assert oracle is not None
        self.assertEqual(
            oracle.implementation_scope,
            "visual-choice-seam-repository-code-v1")
        self.assertEqual(oracle.implementation_nonclaims, (
            "audio-seam-measurement",
            "candidate-qc-orchestration-storage-or-promotion",
            "python-stdlib-os-dylibs",
        ))
        types_path = dict(
            approved_visual_oracle_files())["candidate-qc-value-types"]

        def observed(path: str, label: str) -> str:
            return "0" * 64 if path == types_path \
                else stable_file_digest(path, label)

        with mock.patch(
                "edit.cut_repair_candidate_qc_tools.stable_file_digest",
                side_effect=observed):
            with self.assertRaisesRegex(
                    CandidateQcContractError, "TOOL_DRIFT_DURING_QC"):
                reobserve_tools(tools)

    def test_symlinked_receipt_replay_is_rejected(self) -> None:
        result = self._run()
        vad_path = os.path.join(result["qcDirectory"], "vad.json")
        os.unlink(vad_path)
        os.symlink(os.path.join(
            result["qcDirectory"], "alignment.json"), vad_path)
        with self.assertRaisesRegex(
                CandidateQcContractError, "private regular file"):
            self._run()

    def test_content_addressed_bundle_tamper_is_rejected(self) -> None:
        result = self._run()
        with open(result["automatedQcBundlePath"], "ab") as stream:
            stream.write(b"tamper")
        with self.assertRaisesRegex(
                CandidateQcContractError, "unreadable or stale|digest is stale"):
            load_automated_qc_bundle(
                self.fixture.producer, self.fixture.preparation_hash)


if __name__ == "__main__":
    unittest.main(verbosity=2)

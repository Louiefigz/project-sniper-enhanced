"""Policy and tamper tests for cadence-approximation approvals."""
from __future__ import annotations

import copy
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from headless.external_media_snapshot import MAX_EXTERNAL_MEDIA_BYTES
from ingest_admission_contract import canonical_bytes
from qualification_cadence_approval import (
    build_cadence_approval,
    publish_cadence_approval,
    verify_cadence_approval,
)
from qualification_mezzanine import (
    QualificationRequest,
    QualificationRunners,
    build_qualification_mezzanine,
)
from qualification_mezzanine_fixture import envelope, source_fact


class CadenceApprovalTests(unittest.TestCase):
    def _qualification(self, root: Path) -> tuple[dict, Path, Path]:
        source = root / "source.mp4"
        output = root / "qualified.mp4"
        evidence_path = root / "qualification.json"
        source.write_bytes(b"host-hash-only")
        request = QualificationRequest(
            str(source), str(output), str(evidence_path), 10800, 24)

        def observe(path: str):
            return source_fact(path)

        def transcode(_source: str, target: str, _timeout: int, _fps: int):
            payload = b"qualified-media"
            (Path(target) / "qualified.mp4").write_bytes(payload)
            return envelope(MAX_EXTERNAL_MEDIA_BYTES + 1, len(payload))

        document = build_qualification_mezzanine(
            request, QualificationRunners(observe, transcode))
        return document, evidence_path, output

    def test_approval_binds_actual_map_clocks_tools_and_time_authority(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _, evidence_path, output = self._qualification(root)
            approval_path = root / "cadence-approval.json"
            document = publish_cadence_approval(
                str(evidence_path), str(approval_path))
            mapping = document["frameMapping"]
            self.assertEqual(document["decision"],
                             "policy-approved-approximation")
            self.assertFalse(document["approvedBy"]["humanApprovalClaimed"])
            self.assertEqual(document["media"]["source"]["rate"],
                             "24000/1001")
            self.assertEqual(
                document["media"]["normalized"]["video"]["rate"], "24/1")
            self.assertEqual(len(mapping["duplicateTargetFrameIndices"]), 20)
            self.assertEqual(mapping["droppedSourceFrameIndices"], [])
            self.assertFalse(mapping["interpolation"])
            self.assertEqual(document["duration"][
                "durationDeltaRationalSeconds"], "-1/6000")
            self.assertEqual(
                document["audioClock"]["source"][
                    "timelineSamplesPerChannel"], 40048080)
            self.assertEqual(
                document["audioClock"]["normalized"][
                    "timelineSamplesPerChannel"], 40048032)
            self.assertEqual(
                document["audioClock"]["normalized"][
                    "silentTailSamplesPerChannel"], 32)
            self.assertEqual(
                document["audioClock"]["source"]["timelineSamplesPerChannel"]
                - document["audioClock"]["normalized"][
                    "programSamplesPerChannel"],
                80,
            )
            self.assertAlmostEqual(
                document["audioClock"]["source"][
                    "videoDurationDeltaSeconds"],
                0.0015,
            )
            self.assertTrue(document["audioClock"][
                "absoluteDeltasWithinOneSourceFrame"])
            authority = document["downstreamTimeAuthority"]
            self.assertEqual(authority["mediaPath"], str(output))
            self.assertTrue(authority["transcriptAndCutsMustBindThisAsset"])
            self.assertEqual(
                stat.S_IMODE(os.stat(approval_path).st_mode), 0o400)
            self.assertEqual(
                verify_cadence_approval(str(approval_path)), document)

    def test_receipt_or_media_tampering_fails_closed(self) -> None:
        for target in ("receipt", "media"):
            with self.subTest(target=target), \
                    tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                _, evidence_path, output = self._qualification(root)
                approval_path = root / "cadence-approval.json"
                publish_cadence_approval(
                    str(evidence_path), str(approval_path))
                path = approval_path if target == "receipt" else output
                os.chmod(path, 0o600)
                if target == "receipt":
                    value = json.loads(path.read_bytes())
                    value["frameMapping"]["duplicateTargetFrameIndices"][0] += 1
                    path.write_bytes(canonical_bytes(value))
                else:
                    path.write_bytes(b"tampered-media")
                with self.assertRaises(RuntimeError):
                    verify_cadence_approval(str(approval_path))

    def test_unsupported_pair_delta_and_interpolation_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            document, evidence_path, _ = self._qualification(Path(raw))
            cases = (
                "pair", "delta", "interpolation",
                "audio-filter-missing", "audio-filter-tampered",
            )
            for case in cases:
                candidate = copy.deepcopy(document)
                cadence = candidate["execution"]["cadenceDecision"]
                if case == "pair":
                    cadence["targetRate"] = "30/1"
                elif case == "delta":
                    cadence["targetFrames"] += 2
                elif case == "interpolation":
                    candidate["execution"]["ffmpegArgv"].insert(
                        -1, "minterpolate=fps=24")
                if case.startswith("audio-filter"):
                    argv = candidate["execution"]["ffmpegArgv"]
                    index = argv.index("-af")
                    if case.endswith("missing"):
                        del argv[index:index + 2]
                    else:
                        argv[index + 1] += ",anull"
                with self.subTest(case=case), patch(
                        "qualification_cadence_approval."
                        "verify_qualification_evidence",
                        return_value=candidate), self.assertRaises(RuntimeError):
                    build_cadence_approval(str(evidence_path))

    def test_publish_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _, evidence_path, _ = self._qualification(root)
            approval_path = root / "cadence-approval.json"
            publish_cadence_approval(str(evidence_path), str(approval_path))
            with self.assertRaisesRegex(RuntimeError, "new JSON"):
                publish_cadence_approval(
                    str(evidence_path), str(approval_path))


if __name__ == "__main__":
    unittest.main()

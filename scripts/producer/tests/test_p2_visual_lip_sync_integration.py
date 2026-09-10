"""Visual proof is inseparable from the passed picture-dirty seam lane."""
from __future__ import annotations

import copy
import types
import unittest

from edit.cut_repair_candidate_qc_bundle import _validate_seam_authority
from edit.cut_repair_candidate_qc_types import CandidateQcContractError
from edit.cut_repair_candidate_qc_receipts import seam_lane
from edit.cut_repair_candidate_qc_store import ReceiptStore
from edit.cut_repair_candidate_qc_visual import visual_observation
from edit.cut_repair_context_sources import digest
from edit.cut_repair_promotion_candidate import (
    PromotionCandidate,
    _visual_binding,
)
from edit.cut_repair_promotion_gate import (
    PromotionGateError,
    _assert_visual_binding,
)
from edit.cut_repair_visual_lip_sync_contract import validate_visual_seam
from tests._p2_visual_lip_sync_fixture import (
    FFMPEG,
    VisualLipSyncFixture,
)


def _waveform(run) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        runtime_sha256=run.tools.ffmpeg.sha256,
        click_free=True,
        duplicate_free=True,
        room_tone_continuous=True,
    )


@unittest.skipUnless(FFMPEG, "ffmpeg required")
class VisualLipSyncIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = VisualLipSyncFixture()

    def tearDown(self) -> None:
        self.fixture.clean()

    def test_picture_seam_embeds_exact_governed_visual_proof(self) -> None:
        run = self.fixture.qc_run()
        observed = visual_observation(run)
        lane = seam_lane(
            run, _waveform(run), ReceiptStore(run), observed)
        self.assertEqual(lane["status"], "bounded-pass")
        receipt = lane["_receipt"]
        self.assertEqual(receipt["lipSyncDisposition"], "passed")
        self.assertEqual(
            receipt["alternateTakeSelectionReceiptHash"], "3" * 64)
        self.assertEqual(
            receipt["sourceFrameRange"],
            receipt["visualOracleReceipt"]["sourceFrameRange"])
        self.assertEqual(
            receipt["outputSampleRange"],
            receipt["visualOracleReceipt"]["outputSampleRange"])
        validate_visual_seam(
            receipt,
            run.authority.descriptor["operationHash"],
            run.authority.candidate_sha256,
        )

    def test_delayed_candidate_blocks_the_published_seam_lane(self) -> None:
        run = self.fixture.qc_run("delayed")
        observed = visual_observation(run)
        lane = seam_lane(
            run, _waveform(run), ReceiptStore(run), observed)
        self.assertEqual(lane["status"], "blocked")
        self.assertEqual(
            lane["blocker"]["code"], "VISIBLE_SPEECH_AV_OFFSET")
        self.assertNotIn("_receipt", lane)

    def test_missing_pinned_visual_tool_blocks_picture_seam(self) -> None:
        run = self.fixture.qc_run(visual_tool=False)
        observed = visual_observation(run)
        lane = seam_lane(
            run, _waveform(run), ReceiptStore(run), observed)
        self.assertEqual(lane["status"], "blocked")
        self.assertEqual(
            lane["blocker"]["code"], "LIP_SYNC_ORACLE_UNAVAILABLE")

    def test_picture_bundle_cannot_claim_audio_only_disposition(self) -> None:
        run = self.fixture.qc_run()
        observed = visual_observation(run)
        receipt = seam_lane(
            run, _waveform(run), ReceiptStore(run), observed)["_receipt"]
        bypass = copy.deepcopy(receipt)
        bypass["lipSyncDisposition"] = "not-applicable-audio-only"
        with self.assertRaisesRegex(
                CandidateQcContractError, "contradicts repair picture"):
            _validate_seam_authority(run.authority, bypass)

    def test_picture_bundle_binds_authoritative_take_selection(self) -> None:
        run = self.fixture.qc_run()
        observed = visual_observation(run)
        receipt = seam_lane(
            run, _waveform(run), ReceiptStore(run), observed)["_receipt"]
        bypass = copy.deepcopy(receipt)
        bypass["alternateTakeSelectionReceiptHash"] = "f" * 64
        with self.assertRaisesRegex(
                CandidateQcContractError, "another alternate-take"):
            _validate_seam_authority(run.authority, bypass)

    def test_promotion_gate_binds_nested_visual_selection_fields(self) -> None:
        run = self.fixture.qc_run()
        receipt = seam_lane(
            run, _waveform(run), ReceiptStore(run),
            visual_observation(run))["_receipt"]
        candidate = PromotionCandidate(
            run.authority.descriptor["operationHash"],
            run.authority.candidate_sha256,
            self.fixture.root,
            True,
            run.authority.alternate_take_selection_hash,
            _visual_binding(run.authority),
        )
        bypass = copy.deepcopy(receipt)
        bypass["visualOracleReceipt"]["selectionHash"] = "f" * 64
        bypass["visualOracleReceiptHash"] = digest(
            bypass["visualOracleReceipt"])
        with self.assertRaisesRegex(
                PromotionGateError, "contradicts alternate-take authority"):
            _assert_visual_binding(bypass, candidate)


if __name__ == "__main__":
    unittest.main(verbosity=2)

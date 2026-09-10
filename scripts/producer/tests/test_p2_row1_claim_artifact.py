"""Freshness and claim-shape gate for retained P2 row-one evidence."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from current_render_graph_contract import file_hash
from edit.picture_lock_common import content_hash
from tests.live_p2_row1_acceptance import CLOSURE, REPO

ARTIFACT = REPO / (
    "docs/producer/command-driven-editing/contracts/"
    "p2-row1-claim-cohort-v1.json")
RATES = (
    "24000/1001", "24/1", "25/1", "30000/1001",
    "30/1", "50/1", "60000/1001", "60/1",
)
POSITIONS = ("early", "middle", "late")
ASSERTIONS = {
    "candidateProved", "positionBound", "normalizedVfr",
    "distinctMediaInputs", "multiSourceAuthority", "captionRefit",
    "oneCaptionCueChanged", "oneCaptionCueUnchanged",
    "captionContentReused", "generalJResolved", "generalLResolved",
    "dialogueCaptionsCompiled", "localMasterFramesExact",
    "terminalPcmExact", "outsidePicturePreserved",
    "outsidePcmPreserved", "palmierNativeUnsupported",
    "palmierBakedExact", "palmierNotSampleExact",
    "palmierReadbackFailClosed", "invariantHashesBound",
    "totalFramesPreserved",
}


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [
            text for child in value.values() for text in _strings(child)]
    if isinstance(value, list):
        return [text for child in value for text in _strings(child)]
    return []


def _without_hash(value: dict) -> dict:
    return {key: item for key, item in value.items()
            if key != "receiptHash"}


class P2RowOneClaimArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.value = json.loads(ARTIFACT.read_text(encoding="utf-8"))

    def test_receipt_is_fresh_self_hashed_and_path_free(self) -> None:
        value = self.value
        self.assertEqual(set(value), {
            "schemaVersion", "kind", "cohortId", "generatedAt",
            "execution", "elapsedSeconds", "sourceClosure", "toolchain",
            "coverage", "cases", "nativeSubsetControl", "nonClaims",
            "passed", "receiptHash",
        })
        self.assertEqual(value["kind"], "p2-row1-claim-cohort")
        self.assertTrue(value["passed"])
        self.assertEqual(
            value["receiptHash"], content_hash(_without_hash(value)))
        expected_closure = {
            name: file_hash(REPO / name) for name in CLOSURE}
        self.assertEqual(value["sourceClosure"], expected_closure)
        self.assertGreaterEqual(len(expected_closure), 25)
        for row in value["toolchain"].values():
            self.assertEqual(row["sha256"], file_hash(Path(row["path"])))
        strings = _strings(value)
        self.assertFalse(any(
            "sniper-p2-row1-" in text
            or ".sniper-repair-" in text
            or ".sniper-repair-composite-" in text
            for text in strings))

    def test_cross_product_is_complete_without_duplicate_cells(self) -> None:
        coverage = self.value["coverage"]
        self.assertEqual(coverage["expectedCaseCount"], 24)
        self.assertEqual(coverage["actualCaseCount"], 24)
        self.assertEqual(coverage["rateTokens"], list(RATES))
        self.assertEqual(coverage["positions"], list(POSITIONS))
        self.assertTrue(coverage["uniqueCaseIdentities"])
        self.assertTrue(coverage["crossProductComplete"])
        self.assertTrue(coverage["allCaseAssertionsPassed"])
        for token in RATES:
            self.assertEqual(
                coverage["positionsByRate"][token], sorted(POSITIONS))
        for key in (
                "normalizedVfrCaseCount", "captionRefitCaseCount",
                "generalJlCaseCount", "palmierFailClosedCaseCount"):
            self.assertEqual(coverage[key], 24)
        expected = {
            f"p2-row1-{token.replace('/', '-')}-{position}"
            for token in RATES for position in POSITIONS
        }
        self.assertEqual(
            {row["caseId"] for row in self.value["cases"]}, expected)

    def test_every_cell_executes_every_claim_dimension(self) -> None:
        for row in self.value["cases"]:
            with self.subTest(case=row["caseId"]):
                self._assert_case(row)

    def _assert_case(self, row: dict) -> None:
        self.assertEqual(row["fixtureId"],
                         "p2-row1-real-vfr-multisource-caption-jl-v1")
        self.assertEqual(
            row["receiptHash"], content_hash(_without_hash(row)))
        self.assertEqual(set(row["assertions"]), ASSERTIONS)
        self.assertTrue(all(row["assertions"].values()))
        self.assertTrue(row["passed"])
        self._assert_position(row)
        self._assert_media(row["media"])
        self._assert_captions(row["captions"])
        self._assert_dialogue(row["dialogue"])
        self._assert_palmier(row["palmier"])
        self.assertTrue(row["invariants"]["hashesBound"])
        self.assertTrue(
            row["invariants"]["totalOutputFramesPreserved"])

    def _assert_position(self, row: dict) -> None:
        repair = row["repair"]
        window = repair["dirtyFrameWindow"]
        self.assertLess(window["startFrame"], window["endFrameExclusive"])
        if repair["position"] == "early":
            self.assertEqual(window["startFrame"], 0)
        elif repair["position"] == "middle":
            self.assertEqual(window["startFrame"], 60)
        else:
            self.assertEqual(window["endFrameExclusive"], 150)
        expected_source = (
            "source-b" if repair["position"] == "late" else "source-a")
        self.assertEqual(repair["targetSourceId"], expected_source)
        self.assertEqual(row["authority"]["sourceIds"],
                         ["source-a", "source-b"])

    def _assert_media(self, media: dict) -> None:
        self.assertEqual(
            media["sourceTimingClass"], "normalized-from-vfr-source")
        self.assertNotEqual(media["sourceSha256"], media["parentSha256"])
        self.assertEqual(media["masterVideoFrames"], 150)
        self.assertEqual(
            media["masterAudioSamplesPerChannel"],
            media["terminalExpectedSamples"])
        oracle = media["outsideDirtyOracle"]
        self.assertTrue(oracle["pictureMatches"])
        self.assertTrue(oracle["pcmMatches"])
        self.assertEqual(oracle["pictureScope"], "full-program")

    def _assert_captions(self, captions: dict) -> None:
        self.assertEqual(captions["status"], "revalidated")
        self.assertEqual(len(captions["changedCueIds"]), 1)
        self.assertEqual(len(captions["unchangedCueIds"]), 1)
        self.assertEqual(
            captions["changedCueIds"], captions["contentNodesReused"])
        self.assertEqual(captions["contentNodesRebuilt"], [])
        self.assertNotEqual(
            captions["beforeCompilationHash"],
            captions["afterCompilationHash"])

    def _assert_dialogue(self, dialogue: dict) -> None:
        self.assertEqual(
            dialogue["jRoles"], ["j-cut-handle", "primary"])
        self.assertEqual(
            dialogue["jCoveringCutSegmentIds"], ["cut-a", "cut-b"])
        self.assertEqual(
            dialogue["lRoles"], ["primary", "l-cut-handle"])
        self.assertEqual(
            dialogue["lCoveringCutSegmentIds"], ["cut-b", "cut-c"])
        self.assertEqual(dialogue["renderedWordCount"], 2)
        self.assertGreater(dialogue["cueCount"], 0)

    def _assert_palmier(self, palmier: dict) -> None:
        self.assertEqual(palmier["nativeStatus"], "unsupported")
        self.assertEqual(
            palmier["deliveryDisposition"], "baked-exact-master")
        self.assertFalse(palmier["sampleExact"])
        self.assertTrue(palmier["requiresRepairFragmentImport"])
        readback = palmier["readback"]
        self.assertEqual(
            readback["verificationStatus"],
            "rejected-before-native-readback")
        self.assertFalse(readback["mutationAttempted"])

    def test_native_subset_control_is_narrow_and_non_sample_exact(self) -> None:
        value = self.value["nativeSubsetControl"]
        self.assertEqual(
            value["kind"], "local-structural-palmier-readback-control")
        self.assertEqual(value["nativeStatus"], "frame-exact-unqualified")
        self.assertEqual(value["fps"], {
            "numerator": "30", "denominator": "1",
        })
        self.assertEqual(value["sourceIds"], ["source-a"])
        self.assertTrue(value["passed"])
        self.assertTrue(all(value["assertions"].values()))
        self.assertIn(
            "not a connected Palmier mutation or connected readback",
            self.value["nonClaims"])
        self.assertIn(
            "not native sample-exact Palmier L/J support",
            self.value["nonClaims"])

    def test_case_tamper_changes_bound_cohort_identity(self) -> None:
        changed = copy.deepcopy(_without_hash(self.value))
        original = content_hash(changed)
        changed["cases"][0]["assertions"]["normalizedVfr"] = False
        self.assertNotEqual(content_hash(changed), original)


if __name__ == "__main__":
    unittest.main(verbosity=2)

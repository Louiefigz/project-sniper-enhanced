"""Exercise rebind's real planner while isolating measured-media authorities."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import qualification_plan_rebind as rebind


def _request(root: Path) -> rebind.RebindRequest:
    """Create canonical intent and transcript files for a planner-only test."""
    (root / "source").mkdir()
    (root / "project.json").write_text(json.dumps({
        "resolvedIntent": {"mode": "longform", "scope": "produced"}}))
    (root / "words.json").write_text(json.dumps({"words": [
        {"word": word, "start": 1 + index * .3, "end": 1.2 + index * .3}
        for index, word in enumerate("three exact things".split())]}))
    return rebind.RebindRequest(
        plan=root / "plan.json", proposal=root / "proposal.json",
        manifest=root / "source/asset_manifest.json", transcripts_dir=root,
        qualification=root / "qualification.json",
        cadence_approval=root / "cadence.json",
        expected_intent=root / "project.json", visual_state=root / "visual.json",
        output=root / "out.json", proposal_output=root / "out-proposal.json",
        report=root / "report.json")


def _plan(aspect: str) -> dict:
    """Supply one real timeline and no historical visual style selection."""
    return {
        "target": {"mode": "longform", "scope": "produced", "aspect": aspect},
        "cutTrack": [{"sourceId": "old", "start": 0, "end": 12}],
        "cutDecisions": {"removals": []},
        "graphicsTrack": [], "graphicsDecisions": [],
    }


def _candidate(request: rebind.RebindRequest, plan: dict,
               retired: bool = False) -> rebind.RebindPreparation:
    """Keep actual transcript, planner, style policy and semantic matching."""
    source = {"id": "fresh", "role": "primary", "transcriptPath": "words.json"}
    state = {"state": "talking-head", "faceBBoxNorm": [.4, .2, .2, .3]}
    old = {"sources": [{**source, "id": "old"}]}
    # This is a TEST planner seam; media qualification has separate real tests.
    previous = rebind.build_proposal(plan, str(request.transcripts_dir), old, [state])
    for index, beat in enumerate(previous["introSemanticBeats"]):
        graphic_id = f"graphic-{index}"
        plan["graphicsTrack"].append({
            "id": graphic_id, "semanticBeatId": beat["beatId"],
            "outStart": beat["outStart"], "outEnd": beat["outStart"] + 2,
        })
        plan["graphicsDecisions"].append({
            "beatId": beat["beatId"], "graphicId": graphic_id, "decision": "graphic"})
    if retired:
        plan["target"]["graphicsStyle"] = "overlay-rich"
    with patch.object(rebind, "verify_authorities", return_value=({}, {})), \
            patch.object(rebind, "visual_state_authority", return_value=({}, state)):
        return rebind._prepare_candidate(request, plan, previous, {"sources": [source]})


class RebindCatalogPlannerTests(unittest.TestCase):
    """Changing source authority must not inject retired style or aspect defaults."""

    def test_current_catalog_default_preserves_each_requested_aspect(self) -> None:
        for aspect in ("9:16", "16:9"):
            with self.subTest(aspect=aspect), tempfile.TemporaryDirectory() as raw:
                request = _request(Path(raw))
                plan = _plan(aspect)
                prepared = _candidate(request, plan)
                self.assertEqual(prepared.proposal["meta"]["style"], "catalog-first")
                self.assertEqual(prepared.proposal["meta"]["aspect"], aspect)
                self.assertEqual(prepared.old_source_id, "old")
                self.assertEqual(plan["cutTrack"][0]["sourceId"], "fresh")
                self.assertTrue(prepared.shifts)
                self.assertTrue(all(row["deltaSeconds"] == 0 for row in prepared.shifts))

    def test_explicit_retired_plan_style_still_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            request = _request(Path(raw))
            plan = _plan("16:9")
            with self.assertRaisesRegex(ValueError, "retired"):
                _candidate(request, plan, retired=True)


if __name__ == "__main__":
    unittest.main()

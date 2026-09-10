"""Pure digest regressions: finishing-only edits never dirty timeline/base under source-float-v2.

Legacy domains are byte-identical to before. Changed cuts, speed, framing, seams
or graphics still change the affected roots and digests under every policy.
"""
from __future__ import annotations

import copy
import unittest

from current_render_graph_nodes import source_nodes
from cut_delivery_authority import base_plan_lineage_digest
from fingerprints import base_plan_digest
from render_stage_roots import stage_input_roots

PLAN = {"planVersion": 1, "target": {"mode": "longform", "excerpt": True, "scope": "trim"},
        "captions": {"burn": False},
        "cutTrack": [{"sourceId": "raw-1", "start": 0, "end": 1}, {"sourceId": "raw-1", "start": 3.5, "end": 4}],
        "transitions": [{"outTime": 1.0, "kind": "white-flash", "sfx": False}]}
MANIFEST = {"sources": [{"id": "raw-1", "path": "/TEST/raw.mp4", "duration": 4}],
            "sourceSetAdmission": {"sourceSetDigest": "d" * 64, "receiptPath": "TEST.json"}}
FINISHING = ({"audioEnhance": {"preset": "voice"}}, {"audioGain": [{"outStart": 0.2, "outEnd": 0.8, "dB": 6}]},
             {"transitions": [{"outTime": 1.0, "kind": "white-flash", "sfx": True}]},
             {"music": {"enabled": True, "assetId": "bed", "gapDb": 12}})
PICTURE = ({"cutTrack": [{"sourceId": "raw-1", "start": 0, "end": 0.9}, {"sourceId": "raw-1", "start": 3.5, "end": 4}]},
           {"transitions": [{"outTime": 1.0, "kind": "light-leak", "sfx": False}]},
           {"reframe": {"strategy": "track"}}, {"punchIns": [{"outStart": 0.2, "outEnd": 0.6, "zoom": 1.2}]})


def _item(plan: dict, policy: str) -> dict:
    roots = stage_input_roots(plan, MANIFEST, policy)
    artifact = {"sha256": "0" * 64}
    return {"roots": roots, "sourceInputs": {"source.set": "d" * 64}, "source": artifact,
            "timeline": artifact, "base": artifact, "audio": {} if policy == "source-float-v2" else None}


def _digests(plan: dict, policy: str) -> dict:
    nodes = {row["nodeId"]: row["inputDigests"] for row in source_nodes(plan, _item(plan, policy))}
    return {"timeline": nodes["node-timeline"], "base": nodes["node-base"]}


class RevisionSpeedDigestTests(unittest.TestCase):
    def test_v2_finishing_only_edits_leave_timeline_and_base_digests_unchanged(self) -> None:
        before = _digests(PLAN, "source-float-v2")
        for change in FINISHING:
            with self.subTest(change=change):
                plan = {**copy.deepcopy(PLAN), **change}
                self.assertEqual(_digests(plan, "source-float-v2"), before)
                roots = stage_input_roots(plan, MANIFEST, "source-float-v2")
                self.assertNotEqual(roots["plan.final"], stage_input_roots(PLAN, MANIFEST, "source-float-v2")["plan.final"])

    def test_v2_picture_edits_still_dirty_timeline_or_base(self) -> None:
        before = _digests(PLAN, "source-float-v2")
        for change in PICTURE:
            with self.subTest(change=change):
                self.assertNotEqual(_digests({**copy.deepcopy(PLAN), **change}, "source-float-v2"), before)

    def test_legacy_domains_are_byte_identical_to_the_historical_digests(self) -> None:
        for change in (*FINISHING, *PICTURE):
            plan = {**copy.deepcopy(PLAN), **change}
            with self.subTest(change=change):
                legacy = _digests(plan, "legacy-v1")
                self.assertEqual(legacy["timeline"]["timeline.plan"], base_plan_digest(plan))
                self.assertEqual(legacy["base"]["base.plan"], base_plan_digest(plan))
                self.assertEqual(stage_input_roots(plan, MANIFEST), stage_input_roots(plan, MANIFEST, "legacy-v1"))
        self.assertNotEqual(_digests({**copy.deepcopy(PLAN), **FINISHING[1]}, "legacy-v1"), _digests(PLAN, "legacy-v1"),
                            "legacy bases bake gain in, so a gain edit still dirties them")

    def test_v2_lineage_matches_the_delivery_seal_projection(self) -> None:
        plan = {**copy.deepcopy(PLAN), **FINISHING[0], **FINISHING[1]}
        self.assertEqual(_digests(plan, "source-float-v2")["base"]["base.plan"],
                         base_plan_lineage_digest(plan, "source-float-v2"))
        from audio.program_finish_contract import finishing_free_plan
        self.assertEqual(_digests(plan, "source-float-v2")["base"]["base.plan"],
                         base_plan_digest(finishing_free_plan(PLAN)))


if __name__ == "__main__":
    unittest.main(verbosity=2)

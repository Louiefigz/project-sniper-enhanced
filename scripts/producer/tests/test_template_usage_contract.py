"""Cross-project template reuse must remain transcript-specific."""
import copy
import unittest
from unittest import mock

from _common import *  # noqa: F401,F403
import template_usage_contract as tuc


def _snapshot(fragment_projects: int = 0) -> dict:
    projects = []
    for index in range(4):
        uses = {"statement-card": 1} if index < 3 else {"fragment-payoff": 1}
        if index < fragment_projects:
            uses["fragment-payoff"] = 1
        projects.append({"projectId": f"project-{index}",
                         "approvedAt": f"2026-07-0{index + 1}T00:00:00.000Z",
                         "planHash": str(index) * 64, "uses": uses})
    counts = tuc._usage_counts(projects)
    overused = [kind for kind, item in counts.items()
                if item["projects"] >= 3 and item["projects"] / len(projects) >= .5]
    core = {"schemaVersion": 1, "kind": "producer-template-usage-history",
            "mode": "longform", "windowProjects": 8,
            "projectCount": len(projects), "projects": projects,
            "counts": counts, "overusedKinds": sorted(overused),
            "policy": {"minProjects": 3, "minProjectShare": .5}}
    return {**core, "digest": tuc._stable_hash(core)}


def _empty_snapshot() -> dict:
    core = {"schemaVersion": 1, "kind": "producer-template-usage-history",
            "mode": "longform", "windowProjects": 8,
            "projectCount": 0, "projects": [], "counts": {},
            "overusedKinds": [],
            "policy": {"minProjects": 3, "minProjectShare": .5}}
    return {**core, "digest": tuc._stable_hash(core)}


def _plan(reason: str | None = None, kind: str = "statement-card") -> dict:
    decision = {"beatId": "intro-proof", "decision": "graphic", "kind": kind,
                "alternativesConsidered": ["fragment-payoff"]}
    if reason is not None:
        decision["reuseReason"] = reason
    return {"target": {"mode": "longform", "scope": "produced"},
            "graphicsDecisions": [decision]}


def _beat() -> list[dict]:
    return [{"beatId": "intro-proof", "evidence": "five tips stay consistent",
             "compatibleKinds": ["statement-card", "fragment-payoff"]}]


class TemplateUsageContractTests(unittest.TestCase):
    def check(self, plan: dict, snapshot: dict,
              beats: list[dict] | None = None) -> dict:
        with mock.patch.object(tuc, "semantic_beats",
                               return_value=beats or _beat()):
            return tuc.check(plan, [{"end": 10.0}], snapshot)

    def test_overused_form_requires_underused_alternative_and_reason(self) -> None:
        verdict = self.check(_plan(), _snapshot())
        self.assertFalse(verdict["ok"])
        self.assertIn("reuseReason", " ".join(verdict["errors"]))

        generic = self.check(_plan(
            "This layout is a familiar and generally useful choice for viewers."),
            _snapshot())
        self.assertFalse(generic["ok"], generic)
        self.assertIn("transcript-specific", " ".join(generic["errors"]))

        grounded = self.check(_plan(
            "The transcript says five tips stay consistent, and this anatomy keeps that thesis whole."),
            _snapshot())
        self.assertTrue(grounded["ok"], grounded)
        self.assertEqual(grounded["metrics"]["checkedReuses"], 1)

    def test_underused_choice_needs_no_reuse_waiver(self) -> None:
        plan = _plan(kind="fragment-payoff")
        plan["graphicsDecisions"][0]["alternativesConsidered"] = ["statement-card"]
        self.assertTrue(self.check(plan, _snapshot())["ok"])

    def test_no_compatible_underused_form_creates_no_fake_obligation(self) -> None:
        self.assertTrue(self.check(_plan(), _snapshot(fragment_projects=3))["ok"])

    def test_snapshot_tampering_fails_closed(self) -> None:
        snapshot = copy.deepcopy(_snapshot())
        snapshot["counts"]["statement-card"]["projects"] = 1
        verdict = self.check(_plan(), snapshot)
        self.assertFalse(verdict["ok"])
        self.assertIn("digest", " ".join(verdict["errors"]))

        with mock.patch.object(tuc, "semantic_beats", return_value=_beat()):
            bound = tuc.check(_plan(), [{"end": 10.0}], _snapshot(), "e" * 64)
        self.assertFalse(bound["ok"])
        self.assertIn("controller-bound", " ".join(bound["errors"]))

    def test_empty_history_still_blocks_globally_avoidable_reuse(self) -> None:
        beats = [
            {"beatId": "one", "evidence": "first proof",
             "compatibleKinds": ["statement-card", "fragment-payoff"]},
            {"beatId": "two", "evidence": "second proof",
             "compatibleKinds": ["fragment-payoff", "statement-card"]},
        ]
        plan = {"target": {"mode": "longform", "scope": "produced"},
                "graphicsDecisions": [
                    {"beatId": row["beatId"], "decision": "graphic",
                     "kind": "statement-card"} for row in beats]}
        verdict = self.check(plan, _empty_snapshot(), beats)
        self.assertFalse(verdict["ok"], verdict)
        self.assertIn("replacement witness", " ".join(verdict["errors"]))
        self.assertEqual(verdict["metrics"]["maximumFeasibleDistinctKinds"], 2)

    def test_unavoidable_reuse_passes_global_allocation_gate(self) -> None:
        beats = [
            {"beatId": "one", "evidence": "first proof",
             "compatibleKinds": ["statement-card"]},
            {"beatId": "two", "evidence": "second proof",
             "compatibleKinds": ["statement-card"]},
            {"beatId": "three", "evidence": "third proof",
             "compatibleKinds": ["fragment-payoff"]},
        ]
        choices = ["statement-card", "statement-card", "fragment-payoff"]
        plan = {"target": {"mode": "longform", "scope": "produced"},
                "graphicsDecisions": [
                    {"beatId": row["beatId"], "decision": "graphic",
                     "kind": choices[index]}
                    for index, row in enumerate(beats)]}
        verdict = self.check(plan, _empty_snapshot(), beats)
        self.assertTrue(verdict["ok"], verdict)
        self.assertEqual(verdict["metrics"]["selectedDistinctKinds"], 2)
        self.assertEqual(verdict["metrics"]["maximumFeasibleDistinctKinds"], 2)

    def test_profiled_plan_allocates_against_profile_compatible_kinds(self) -> None:
        plan = _plan(kind="nateherk-rail")
        plan["target"].update({"graphicsStyle": "face-bridge",
                               "visualProfile": "nateherk-editorial-v1"})
        beats = [{"beatId": "intro-proof", "evidence": "first proof",
                  "compatibleKinds": ["nateherk-rail"]}]
        with mock.patch.object(tuc, "semantic_beats", return_value=beats) as mocked:
            verdict = tuc.check(plan, [{"end": 10.0}], _empty_snapshot())
        self.assertTrue(verdict["ok"], verdict)
        self.assertEqual(mocked.call_args.args[2], "nateherk-editorial-v1")


if __name__ == "__main__":
    unittest.main()


class ShortModeDigestBindingTests(unittest.TestCase):
    """Out-of-scope modes (shorts) still bind the validated snapshot digest so
    the delivery-approval writer can verify its controller-bound authority."""

    def test_short_mode_verdict_carries_validated_snapshot_digest(self) -> None:
        snapshot = _snapshot()
        snapshot["mode"] = "short"
        snapshot["digest"] = tuc._stable_hash(
            {k: v for k, v in snapshot.items() if k != "digest"})
        plan = {"target": {"mode": "short", "scope": "produced"},
                "graphicsTrack": []}
        verdict = tuc.check(plan, [{"end": 10.0}], snapshot,
                            expected_digest=snapshot["digest"])
        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["metrics"].get("snapshotDigest"),
                         snapshot["digest"])

    def test_short_mode_invalid_snapshot_still_empty_metrics(self) -> None:
        verdict = tuc.check({"target": {"mode": "short", "scope": "produced"}},
                            [{"end": 10.0}], {"not": "a snapshot"})
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["metrics"], {})

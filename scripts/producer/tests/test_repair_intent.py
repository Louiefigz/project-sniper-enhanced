"""Strict typed repair regressions for the first headless quality-pass lane."""
from __future__ import annotations

import copy
import dataclasses
import unittest

from _common import pl  # noqa: F401
from headless.repair_intent import (
    AccentRepairPolicy,
    ParentRefV1,
    RepairIntentV1,
    RepairIntentError,
    RepairApplication,
    accent_policy,
    apply_repair,
    approved_plan_digest,
    current_accent_policy,
    parse_repair_intent,
)

GENERATION = "11111111-1111-4111-8111-111111111111"
REQUEST = "22222222-2222-4222-8222-222222222222"


def _plan() -> dict:
    return {"planVersion": 3, "graphicsTrack": [
        {"id": "g-00000001", "kind": "section-marker",
         "outStart": 1.0, "outEnd": 3.5, "anchor": "free-band",
         "spec": {"num": "Part 1", "line1": "Old",
                  "line2": "Basics", "side": "left", "accent": "#054BC9"}},
        {"id": "g-00000002", "kind": "section-marker",
         "outStart": 4.0, "outEnd": 6.5, "anchor": "free-band",
         "spec": {"num": "Part 2", "line1": "Keep",
                  "line2": "Basics", "side": "right", "accent": "#F5E960"}},
    ], "captions": {"enabled": True}}


def _parent(plan: dict) -> dict:
    return {"authorityId": "authority-mp4-v1", "publicationSeq": 7,
            "generationId": GENERATION, "commitDigest": "a" * 64,
            "planDigest": approved_plan_digest(plan)}


def _intent(plan: dict) -> dict:
    return {"schemaVersion": 1,
            "effectClass": "SECTION_MARKER_ACCENT_V1",
            "realizationKind": "deterministic-mp4",
            "expectedParent": _parent(plan), "requestId": REQUEST,
            "target": {"lane": "graphicsTrack", "id": "g-00000001"},
            "op": "replace", "relativePointer": "/spec/accent",
            "expectedOld": "#054bc9", "value": "#ffd400"}


def _catalog_plan() -> dict:
    """Current source policy passes; the retired effect schema stays unchanged."""
    plan = _plan()
    for row in plan['graphicsTrack']:
        row['kind'] = 'line-swap'
        row['spec'] = {'lineA': 'Review the plan', 'lineB': 'Check the result',
                       'underlineWord': '', 'swapAt': 1.2, 'accent': '#054BC9'}
    return plan


class RepairIntentTests(unittest.TestCase):
    def test_retired_repair_stops_before_mutation_or_diff(self) -> None:
        from unittest.mock import patch
        original = _plan()
        before = copy.deepcopy(original)
        intent = parse_repair_intent(_intent(original))
        with patch('headless.repair_intent.changed_pointers') as diff, \
                self.assertRaisesRegex(ValueError, 'section-marker.*retired'):
            apply_repair(intent, intent.expected_parent, original, current_accent_policy())
        diff.assert_not_called()
        self.assertEqual(original, before)

    def test_unknown_fields_indexes_bad_ids_and_noops_reject(self) -> None:
        plan = _catalog_plan()
        cases = []
        extra = _intent(plan)
        extra["unexpected"] = True
        cases.append(extra)
        indexed = _intent(plan)
        indexed["relativePointer"] = "/graphicsTrack/0/spec/accent"
        cases.append(indexed)
        bad_id = _intent(plan)
        bad_id["target"]["id"] = "g-legacy"
        cases.append(bad_id)
        boolean_schema = _intent(plan)
        boolean_schema["schemaVersion"] = True
        cases.append(boolean_schema)
        noop = _intent(plan)
        noop["value"] = "#054BC9"
        cases.append(noop)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(RepairIntentError):
                parse_repair_intent(value)

    def test_stale_parent_or_plan_never_rebases(self) -> None:
        plan = _catalog_plan()
        intent = parse_repair_intent(_intent(plan))
        stale_parent = dataclasses.replace(
            intent.expected_parent, commit_digest="b" * 64)
        with self.assertRaisesRegex(RepairIntentError, "parent is stale"):
            apply_repair(
                intent, stale_parent, plan, current_accent_policy())
        changed = copy.deepcopy(plan)
        changed["captions"]["enabled"] = False
        with self.assertRaisesRegex(RepairIntentError, "plan digest"):
            apply_repair(
                intent, intent.expected_parent, changed,
                current_accent_policy())

    def test_duplicate_or_noncanonical_track_identity_is_ineligible(self) -> None:
        for identity in ("g-00000001", "legacy-id", None):
            plan = _catalog_plan()
            if identity is None:
                plan["graphicsTrack"][1].pop("id")
            else:
                plan["graphicsTrack"][1]["id"] = identity
            document = _intent(plan)
            document["expectedParent"] = _parent(plan)
            intent = parse_repair_intent(document)
            with self.subTest(identity=identity), \
                    self.assertRaisesRegex(
                        RepairIntentError, "identit"):
                apply_repair(
                    intent, intent.expected_parent, plan,
                    current_accent_policy())

    def test_catalog_kind_cannot_be_substituted_for_retired_effect(self) -> None:
        base = _catalog_plan()
        cases = []
        wrong_kind = copy.deepcopy(base)
        wrong_kind["graphicsTrack"][0]["kind"] = "marker-highlight"
        cases.append((wrong_kind, _intent(wrong_kind), "section marker"))
        for plan, document, message in cases:
            intent = parse_repair_intent(document)
            with self.subTest(message=message), \
                    self.assertRaisesRegex(RepairIntentError, message):
                apply_repair(
                    intent, intent.expected_parent, plan,
                    current_accent_policy())

    def test_retirement_rejects_stale_value_and_off_policy_requests_without_mutation(self) -> None:
        """Neither alternative request can reopen the retired effect executor."""
        plan = _plan()
        before = copy.deepcopy(plan)
        for key, value in (("expectedOld", "#FFFFFF"), ("value", "#123456")):
            document = _intent(plan)
            document[key] = value
            intent = parse_repair_intent(document)
            with self.subTest(field=key), self.assertRaisesRegex(ValueError, "section-marker.*retired"):
                apply_repair(intent, intent.expected_parent, plan, current_accent_policy())
            self.assertEqual(plan, before)

    def test_forged_or_self_consistent_broad_policy_is_rejected(self) -> None:
        plan = _catalog_plan()
        intent = parse_repair_intent(_intent(plan))
        valid = accent_policy(("#054BC9", "#FFD400"))
        forged = AccentRepairPolicy("0" * 64, valid.allowed_values)
        broad = accent_policy(("#054BC9", "#FFD400", "#123456"))
        for policy in (forged, broad):
            with self.subTest(policy=policy), self.assertRaisesRegex(
                    RepairIntentError, "policy identity"):
                apply_repair(intent, intent.expected_parent, plan, policy)

    def test_historical_application_bytes_are_immutable_and_not_authority(self) -> None:
        """Read-only receipt decoding does not invoke the retired executor."""
        import json
        plan = _plan()
        policy = current_accent_policy()
        self.assertEqual(policy.allowed_values, ("#054BC9", "#FFD400"))
        application = RepairApplication(json.dumps(plan).encode(),
            approved_plan_digest(plan), approved_plan_digest(plan), (),
            "g-00000001", policy.policy_id)
        candidate = application.decoded_plan()
        candidate["graphicsTrack"][0]["spec"]["accent"] = "#123456"
        self.assertEqual(application.decoded_plan(), plan)
        self.assertEqual(application.after_digest, approved_plan_digest(plan))

    def test_direct_dataclass_construction_cannot_bypass_validation(self) -> None:
        plan = _catalog_plan()
        parsed = parse_repair_intent(_intent(plan))
        bad_parent = ParentRefV1(
            parsed.expected_parent.authority_id, True,
            parsed.expected_parent.generation_id,
            parsed.expected_parent.commit_digest,
            parsed.expected_parent.plan_digest)
        bad_intent = RepairIntentV1(
            parsed.expected_parent, "not-a-uuid", parsed.graphic_id,
            parsed.expected_old.lower(), parsed.value)
        cases = ((parsed, bad_parent), (bad_intent, parsed.expected_parent))
        for intent, parent in cases:
            with self.subTest(intent=intent, parent=parent), \
                    self.assertRaises(RepairIntentError):
                apply_repair(intent, parent, plan, current_accent_policy())


if __name__ == "__main__":
    unittest.main(verbosity=2)

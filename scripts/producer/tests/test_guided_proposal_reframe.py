"""Pure adversarial V6 request rederivation; no media or approval qualification."""
from __future__ import annotations

from copy import deepcopy
import unittest

from _guided_proposal_reframe_fixture import accepted, candidate, operation, packet, replace_operations
from cut_preview_io import digest
from guided_media_profile import CAPTION_SHORT_PROFILE, SHORT_PROFILE
from guided_proposal_reframe import validate_requested_manual_crop


class RequestedReframeTests(unittest.TestCase):
    def check(self, plan: dict | None = None, result: dict | None = None, request: dict | None = None) -> bool:
        return validate_requested_manual_crop(accepted() if plan is None else plan,
            candidate() if result is None else result, packet() if request is None else request, CAPTION_SHORT_PROFILE)

    def reject(self, **values: dict) -> None:
        with self.assertRaises((RuntimeError, ValueError)):
            self.check(**values)

    def test_exact_projection_does_not_mutate_accepted_candidate_or_actual_operations(self) -> None:
        rows = (accepted(), candidate(), packet())
        before = deepcopy(rows)
        self.assertTrue(self.check(*rows))
        self.assertEqual(rows, before)
        self.assertEqual([row["type"] for row in rows[2]["proposal"]["operations"]],
                         ["reframe-manual-short", "captions-full-program"])

    def test_karaoke_is_explicit_not_a_default_or_inferred_caption_owner(self) -> None:
        request = packet()
        request["proposal"]["operations"][1]["captions"]["preset"] = "producer-config-karaoke-v1"
        self.assertTrue(self.check(result=candidate(policy="karaoke"), request=request))
        self.reject(request=request)

    def test_candidate_mutation_rejects_even_with_new_self_consistent_hash(self) -> None:
        changes = [{"reframe": {"layout": "fill", "crop": [0, 0, 1, 1], "track": False}},
                   {"captions": {"burn": False}}, {"captionsTrack": None}, {"captionChapters": []},
                   {"captionCorrectionLedger": {}}, {"captionStyles": {}}, {"dialogueCaptionAuthority": {}}, {"chapters": {}}]
        for change in changes:
            with self.subTest(change=change):
                result = {**candidate(), **change}
                request = {**packet(), "candidate": result, "candidateHash": digest(result)}
                self.reject(result=result, request=request)

    def test_changed_request_cannot_reuse_previous_crop_or_caption_projection(self) -> None:
        request = packet()
        request["proposal"]["operations"][0]["reframe"]["crop"] = [0, 0, 1, 1]
        request["proposalHash"] = digest(request["proposal"])
        self.reject(request=request)

    def test_actual_source_id_and_fresh_inherited_authority_are_required(self) -> None:
        changes = [{"reframe": None}, {"reframe": {}}, {"captionsTrack": None}, {"captionStyles": {}},
                   {"captionChapters": []}, {"captionCorrectionLedger": {}}, {"dialogueCaptionAuthority": {}},
                   {"captions": {"burn": True}}, {"chapters": {}}, {"chapters": ["TEST"]},
                   {"cutTrack": []}, {"cutTrack": [{"sourceId": "another"}]}]
        for change in changes:
            with self.subTest(change=change):
                plan = {**accepted(), **change}
                self.reject(plan=plan, result=candidate(plan))
        plan = {**accepted(), "captions": {"burn": False}, "chapters": []}
        self.assertTrue(self.check(plan=plan, result=candidate(plan)))

    def test_explicit_target_and_resolved_scope_default_auto_are_required(self) -> None:
        plan = accepted()
        del plan["target"]["lanes"]
        self.assertTrue(self.check(plan=plan, result=candidate(plan)))
        targets = [{"scope": "trim"}, {"scope": None}, {"mode": "longform"}, {"width": 1920}, {"height": "1920"},
                   {"lanes": {"captions": "off"}}, {"lanes": {"captions": "operator"}},
                   {"lanes": {"captions": ["auto"]}}, {"lanes": {"graphics": ["asset-id"]}}]
        for change in targets:
            with self.subTest(change=change):
                plan = accepted()
                plan["target"].update(change)
                self.reject(plan=plan, result=candidate(plan))

    def test_existing_minimum_and_finite_boolean_free_bounds_are_not_relaxed(self) -> None:
        crops = [[0, 0, 0.049, 1], [0.6, 0, 0.5, 1], [0, 0.6, 1, 0.5], [False, 0, 1, 1],
                 [float("nan"), 0, 1, 1], [0, float("inf"), 1, 1], ["0", 0, 1, 1], [0, 0, 1]]
        for crop in crops:
            with self.subTest(crop=crop):
                request, result = packet(), candidate()
                request["proposal"]["operations"][0]["reframe"]["crop"] = crop
                result["reframe"]["crop"] = crop
                self.reject(result=result, request=request)
        request, result = packet(), candidate()
        request["proposal"]["operations"][0]["reframe"]["crop"] = [0, 0, 0.05, 0.05]
        result["reframe"]["crop"] = [0, 0, 0.05, 0.05]
        self.assertTrue(self.check(result=result, request=request))

    def test_every_operation_has_actual_type_and_its_own_nullable_fields(self) -> None:
        changes = [{"type": ["reframe-manual-short"]}, {"beatIndex": 0}, {"catalogKind": "TEST"}, {"variables": []},
                   {"grade": "warm"}, {"startAnchor": 0}, {"endAnchorExclusive": 1}, {"captions": {}},
                   {"presentation": {}}, {"reason": "        "}, {"reframe": None}, {"approval": True}]
        for change in changes:
            with self.subTest(change=change):
                request = packet()
                request["proposal"]["operations"][0].update(change)
                self.reject(request=request)
        request = packet()
        del request["proposal"]["operations"][1]["reframe"]
        self.reject(request=request)

    def test_payload_versions_are_not_boolean_or_string_coercions(self) -> None:
        for index, name in [(0, "reframe"), (1, "captions")]:
            for value in (True, "1", 1.0):
                request = packet()
                request["proposal"]["operations"][index][name]["schemaVersion"] = value
                self.reject(request=request)

    def test_graphic_and_grade_roles_keep_prior_closed_semantics(self) -> None:
        graphic = operation("catalog-graphic")
        graphic.update(beatIndex=0, catalogKind="TEST-card", variables=[{"name": "label", "value": ""}],
            startAnchor=0, endAnchorExclusive=1, reason="A source-grounded TEST graphic.", presentation={
                "schemaVersion": 1, "anchor": "own-screen", "placement": "full-canvas",
                "compositeMode": "normal", "baseTreatment": "preserve", "rationale": "TEST original geometry."})
        grade = {**operation("grade"), "grade": "warm"}
        rows = [*packet()["proposal"]["operations"], graphic, grade]
        self.assertTrue(self.check(request=replace_operations(packet(), rows)))
        for change in ({"variables": []}, {"grade": "warm"}, {"captions": {}},
                       {"presentation": {**graphic["presentation"], "placement": "measured-free-region"}},
                       {"presentation": {**graphic["presentation"], "schemaVersion": True}}):
            self.reject(request=replace_operations(packet(), [*rows[:2], {**graphic, **change}, grade]))
        self.reject(request=replace_operations(packet(), [*rows[:3], {**grade, "reason": "Cannot carry this reason."}]))

    def test_beat_and_hook_decisions_retain_unique_indices_and_substantive_floors(self) -> None:
        beat = {"beatId": "TEST-beat", "decision": "graphic", "reason": "The original TEST beat is still required.",
                "kind": "TEST-card", "alternativesConsidered": ["TEST-other"],
                "selectionReason": "This TEST anatomy matches the obligation.", "operationIndex": 2}
        seam = {"seamIndex": 0, "decision": "clean-hook", "reason": "Retain this explicit TEST clean seam.",
                "evidence": "TEST source-grounded seam evidence."}
        for changes in ({"beatDecisions": [beat, beat]}, {"hookSeamDecisions": [seam, seam]},
                        {"beatDecisions": [{**beat, "reason": " " * 20}]},
                        {"beatDecisions": [{**beat, "alternativesConsidered": ["TEST-card"]}]},
                        {"hookSeamDecisions": [{**seam, "evidence": " " * 12}]}):
            request = packet()
            request["proposal"].update(changes)
            self.reject(request=request)

    def test_one_crop_and_separate_nonconflicting_caption_selection_are_mandatory(self) -> None:
        crop, caption = operation("reframe-manual-short"), operation("captions-full-program")
        conflict = deepcopy(caption)
        conflict["captions"]["preset"] = "producer-config-karaoke-v1"
        for rows in ([crop], [crop, crop, caption], [crop, caption, conflict]):
            self.reject(request=replace_operations(packet(), rows))

    def test_actual_clause_indices_and_original_utf16_text_are_bound(self) -> None:
        for change in ({"quote": "changed"}, {"start": 1}, {"end": 2}, {"operationIndices": [1, 1]},
                       {"operationIndices": [0]}, {"operationIndices": [0, 2]}, {"disposition": "unsupported"}):
            request = packet()
            request["proposal"]["clauses"][0].update(change)
            self.reject(request=request)
        request = packet()
        request["proposal"]["operations"][0]["clauseIndex"] = 1
        self.reject(request=request)
        request = packet()
        request["rawRequest"]["rawIntent"] += " Extra instruction."
        self.reject(request=request)
        self.reject(request={"proposal": packet()["proposal"]})

    def test_unicode_quote_boundaries_use_utf16_without_surrogate_splitting(self) -> None:
        request = packet()
        raw = "Crop 🧭 and caption."
        request["rawRequest"]["rawIntent"] = raw
        request["proposal"]["clauses"][0].update(quote=raw, end=len(raw.encode("utf-16-le")) // 2)
        self.assertTrue(self.check(request=request))
        first = {**request["proposal"]["clauses"][0], "quote": "Crop \ud83e", "end": 6}
        second = {**first, "quote": "\udded and caption.", "start": 6, "end": 20,
                  "operationIndices": [], "disposition": "unsupported"}
        request["proposal"]["clauses"] = [first, second]
        self.reject(request=request)

    def test_closed_schema_and_existing_story_semantics_are_not_skipped(self) -> None:
        for change in ({"extra": True}, {"colorPolicy": ["preserve"]}, {"summary": " "},
                       {"graphicsStyleRationale": "                    "}, {"schemaVersion": 6.0}):
            request = packet()
            request["proposal"].update(change)
            self.reject(request=request)
        request = packet()
        request["proposal"]["beats"][0]["supportsBeatIndices"] = [0, 0]
        self.reject(request=request)

    def test_historical_or_valid_v6_no_crop_retains_the_callers_old_comparison(self) -> None:
        for version in (4, 5):
            request = packet()
            request["proposal"]["schemaVersion"] = version
            self.assertFalse(self.check(request=request))
        request = replace_operations(packet(), [operation("preserve-cut")])
        self.assertFalse(self.check(request=request))
        with self.assertRaisesRegex(RuntimeError, "profile"):
            validate_requested_manual_crop(accepted(), candidate(), packet(), SHORT_PROFILE)


if __name__ == "__main__":
    unittest.main()

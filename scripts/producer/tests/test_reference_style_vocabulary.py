"""Reference style vocabulary stays current, bounded, and planning-only."""
from __future__ import annotations

from copy import deepcopy

from cut_preview_io import file_hash
from graphics.reference_style_vocabulary import (
    prepare_vocabulary, validate_vocabulary,
)
from reference_style_application_lint import VocabularyContext, lint_style_application
from _reference_reuse_fixture import ReuseFixture


class ReferenceStyleVocabularyTests(ReuseFixture):
    """Use the real catalog freezer against small test-owned evidence."""

    def setUp(self) -> None:
        """Add profile, study, and visual evidence to the shared fixture."""
        super().setUp()
        self.profile = self.root / "style_profile.json"
        self.deep = self.root / "deep_study.json"
        self.frame = self.root / "frame-001.jpg"
        self.profile.write_text('{"schemaVersion":1,"referenceId":"reference-1"}')
        self.deep.write_text('{"video":"TEST reference","events":[]}')
        self.frame.write_bytes(b"TEST reviewed frame bytes")

    def evidence(self, identifier: str, role: str, path) -> dict:
        """Create one exact test evidence row."""
        return {"id": identifier, "role": role, "path": str(path),
                "sha256": file_hash(path),
                "observation": f"TEST inspected {role} evidence"}

    def catalog(self):
        """Give this application-focused fixture explicit synthetic measured evidence."""
        catalog = super().catalog()
        for record in catalog.records:
            record["eligibility"] = {**record["eligibility"],
                "executionStatus": "measured-compatibility-candidate",
                "selectionEligible": True, "prerequisites": []}
        return catalog

    def draft(self) -> dict:
        """Return a two-option comparison family with cited observations."""
        refs = [row["ref"] for row in self.catalog().records]
        contender = lambda ref, difference: {
            "catalogRef": ref, "styleFit": "TEST compact comparison treatment",
            "bestFor": "TEST simultaneous before and after information",
            "difference": difference, "configuration": "TEST replace copy and timing",
            "variationOptions": ["TEST swap pane emphasis", "TEST stage result second"],
            "availability": "ready", "prerequisites": [],
            "evidenceIds": ["frame-1"], "confidence": 0.8,
        }
        trait = lambda identifier, description: {
            "id": identifier, "description": description,
            "evidenceIds": ["profile", "frame-1"],
        }
        return {
            "referenceId": "reference-1",
            "coverage": {"status": "limited", "reviewed": "TEST profile, events, one frame",
                         "limitations": ["TEST motion phases were not rendered"]},
            "evidence": [self.evidence("profile", "style-profile", self.profile),
                         self.evidence("deep", "deep-study", self.deep),
                         self.evidence("frame-1", "frame", self.frame)],
            "stableTraits": [trait("compact-hierarchy", "TEST compact type hierarchy")],
            "flexibleTraits": [trait("panel-direction", "TEST panel direction may vary")],
            "signatureDevices": [trait("result-accent", "TEST result accent may repeat")],
            "families": [{"id": "comparison", "name": "TEST comparison family",
                          "purposes": ["comparison", "evidence"],
                          "sharedStyle": "TEST compact type and staged result emphasis",
                          "useWhen": "TEST viewer must compare two states",
                          "avoidWhen": "TEST narration presents only one state",
                          "contenders": [contender(refs[0], "TEST meter emphasizes amount"),
                                         contender(refs[1], "TEST callout emphasizes result")]}],
            "selectionPolicy": {
                "coherence": "TEST preserve hierarchy and staged result emphasis",
                "variation": "TEST vary composition when it improves the viewer job",
                "repetition": "TEST repeat only for a signature or callback",
                "uncertainty": "TEST inspect more evidence or keep the supported conservative choice",
            },
        }

    def test_prepares_multiple_current_options_without_approval(self) -> None:
        """A valid vocabulary freezes only inspected candidates and claims no approval."""
        catalog = self.catalog()
        record = prepare_vocabulary(self.draft(), catalog)
        report = validate_vocabulary(record, catalog)
        self.assertEqual(report["status"], "style-vocabulary-current")
        self.assertEqual(report["familyCount"], 1)
        self.assertEqual(report["contenderCount"], 2)
        self.assertEqual(report["coverage"], "limited")
        for field in ("styleApproved", "qualityApproved", "renderApproved",
                      "verifiedMimicQualified"):
            self.assertIs(record[field], False)

    def test_changed_evidence_or_catalog_source_invalidates_record(self) -> None:
        """Reviewed inputs and selected component bytes cannot drift."""
        catalog = self.catalog(); record = prepare_vocabulary(self.draft(), catalog)
        self.frame.write_bytes(b"TEST changed reviewed frame")
        with self.assertRaisesRegex((RuntimeError, ValueError), "stale|changed"):
            validate_vocabulary(record, catalog)
        self.frame.write_bytes(b"TEST reviewed frame bytes")
        record = prepare_vocabulary(self.draft(), catalog)
        (self.sources / "meter-card.html").write_text("<!-- TEST changed component -->")
        with self.assertRaisesRegex((RuntimeError, ValueError), "changed|prepare again"):
            validate_vocabulary(record, catalog)

    def test_rejects_unknown_citations_duplicate_options_and_false_coverage(self) -> None:
        """Authored semantics remain evidence-cited and honestly bounded."""
        catalog = self.catalog()
        for mutate, message in (
            (lambda value: value["stableTraits"][0].update(evidenceIds=["missing"]), "unknown evidence"),
            (lambda value: value["families"][0]["contenders"].append(
                deepcopy(value["families"][0]["contenders"][0])), "duplicate contender"),
            (lambda value: value["coverage"].update(limitations=[]), "limited coverage"),
        ):
            draft = self.draft(); mutate(draft)
            with self.assertRaisesRegex(ValueError, message):
                prepare_vocabulary(draft, catalog)

    def test_nonready_options_require_a_reason(self) -> None:
        """Unready research cannot masquerade as an executable option."""
        catalog = self.catalog(); draft = self.draft()
        contender = draft["families"][0]["contenders"][0]
        contender["availability"] = "research-only"
        with self.assertRaisesRegex(ValueError, "other statuses need"):
            prepare_vocabulary(draft, catalog)
        contender["prerequisites"] = ["TEST source is research guidance only"]
        record = prepare_vocabulary(draft, catalog)
        self.assertEqual(record["families"][0]["contenders"][0]["availability"],
                         "research-only")

    def test_reference_source_presence_cannot_claim_execution_readiness(self) -> None:
        """A mirror file remains adaptation research until measured route evidence exists."""
        catalog = super().catalog(); draft = self.draft()
        with self.assertRaisesRegex(ValueError, "lacks measured execution evidence"):
            prepare_vocabulary(draft, catalog)
        by_ref = {row["ref"]: row for row in catalog.records}
        for contender in draft["families"][0]["contenders"]:
            contender["availability"] = "prerequisite"
            contender["prerequisites"] = by_ref[contender["catalogRef"]]["eligibility"]["prerequisites"]
        self.assertEqual(prepare_vocabulary(draft, catalog)["families"][0]
                         ["contenders"][0]["availability"], "prerequisite")

    def test_measured_option_can_stay_vocabulary_ready_before_job_probe(self) -> None:
        """Planning readiness does not forge the separate per-job probe receipt."""
        catalog = self.catalog(); draft = self.draft()
        for record in catalog.records:
            record["eligibility"]["prerequisites"] = ["guarded-capability-probe"]
        prepared = prepare_vocabulary(draft, catalog)
        contenders = prepared["families"][0]["contenders"]
        self.assertTrue(all(row["availability"] == "ready" for row in contenders))
        self.assertTrue(all(row["record"]["eligibility"]["prerequisites"]
                            == ["guarded-capability-probe"]
                            for row in prepared["candidates"].values()))

    def ordinary_plan(self, record: dict) -> dict:
        """Bind two ordinary graphics to the two inspected contenders."""
        contenders = record["families"][0]["contenders"]
        choices, graphics = [], []
        for index, contender in enumerate(contenders):
            ref = contender["catalogRef"]
            graphic_id = f"graphic-{index + 1}"
            graphics.append({"id": graphic_id,
                             "kind": record["candidates"][ref]["record"]["id"]})
            choices.append({"graphicId": graphic_id, "viewerNeed": "TEST compare states",
                "familyId": "comparison", "contenderRef": ref,
                "anatomy": f"TEST comparison anatomy {index + 1}",
                "configuration": f"TEST composition {index + 1}",
                "development": f"TEST information development {index + 1}",
                "consideredContenders": [row["catalogRef"] for row in contenders],
                "selectionReason": "TEST content-fit choice", "repeatMode": "new",
                "repeatReason": "TEST first use of this contender"})
        return {"graphicsTrack": graphics, "styleApplication": {"schemaVersion": 1,
            "vocabulary": {"path": "/TEST/reference_style_vocabulary.json",
                           "sha256": "a" * 64, "referenceId": "reference-1"},
            "choices": choices, "limitations": ["TEST structural plan only"]}}

    def test_ordinary_plan_binds_every_graphic_to_current_family_choices(self) -> None:
        """Ordinary Producer gets the same semantic selection record as native paths."""
        record = prepare_vocabulary(self.draft(), self.catalog())
        plan = self.ordinary_plan(record)
        context = VocabularyContext(record, "/TEST/reference_style_vocabulary.json",
                                    "a" * 64, "reference-1")
        verdict = lint_style_application(plan, context)
        self.assertTrue(verdict["ok"], verdict["errors"])
        plan["styleApplication"]["choices"].pop()
        verdict = lint_style_application(plan, context)
        self.assertIn("every graphicsTrack id", verdict["errors"][0])

    def test_ordinary_plan_rejects_kind_substitution_and_false_grounding(self) -> None:
        """A semantic declaration cannot replace the executable-kind or vocabulary proof."""
        record = prepare_vocabulary(self.draft(), self.catalog())
        plan = self.ordinary_plan(record); plan["graphicsTrack"][0]["kind"] = "other"
        context = VocabularyContext(record, "/TEST/reference_style_vocabulary.json",
                                    "a" * 64, "reference-1")
        verdict = lint_style_application(plan, context)
        self.assertIn("executable graphic kind", verdict["errors"][0])
        self.assertFalse(lint_style_application(plan, None)["ok"])

    def supplemental_choice(self, graphic_id: str, catalog_id: str) -> dict:
        """Record a catalog choice that does not claim vocabulary membership."""
        return {"graphicId": graphic_id, "viewerNeed": "TEST show supporting proof",
                "catalogId": catalog_id,
                "anatomy": "TEST proof card anatomy",
                "configuration": "TEST configure proof for the current narration",
                "development": "TEST reveal proof, then hold the result",
                "selectionReason": "TEST content fit beats the vocabulary contenders",
                "relationshipMode": "coherent",
                "relationshipEvidence": "TEST shares compact hierarchy and staged emphasis",
                "repeatMode": "new", "repeatReason": "TEST first use of this component"}

    def test_general_catalog_choice_can_coexist_without_vocabulary_claim(self) -> None:
        """The reference vocabulary guides its choices without closing the catalog."""
        record = prepare_vocabulary(self.draft(), self.catalog())
        plan = self.ordinary_plan(record)
        plan["graphicsTrack"].append({"id": "graphic-3", "kind": "chart-story"})
        plan["styleApplication"]["supplementalChoices"] = [
            self.supplemental_choice("graphic-3", "chart-story")]
        context = VocabularyContext(record, "/TEST/reference_style_vocabulary.json",
                                    "a" * 64, "reference-1")
        verdict = lint_style_application(plan, context)
        self.assertTrue(verdict["ok"], verdict["errors"])
        self.assertEqual(verdict["metrics"]["styleChoices"], 2)
        self.assertEqual(verdict["metrics"]["supplementalStyleChoices"], 1)

    def test_full_catalog_or_restraint_can_select_zero_vocabulary_options(self) -> None:
        """Analyzed families guide the edit without forcing a partial-allowlist choice."""
        record = prepare_vocabulary(self.draft(), self.catalog())
        context = VocabularyContext(record, "/TEST/reference_style_vocabulary.json",
                                    "a" * 64, "reference-1")
        plan = self.ordinary_plan(record)
        plan["graphicsTrack"] = [{"id": "graphic-3", "kind": "chart-story"}]
        plan["styleApplication"]["choices"] = []
        plan["styleApplication"]["supplementalChoices"] = [
            self.supplemental_choice("graphic-3", "chart-story")]
        self.assertTrue(lint_style_application(plan, context)["ok"])
        plan["graphicsTrack"] = []; plan["styleApplication"]["supplementalChoices"] = []
        self.assertTrue(lint_style_application(plan, context)["ok"])

    def test_different_catalog_ids_do_not_fake_composition_variation(self) -> None:
        """The anatomy/configuration/development signature wins over component ID."""
        record = prepare_vocabulary(self.draft(), self.catalog())
        plan = self.ordinary_plan(record); first, second = plan["styleApplication"]["choices"]
        for field in ("anatomy", "configuration", "development"):
            second[field] = first[field]
        context = VocabularyContext(record, "/TEST/reference_style_vocabulary.json",
                                    "a" * 64, "reference-1")
        self.assertIn("repeat mode", lint_style_application(plan, context)["errors"][0])
        second["repeatMode"] = "callback"
        self.assertTrue(lint_style_application(plan, context)["ok"])

    def test_supplemental_choice_requires_exact_binding_and_relationship(self) -> None:
        """General choices stay executable and explain their style relationship."""
        record = prepare_vocabulary(self.draft(), self.catalog())
        context = VocabularyContext(record, "/TEST/reference_style_vocabulary.json",
                                    "a" * 64, "reference-1")
        for mutate, message in (
            (lambda row: row.update(catalogId="other"), "executable graphic kind"),
            (lambda row: row.update(relationshipMode="similar-ish"), "relationship mode"),
            (lambda row: row.update(relationshipEvidence=""), "relationshipEvidence"),
        ):
            plan = self.ordinary_plan(record)
            plan["graphicsTrack"].append({"id": "graphic-3", "kind": "chart-story"})
            row = self.supplemental_choice("graphic-3", "chart-story")
            mutate(row); plan["styleApplication"]["supplementalChoices"] = [row]
            verdict = lint_style_application(plan, context)
            self.assertIn(message, verdict["errors"][0])

    def test_graphic_must_have_exactly_one_style_choice_kind(self) -> None:
        """No graphic can be omitted or claimed by both vocabulary paths."""
        record = prepare_vocabulary(self.draft(), self.catalog())
        context = VocabularyContext(record, "/TEST/reference_style_vocabulary.json",
                                    "a" * 64, "reference-1")
        plan = self.ordinary_plan(record)
        plan["styleApplication"]["supplementalChoices"] = [
            self.supplemental_choice("graphic-1", plan["graphicsTrack"][0]["kind"])]
        verdict = lint_style_application(plan, context)
        self.assertIn("exactly once", verdict["errors"][0])

    def test_mixed_application_keeps_one_total_choice_bound(self) -> None:
        """Adding a second choice lane cannot double the prior memory bound."""
        record = prepare_vocabulary(self.draft(), self.catalog())
        context = VocabularyContext(record, "/TEST/reference_style_vocabulary.json",
                                    "a" * 64, "reference-1")
        plan = self.ordinary_plan(record)
        row = self.supplemental_choice("graphic-3", "chart-story")
        plan["styleApplication"]["supplementalChoices"] = [row] * 511
        verdict = lint_style_application(plan, context)
        self.assertIn("exceeds 512", verdict["errors"][0])


if __name__ == "__main__":
    import unittest
    unittest.main()

"""Opt-in planning evidence: exact retrieval, route constraints and stale inputs."""
from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _reference_reuse_fixture import ReuseFixture
from graphics.reference_reuse_map import prepare_map, validate_map


class ReferenceReuseMapTests(ReuseFixture):
    """Contract tests run without network, rendering or image assessment."""

    def test_prepare_is_repeatable_and_keeps_decisions_pending(self) -> None:
        """The same pinned request produces identical retrieval evidence."""
        request, catalog = self.request(), self.catalog()
        record = prepare_map(request, catalog)
        self.assertEqual(record, prepare_map(request, catalog))
        self.assertEqual(record["shots"][0]["decision"], {"route": "pending"})
        with self.assertRaisesRegex(ValueError, "pending"):
            validate_map(record, catalog)

    def test_matching_is_explicit_for_short_and_long_form(self) -> None:
        """Only requests explicitly choosing reference matching enter this path."""
        for form in ("short", "longform"):
            self.body["format"] = form
            self.assertEqual(self.prepared()["format"], form)
        for scope in (None, "inspiration", "ordinary-edit"):
            self.body["scope"] = scope
            with self.assertRaisesRegex(ValueError, "explicit reference-match"):
                self.prepared()

    def test_reference_status_and_geometry_do_not_admit_or_disqualify(self) -> None:
        """A landscape reference can be planned for native Shorts without a port claim."""
        record = self.decided()
        candidate = next(iter(record["candidates"].values()))
        self.assertEqual(candidate["record"]["integration"]["status"], "reference")
        self.assertEqual(candidate["record"]["declared"]["aspects"], ["16:9"])
        report = validate_map(record, self.catalog())
        self.assertTrue(report["ready"])
        self.assertEqual(report["status"], "complete-planning-only")
        for field in ("executionAdmitted", "renderApproved", "qualityApproved", "styleApproved"):
            self.assertFalse(report[field])
        self.assertIn(candidate["source"]["path"], report["inputPins"])

    def test_all_reuse_routes_require_actual_inspection(self) -> None:
        """Reuse/configure/compose share exact inspection binding."""
        for route in ("reuse", "configure", "compose"):
            record = self.decided(route)
            self.assertTrue(validate_map(record, self.catalog())["ready"])
            record["shots"][0]["inspections"] = []
            with self.assertRaisesRegex(ValueError, "not inspected"):
                validate_map(record, self.catalog())

    def test_route_shape_is_not_interchangeable(self) -> None:
        """A route must describe its real single, configured or combined pieces."""
        for source, destination in (("reuse", "configure"), ("configure", "reuse"), ("reuse", "compose")):
            record = self.decided(source)
            record["shots"][0]["decision"]["route"] = destination
            with self.assertRaises(ValueError):
                validate_map(record, self.catalog())

    def test_inventory_deletion_duplication_and_substitution_fail(self) -> None:
        """Editing the map cannot silently drop or replace requested shots."""
        original = self.decided()
        variants = ([], original["shots"] * 2, [{**original["shots"][0], "id": "replacement"}])
        for shots in variants:
            record = {**original, "shots": shots}
            with self.assertRaisesRegex(ValueError, "inventory"):
                validate_map(record, self.catalog())

    def test_request_rejects_duplicate_and_unknown_ids(self) -> None:
        """Stable identities never use dictionary overwrite as a fallback."""
        original = deepcopy(self.body)
        for field in ("references", "shots"):
            self.body = deepcopy(original)
            self.body[field] *= 2
            with self.assertRaisesRegex(ValueError, "duplicate"):
                self.prepared()
        self.body = deepcopy(original)
        self.body["shots"][0]["referenceId"] = "unknown"
        with self.assertRaisesRegex(ValueError, "unknown reference"):
            self.prepared()

    def test_external_request_pin_binds_all_authored_fields(self) -> None:
        """An in-memory replacement cannot borrow an unchanged request pin."""
        request = self.request()
        request["format"] = "longform"
        with self.assertRaisesRegex(ValueError, "differs"):
            prepare_map(request, self.catalog())

    def test_pinned_reference_plan_and_request_mutation_fail(self) -> None:
        """Every external planning input participates in freshness checks."""
        for path in (self.reference, self.plan, self.root / "request.json"):
            record = self.decided()
            before = path.read_bytes()
            path.write_bytes(before + b"\nTEST mutation")
            with self.assertRaisesRegex(ValueError, "stale pinned file"):
                validate_map(record, self.catalog())
            path.write_bytes(before)

    def test_catalog_record_and_source_changes_fail_independently(self) -> None:
        """Unchanged metadata cannot conceal edited source implementation."""
        record = self.decided()
        path = Path(next(iter(record["candidates"].values()))["source"]["path"])
        path.write_text("<!-- TEST changed implementation -->")
        with self.assertRaisesRegex(ValueError, "source, or frozen"):
            validate_map(record, self.catalog())
        record = self.decided()
        self.index[0]["description"] = "TEST changed catalog claim"
        self.write_json(self.catalog_root / "catalog-index.json", self.index)
        with self.assertRaisesRegex(ValueError, "catalog"):
            validate_map(record, self.catalog())

    def test_inspection_digest_and_unknown_or_duplicate_refs_fail(self) -> None:
        """Candidate names alone are insufficient inspection evidence."""
        original = self.decided()
        for field, value in (("candidateSha256", "0" * 64), ("ref", "mirror:unknown")):
            record = deepcopy(original)
            record["shots"][0]["inspections"][0][field] = value
            with self.assertRaises(ValueError):
                validate_map(record, self.catalog())
        original["shots"][0]["inspections"] *= 2
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_map(original, self.catalog())

    def test_custom_requires_compared_gap_and_retains_selected_pieces(self) -> None:
        """Custom code is scoped to an inspected gap, with reusable pieces retained."""
        record = self.custom()
        self.assertTrue(validate_map(record, self.catalog())["ready"])
        for field in ("gap", "scope", "closest", "retainedPiecesRationale", "retainedRefs"):
            changed = deepcopy(record)
            changed["shots"][0]["decision"]["custom"].pop(field)
            with self.assertRaises(ValueError):
                validate_map(changed, self.catalog())

    def test_custom_can_extend_a_partly_reusable_inspected_base(self) -> None:
        """Keep a candidate's useful layout while building its missing behavior."""
        record = self.custom()
        shot = record["shots"][0]
        closest = shot["decision"]["custom"]["closest"][0]["ref"]
        shot["decision"]["pieces"].append({"ref": closest, "role": "retain the card layout",
                                           "changes": "TEST add per-digit staging only"})
        shot["decision"]["custom"]["retainedRefs"].append(closest)
        self.assertTrue(validate_map(record, self.catalog())["ready"])
        shot["decision"]["pieces"][-1]["changes"] = ""
        with self.assertRaisesRegex(ValueError, "partial reuse changes"):
            validate_map(record, self.catalog())

    def test_custom_rejects_selected_gaps_not_compared_by_custom_scope(self) -> None:
        """Retaining a base does not waive its outstanding capability comparison."""
        record = self.custom()
        shot = record["shots"][0]
        inspection = shot["inspections"][0]
        inspection["fit"], inspection["gapType"] = "gap", "missing-capability"
        shot["decision"]["pieces"][0]["changes"] = "TEST improve result staging"
        with self.assertRaisesRegex(ValueError, "partial reuse gap was not compared"):
            validate_map(record, self.catalog())

    def test_unrelated_catalog_changes_preserve_reusable_planning_evidence(self) -> None:
        """Only the actual search scope/results and inspected candidates are bound."""
        record = self.decided()
        self.index.append({"name": "unrelated", "type": "component", "title": "unrelated",
                           "description": "TEST galaxy", "tags": ["space"]})
        self.write_json(self.catalog_root / "catalog-index.json", self.index)
        (self.sources / "unrelated.html").write_text("<!-- TEST galaxy -->")
        self.assertTrue(validate_map(record, self.catalog())["ready"])

    def test_search_miss_requires_a_real_closest_inspection(self) -> None:
        """No result is not proof that the catalog lacks the behavior."""
        self.body["shots"][0]["query"] = "unfindable-mechanism"
        record = self.prepared()
        self.assertEqual(record["shots"][0]["candidateRefs"], [])
        self.body["shots"][0]["additionalCandidates"] = ["mirror:meter-card"]
        record = self.prepared()
        self.assertEqual(record["shots"][0]["search"]["total"], 0)
        self.assertEqual(record["shots"][0]["candidateRefs"], ["mirror:meter-card"])
        self.body["shots"][0]["additionalCandidates"] = ["meter-card"]
        with self.assertRaisesRegex(ValueError, "exact unambiguous"):
            self.prepared()

    def test_custom_cannot_relabel_missing_assets_as_capability_gaps(self) -> None:
        """Structured missing asset evidence remains a prerequisite."""
        record = self.custom()
        gap = record["shots"][0]["inspections"][1]
        gap["prerequisites"] = [{"kind": "asset", "detail": "TEST screenshot not captured"}]
        with self.assertRaisesRegex(ValueError, "remain prerequisites"):
            validate_map(record, self.catalog())
        gap["fit"], gap["gapType"] = "prerequisite", None
        with self.assertRaisesRegex(ValueError, "inspected gap"):
            validate_map(record, self.catalog())

    def test_unavailable_adapter_is_blocked_even_for_custom(self) -> None:
        """Execution readiness stays independent of template matching."""
        record = self.custom()
        decision = record["shots"][0]["decision"]
        decision["execution"]["status"] = "unavailable"
        with self.assertRaisesRegex(ValueError, "adapter is a blocker"):
            validate_map(record, self.catalog())
        decision.pop("custom")
        decision["route"] = "blocked"
        decision["prerequisites"] = [{"kind": "adapter", "detail": "TEST adapter unavailable"}]
        report = validate_map(record, self.catalog())
        self.assertFalse(report["ready"])
        self.assertEqual(report["blockedShots"], ["shot-1"])

    def test_missing_source_can_be_reported_but_not_inspected(self) -> None:
        """Discovery honestly preserves absent sources as prerequisites."""
        (self.sources / "meter-card.html").unlink()
        record = self.prepared()
        missing = record["candidates"]["mirror:meter-card"]
        self.assertFalse(missing["source"]["exists"])
        shot = record["shots"][0]
        shot["inspections"] = [self.inspect(record, "mirror:meter-card", "gap")]
        with self.assertRaisesRegex(ValueError, "missing source is a prerequisite"):
            validate_map(record, self.catalog())

    def test_symlink_and_hardlink_evidence_are_rejected(self) -> None:
        """Shared no-follow file readers protect pinning from path aliases."""
        path = self.root / "aliased-reference.md"
        path.symlink_to(self.reference)
        self.body["references"][0]["path"] = str(path)
        with self.assertRaises(OSError):
            self.prepared()
        path.unlink()
        os.link(self.reference, path)
        with self.assertRaisesRegex(RuntimeError, "unsafe"):
            self.prepared()

    def test_project_binding_cannot_be_replaced_after_preparation(self) -> None:
        """A valid map is specific to the planned target project."""
        record = self.decided()
        record["project"] = str(self.root / "other-project")
        with self.assertRaisesRegex(ValueError, "frozen evidence"):
            validate_map(record, self.catalog())


if __name__ == "__main__":
    import unittest
    unittest.main()

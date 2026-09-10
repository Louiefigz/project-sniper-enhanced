"""Catalog discovery over the recorded mirror + study + registry (live data).

The capability side reads whatever ``comp_capabilities._MATRIX_PATH`` names —
under the suite that is ``_common``'s hermetic release-ready matrix, so these
verdicts do not drift with the repo's probe file.
"""
from __future__ import annotations

import contextlib
import io
import json
import unittest
from unittest.mock import patch

import _common  # noqa: F401  (producer pkg root on sys.path; hermetic matrix)
from graphics import catalog_discovery as cd
from graphics import catalog_discovery_cli as cli
from graphics import catalog_discovery_sources as sources
from graphics import comp_capabilities as caps
from graphics.comp_capability_artifact import composition_kinds
from graphics.catalog_discovery_sources import PORTED_KINDS
from graphics.scene_catalog import CatalogSceneRequest, wrap_catalog_scene
from graphics.scene_contract import SceneContractError


class _Live(unittest.TestCase):
    catalog: cd.Catalog

    @classmethod
    def setUpClass(cls) -> None:
        """Load the recorded catalog once for this test class."""
        cls.catalog = cd.load_catalog()

    def search(self, query: str, **filters: object) -> dict:
        """Search the original test catalog through the public API."""
        return cd.search_catalog(self.catalog, query, cd.SearchFilters(**filters))

    def refs(self, result: dict) -> list[str]:
        """Return exact result references in their reported order."""
        return [row["ref"] for row in result["results"]]


class RealSearchTests(_Live):
    """The handoff's three planning asks, answered from the whole catalog."""

    def test_transition_search_matches_beyond_names(self) -> None:
        """Verify transition search matches beyond names."""
        result = self.search("find a subtle transition", limit=8)
        self.assertEqual(result["terms"], ["find", "subtle", "transition"])
        self.assertEqual(result["ignoredTerms"], ["a"])
        self.assertIn("local:hw-scribble-transition", self.refs(result))
        via_tag_only = [row for row in result["results"]
                        if row["match"]["matchedTerms"].get("transition") == ["tags"]]
        self.assertTrue(via_tag_only, "a tag-only hit proves matching beyond names")
        for row in result["results"]:
            self.assertTrue(row["match"]["matchedTerms"])
            self.assertIn(row["integration"]["status"], cd.STATUSES)

    def test_comparison_card_spans_reference_and_local(self) -> None:
        """Verify comparison card spans reference and local."""
        result = self.search("comparison card", limit=30)
        refs = self.refs(result)
        self.assertIn("mirror:comparison-split", refs)
        self.assertTrue(any(ref.startswith("local:") for ref in refs))
        reference = next(r for r in result["results"] if r["ref"] == "mirror:comparison-split")
        self.assertEqual(reference["integration"]["status"], cd.STATUS_REFERENCE)
        self.assertIsNone(reference["integration"]["kind"])
        self.assertTrue(reference["upstream"]["reference"]["exists"])

    def test_data_card_and_presentation_emphasis(self) -> None:
        """Verify data card and presentation emphasis."""
        data = self.search("data chart stats card", limit=8)
        self.assertEqual(self.refs(data)[0], "local:chart-story")
        self.assertEqual(len(data["results"][0]["match"]["matchedTerms"]), 4)
        self.assertIn("mirror:animated-bar-chart", self.refs(data))
        emphasis = self.search("highlight part of this presentation", limit=8)
        self.assertEqual(self.refs(emphasis)[0], "local:marker-highlight")
        self.assertIn("presentation", emphasis["results"][0]["match"]["unmatchedTerms"])

    def test_filters_narrow_to_measured_16x9_kinds(self) -> None:
        """Verify filters narrow to measured 16x9 kinds."""
        result = self.search("highlight emphasis", declared_aspect="16:9",
                             status=cd.STATUS_MEASURED, limit=8)
        self.assertTrue(result["results"])
        for row in result["results"]:
            self.assertEqual(row["integration"]["status"], cd.STATUS_MEASURED)
            self.assertEqual(row["integration"]["measured"]["aspect"], "16:9")
            self.assertEqual(row["declared"]["aspects"], ["16:9"])


class DeterminismAndBoundsTests(_Live):
    def test_exact_refs_outrank_extra_prefix_word_hits(self) -> None:
        """A competing description containing 'local' cannot hide an exact ref."""
        for name in ("local:icon-badge", "local:chip-row", "mirror:push-in"):
            self.assertEqual(self.refs(self.search(name, limit=1)), [name])
        self.assertEqual(self.refs(self.search("comparison card", limit=3)),
                         ["local:nateherk-takeover", "mirror:social-proof-card", "mirror:card-resize"])

    def test_same_query_twice_is_identical_and_limits_are_explicit(self) -> None:
        """Verify same query twice is identical and limits are explicit."""
        first = self.search("transition", limit=100)
        second = cd.search_catalog(cd.load_catalog(), "transition", cd.SearchFilters(limit=100))
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        self.assertFalse(first["limited"])
        capped = self.search("transition", limit=3)
        self.assertTrue(capped["limited"])
        self.assertEqual(capped["total"], first["total"])
        self.assertEqual(capped["returned"], 3)
        self.assertEqual(self.refs(capped), self.refs(first)[:3])

    def test_exact_id_is_never_dropped_by_the_limit(self) -> None:
        """Verify exact id is never dropped by the limit."""
        result = self.search("ui-focus-zoom", limit=1)
        self.assertGreater(result["total"], 1)
        self.assertEqual(self.refs(result), ["local:ui-focus-zoom"])
        self.assertTrue(result["results"][0]["match"]["exact"])

    def test_exact_id_excluded_by_a_filter_is_reported(self) -> None:
        """Verify exact id excluded by a filter is reported."""
        result = self.search("ui-focus-zoom", type="block", limit=3)
        self.assertEqual(result["excludedExactMatches"], ["local:ui-focus-zoom"])
        self.assertNotIn("local:ui-focus-zoom", self.refs(result))

    def test_empty_results_and_rejected_inputs(self) -> None:
        """Verify empty results and rejected inputs."""
        empty = self.search("zzqxv")
        self.assertEqual((empty["total"], empty["results"], empty["limited"]), (0, [], False))
        with self.assertRaisesRegex(ValueError, "at least one term"):
            self.search("a")
        with self.assertRaisesRegex(ValueError, "limit"):
            self.search("transition", limit=0)
        with self.assertRaisesRegex(ValueError, "status"):
            self.search("transition", status="ported")
        for bad in ("../count-up", "components/count-up", "Count-Up", "", "a b", "count-up\n"):
            with self.assertRaisesRegex(ValueError, "not a valid catalog name"):
                cd.lookup_item(self.catalog, bad)


class ExactLookupTests(_Live):
    def test_integrated_ported_item_separates_declared_from_measured(self) -> None:
        """Verify integrated ported item separates declared from measured."""
        result = cd.lookup_item(self.catalog, "count-up")
        self.assertTrue(result["found"])
        (record,) = result["matches"]
        self.assertEqual(record["provenance"], cd.PROVENANCE_PORTED)
        self.assertEqual(record["upstream"]["name"], "count-up")
        self.assertTrue(record["upstream"]["reference"]["exists"])
        self.assertTrue(record["study"]["port"].startswith("P0"))
        self.assertIsNone(record["upstream"]["declared"]["dimensions"])   # index: none
        self.assertEqual(record["declared"]["dimensions"], [1080, 1920])   # template
        self.assertEqual(record["declared"]["aspectSource"], "template-data-width-height")
        self.assertEqual(record["integration"]["status"], cd.STATUS_MEASURED)
        self.assertEqual(record["integration"]["measured"]["canvas"],
                         caps.capability_matrix()["count-up"]["canvas"])
        self.assertEqual(record["integration"]["qualifiedAspects"], ["9:16"])
        self.assertTrue(any("not qualified at the other aspect" in note
                            for note in record["adaptationNotes"]))
        self.assertEqual(cd.lookup_item(self.catalog, "local:count-up")["matches"], [record])

    def test_known_missing_items_keep_their_distinct_evidence(self) -> None:
        """Verify known missing items keep their distinct evidence."""
        texture = cd.lookup_item(self.catalog, "texture-mask-text")["matches"][0]
        self.assertEqual(texture["integration"]["status"], cd.STATUS_REFERENCE_MISSING)
        self.assertFalse(texture["upstream"]["reference"]["exists"])
        self.assertIsNone(texture["upstream"]["lockKnownMissing"])
        self.assertTrue(texture["study"]["mechanism"].startswith("FILE MISSING"))
        self.assertIn("lock does not record it as missing", " ".join(texture["disagreements"]))
        neon = cd.lookup_item(self.catalog, "lt-neon-border")["matches"][0]
        self.assertEqual(neon["integration"]["status"], cd.STATUS_REFERENCE_MISSING)
        self.assertTrue(neon["upstream"]["lockKnownMissing"].startswith("registry-side"))
        self.assertEqual(neon["disagreements"], [])
        self.assertFalse(cd.lookup_item(self.catalog, "no-such-item-xyz")["found"])

    def test_provenance_is_loaded_not_hardcoded(self) -> None:
        """Verify provenance is loaded not hardcoded."""
        provenance = self.catalog.provenance
        mirror = provenance["mirror"]
        self.assertEqual(mirror["indexRecords"], mirror["itemsListed"])
        missing_on_disk = [r for r in self.catalog.records
                           if r["integration"]["status"] == cd.STATUS_REFERENCE_MISSING]
        self.assertEqual(mirror["referenceSourcesPresent"],
                         mirror["indexRecords"] - len(missing_on_disk))
        self.assertEqual(mirror["itemsInstalled"] != mirror["referenceSourcesPresent"],
                         any("installed" in d for d in provenance["disagreements"]))
        self.assertEqual(provenance["ported"], PORTED_KINDS)
        self.assertEqual(provenance["issues"], [])
        capability = provenance["capability"]
        self.assertTrue(capability["fresh"])
        self.assertEqual(capability["releaseReadyKinds"], len(caps.capability_matrix()))
        self.assertEqual(capability["integratedKinds"], len(composition_kinds()))
        ready = {r["id"] for r in self.catalog.records
                 if r["integration"]["status"] == cd.STATUS_MEASURED}
        self.assertEqual(ready, set(caps.capability_matrix()))


class CallerConsumptionTests(_Live):
    """The existing adapters consume measured kinds; references stay references."""

    def test_measured_kind_flows_into_existing_predicates(self) -> None:
        """Verify measured kind flows into existing predicates."""
        record = cd.lookup_item(self.catalog, "marker-highlight")["matches"][0]
        kind, aspect = record["integration"]["kind"], record["integration"]["measured"]["aspect"]
        self.assertTrue(caps.is_aspect_legal_kind(kind, aspect))
        other = "16:9" if aspect == "9:16" else "9:16"
        self.assertFalse(caps.is_aspect_legal_kind(kind, other))
        self.assertEqual(record["integration"]["qualifiedAspects"], [aspect])

    def test_reference_result_cannot_become_a_scene(self) -> None:
        """Verify reference result cannot become a scene."""
        record = cd.lookup_item(self.catalog, "comparison-split")["matches"][0]
        self.assertEqual(record["integration"]["status"], cd.STATUS_REFERENCE)
        self.assertFalse(caps.is_aspect_legal_kind(record["id"], "16:9"))
        request = CatalogSceneRequest(
            entry={"kind": record["id"], "anchor": "own-screen", "outStart": 0.0,
                   "outEnd": 2.0, "spec": {}},
            scene_id="scene-1", timing={"fps": "30", "startFrame": 0, "endFrameExclusive": 60},
            canvas={"width": 1920, "height": 1080}, provenance={"source": "TEST"})
        with self.assertRaisesRegex(SceneContractError, "lacks fresh measured capability"):
            wrap_catalog_scene(request)


class CliTests(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str]:
        """Capture the actual CLI result and exit status without spawning."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(argv)
        return code, out.getvalue()

    def test_json_and_text_forms(self) -> None:
        """Verify json and text forms."""
        code, out = self._run(["search", "transition", "--limit", "2"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual((payload["returned"], payload["scope"]), (2, cd.SCOPE))
        code, text = self._run(["--format", "text", "lookup", "count-up"])
        self.assertEqual(code, 0)
        self.assertIn("MEASURED 1080x1920 9:16", text)
        self.assertIn("scope: " + cd.SCOPE, text)
        self.assertEqual(self._run(["lookup", "no-such-item-xyz"])[0], 1)
        code, out = self._run(["lookup", "../etc"])
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(out)["ok"])


class RecordedMetadataShapeTests(unittest.TestCase):
    def test_bad_study_shapes_are_reported_and_dropped(self) -> None:
        """Unknown non-text/numeric study claims never become JSON evidence."""
        bad = [("scrubSafe", float("nan")), ("selfContained", float("inf")),
               ("scrubSafe", 1), ("selfContained", []), ("type", []),
               ("variables", [3]), ("mechanism", {"not": "text"}), ("name", "bad\n")]
        rows = [{"name": f"bad-{index}", key: value} for index, (key, value) in enumerate(bad)]
        rows += [{"name": "valid", "type": "component", "variables": ["copy"],
                  "scrubSafe": "conditional: host-driven", "selfContained": False}]
        with patch.object(sources, "_read_json", return_value=rows):
            records, issues = sources.load_study("/TEST-not-opened")
        self.assertEqual(list(records), ["valid"])
        self.assertEqual(len(issues), len(bad))
        self.assertEqual(records["valid"]["scrubSafe"], "conditional: host-driven")
        json.dumps(records, allow_nan=False)

    def test_malformed_lock_fields_are_diagnostic_not_exceptions(self) -> None:
        """Keep valid provenance while dropping invalid fields and missing rows."""
        for malformed in (3, "not-a-list", {"name": "not-a-list"}, False, 0, ""):
            with patch.object(sources, "_read_json", return_value={"knownMissing": malformed}):
                lock, issues = sources.load_lock("/TEST-not-opened")
            self.assertEqual(lock["knownMissing"], {})
            self.assertTrue(issues)
        value = {"itemsListed": float("nan"), "source": {"not": "text"}, "files": True,
                 "knownMissing": [{"name": "bad", "reason": []}, {"name": "valid", "reason": "TEST"}]}
        with patch.object(sources, "_read_json", return_value=value):
            lock, issues = sources.load_lock("/TEST-not-opened")
        self.assertEqual(lock["knownMissing"], {"valid": "TEST"})
        self.assertTrue(all(lock[key] is None for key in ("itemsListed", "source", "files")))
        self.assertEqual(len(issues), 4)
        json.dumps(lock, allow_nan=False)


if __name__ == "__main__":
    unittest.main()

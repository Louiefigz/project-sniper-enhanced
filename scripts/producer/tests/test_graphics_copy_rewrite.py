"""Complete-copy repair stays unresolved without changing spoken timing.

All fixtures are in-memory TEST data. No model, renderer, or filesystem writes.
Fit checks are mechanical and never claim a rewrite is semantically faithful.
"""
from __future__ import annotations

import copy
import unittest

from graphics_copy import fill_list_spec
from plan_lint import Report
from plan_lint_motion import check_graphics_track

COMPLETE = "Keep the original footage until the export passes review"


def beat() -> dict:
    """Return an original requested list with explicit kept-word timing."""
    return {"id": "TEST-required-list", "kind": "whiteboard-list",
            "outStart": 10.0, "outEnd": 16.0, "anchor": "own-screen",
            "needsCopy": True, "spec": {}, "needsOperator": True,
            "anchors": [{"atSec": 0.5, "hint": "First"},
                        {"atSec": 2.0, "hint": "Then"}],
            "rawSpan": COMPLETE, "reason": "Requested source protection",
            "request": {"clauseId": "TEST-clause", "required": True},
            "source": {"wordIds": ["TEST-word-1", "TEST-word-2"]}}


def items(label: str = COMPLETE) -> list[dict]:
    """Return the author's exact ordered selection, not a generated rewrite."""
    return [{"anchorIndex": 0, "label": label},
            {"anchorIndex": 1, "label": "Review the exported video"}]


def pending_choices() -> tuple[dict, list[dict]]:
    """Hold three original obligations, including the final backup instruction."""
    original = beat()
    original["anchors"].append({"atSec": 3.5, "hint": "Finally"})
    selected = items() + [{"anchorIndex": 2, "label": "Keep the backup copy"}]
    pending = fill_list_spec(original, selected, "Protect the source")
    rewritten = copy.deepcopy(selected)
    rewritten[0]["label"] = "Retain footage until export review passes"
    return pending, rewritten


class GraphicsCopyRewriteTests(unittest.TestCase):
    """Repair data preserves copy, provenance and the original chosen anchors."""

    def test_complete_condition_is_retained_not_truncated(self) -> None:
        """The original conditional obligation remains complete and unresolved."""
        original = beat()
        result = fill_list_spec(original, items(), "Protect the source")
        self.assertTrue(result["needsCopy"])
        self.assertEqual(result["spec"], {})
        repair = result["copyRepair"]
        self.assertEqual(repair["kind"], "copy-needs-rewrite")
        self.assertEqual(repair["originalItems"], items())
        self.assertEqual(repair["issues"], [{
            "field": "items[0].label", "originalText": COMPLETE,
            "maxWords": 6, "actualWords": len(COMPLETE.split()),
            "anchorIndex": 0}])
        for key in ("anchors", "rawSpan", "outStart", "outEnd", "request", "source"):
            self.assertEqual(result[key], original[key])

    def test_valid_oversized_item_is_not_discarded_with_an_invalid_neighbor(self) -> None:
        """A missing second valid item cannot turn repair into a non-list drop."""
        selected = [items()[0], {"anchorIndex": 99, "label": "Invalid target"}]
        result = fill_list_spec(beat(), selected)
        self.assertIsNotNone(result)
        self.assertEqual(result["copyRepair"]["originalItems"], selected)
        self.assertTrue(result["needsCopy"])

    def test_oversized_title_retains_every_word(self) -> None:
        """Title fitting follows the same complete-copy repair path."""
        title = "Keep every source until review is complete"
        result = fill_list_spec(beat(), items("Protect original footage"), title)
        self.assertEqual(result["copyRepair"]["originalTitle"], title)
        self.assertEqual(result["copyRepair"]["issues"], [{
            "field": "title", "originalText": title,
            "maxWords": 5, "actualWords": 7}])

    def test_unicode_whitespace_and_original_spelling_are_retained(self) -> None:
        """Word counting is whitespace arithmetic, not language or regex semantics."""
        label = "  Conservez\tles vidéos originales jusqu’à\u2003la validation finale ✅  "
        result = fill_list_spec(beat(), items(label))
        issue = result["copyRepair"]["issues"][0]
        self.assertEqual(issue["originalText"], label)
        self.assertEqual(issue["actualWords"], len(label.split()))
        self.assertEqual(result["copyRepair"]["originalItems"][0]["label"], label)

    def test_exact_word_limits_preserve_punctuation_and_unicode(self) -> None:
        """At-limit copy keeps every token without character slicing."""
        label = "  Gardez les vidéos jusqu’à validation finale.  "
        title = "Protect every original source file"
        result = fill_list_spec(beat(), items(label), title)
        self.assertEqual(result["spec"]["item1"], " ".join(label.split()))
        self.assertEqual(result["spec"]["title"], title)
        self.assertNotIn("copyRepair", result)

    def test_fit_does_not_invent_a_character_limit_or_semantic_approval(self) -> None:
        """A fitting long token is unchanged; later template/semantic checks remain."""
        label = "長" * 500
        result = fill_list_spec(beat(), items(label))
        self.assertEqual(result["spec"]["item1"], label)
        self.assertNotIn("semanticApproved", result)

    def test_repair_is_detached_from_all_original_nested_data(self) -> None:
        """Neither caller mutation nor returned repair mutation rewrites originals."""
        original, selected = beat(), items()
        before = copy.deepcopy((original, selected))
        result = fill_list_spec(original, selected)
        result["anchors"][0]["atSec"] = 99
        result["request"]["required"] = False
        result["source"]["wordIds"].append("TEST-other")
        result["copyRepair"]["originalItems"][0]["label"] = "Changed"
        self.assertEqual((original, selected), before)
        selected[1]["label"] = "Caller changed"
        self.assertEqual(result["copyRepair"]["originalItems"][1]["label"],
                         before[1][1]["label"])

    def test_fitting_retry_clears_only_repair_and_uses_same_anchor_indices(self) -> None:
        """An author-supplied revision retains exact timing, not automatic approval."""
        pending = fill_list_spec(beat(), items())
        previous = copy.deepcopy(pending)
        rewritten = items("Retain footage until export review passes")
        ready = fill_list_spec(pending, rewritten, "Protect the source")
        self.assertNotIn("copyRepair", ready)
        self.assertNotIn("needsCopy", ready)
        self.assertEqual(ready["spec"]["item1"], rewritten[0]["label"])
        self.assertEqual([ready["spec"]["at1"], ready["spec"]["at2"]], [0.5, 2.0])
        self.assertEqual(ready["request"], pending["request"])
        self.assertEqual((ready["outStart"], ready["outEnd"]), (10.0, 16.0))
        self.assertEqual(pending, previous)

    def test_success_shape_matches_existing_merge_ready_contract(self) -> None:
        """A prior successful input keeps exactly its existing candidate shape."""
        result = fill_list_spec(beat(), items("Keep original footage"), "Protect sources")
        expected = {key: value for key, value in beat().items()
                    if key not in ("anchors", "rawSpan", "needsCopy", "spec")}
        expected.update({"spec": {"title": "Protect sources", "item1": "Keep original footage",
                                  "at1": 0.5, "item2": "Review the exported video", "at2": 2.0},
                         "confidence": "medium",
                         "reason": "2 sequence steps → whiteboard-list cutaway "
                                   "(brain-written copy; atN = spoken land times)",
                         "evidence": "Keep original footage → Review the exported video"})
        self.assertEqual(result, expected)

    def test_genuine_non_list_selection_remains_none(self) -> None:
        """No repair issue does not override the author's explicit non-list choice."""
        self.assertIsNone(fill_list_spec(beat(), []))
        self.assertIsNone(fill_list_spec(beat(), items("One real step")[:1]))

    def test_failed_retry_keeps_first_complete_wording_and_latest_fit_issue(self) -> None:
        """Another oversized attempt cannot replace the original meaning reference."""
        pending = fill_list_spec(beat(), items(), "Protect the source")
        retry = "Keep all original footage until every export passes its review"
        result = fill_list_spec(pending, items(retry), "Another title")
        self.assertEqual(result["copyRepair"]["originalItems"], items())
        self.assertEqual(result["copyRepair"]["originalTitle"], "Protect the source")
        self.assertEqual(result["copyRepair"]["issues"][0]["originalText"], retry)
        self.assertTrue(result["needsCopy"])

    def test_insufficient_retry_cannot_discharge_an_existing_repair(self) -> None:
        """Dropping labels is not a successful repair or an implicit treatment waiver."""
        pending = fill_list_spec(beat(), items())
        for selected in ([], items("One fitting step")[:1]):
            result = fill_list_spec(pending, selected)
            self.assertEqual(result, pending)
            self.assertIsNot(result, pending)

    def test_all_fit_issues_survive_a_valid_oversized_item_with_invalid_neighbor(self) -> None:
        """The unresolved title and label are both reported, not shortened or dropped."""
        selected = [items()[0], {"anchorIndex": 99, "label": "Invalid"}]
        title = "Preserve the complete original requested source protection obligation"
        result = fill_list_spec(beat(), selected, title)
        self.assertEqual([row["field"] for row in result["copyRepair"]["issues"]],
                         ["title", "items[0].label"])

    def test_existing_caller_lint_rejects_the_unresolved_candidate(self) -> None:
        """The ordinary lint path cannot admit empty pending copy for rendering."""
        pending = fill_list_spec(beat(), items())
        report = Report()
        check_graphics_track({"graphicsTrack": [pending]}, 30.0, "longform", report)
        self.assertTrue(any("unfilled needsCopy beat" in error for error in report.errors),
                        report.errors)

    def assert_pending_retry(self, pending: dict, selected: list[dict]) -> dict:
        """Changed timing obligations stay detached, unresolved and rejected by real lint."""
        before = copy.deepcopy(pending)
        result = fill_list_spec(pending, selected, "Protect the source")
        self.assertEqual(result, before)
        self.assertIsNot(result, pending)
        self.assertEqual(pending, before)
        report = Report()
        check_graphics_track({"graphicsTrack": [result]}, 30.0, "longform", report)
        self.assertTrue(any("unfilled needsCopy beat" in error for error in report.errors))
        return result

    def test_fitting_retry_cannot_drop_third_original_step(self) -> None:
        """Two surviving valid labels cannot discharge the originally chosen third step."""
        pending, rewritten = pending_choices()
        self.assert_pending_retry(pending, rewritten[:2])

    def test_fitting_retry_cannot_reorder_original_steps(self) -> None:
        """An unchanged set of selected anchors cannot conceal changed row order."""
        pending, rewritten = pending_choices()
        self.assert_pending_retry(pending, [rewritten[2], *rewritten[:2]])

    def test_invalid_neighbor_cannot_hide_original_third_step(self) -> None:
        """A fitting retry cannot erase an obligation by making its anchor invalid."""
        pending, rewritten = pending_choices()
        rewritten[2]["anchorIndex"] = 99
        self.assert_pending_retry(pending, rewritten)

    def test_blank_final_label_cannot_discharge_original_third_step(self) -> None:
        """Whitespace is still a dropped original chosen label, not a successful rewrite."""
        pending, rewritten = pending_choices()
        rewritten[2]["label"] = " \t\n "
        self.assert_pending_retry(pending, rewritten)

    def test_duplicate_anchor_cannot_replace_a_different_original_anchor(self) -> None:
        """Keeping the item count does not permit retiming the final instruction."""
        pending, rewritten = pending_choices()
        rewritten[2]["anchorIndex"] = 1
        self.assert_pending_retry(pending, rewritten)

    def test_original_duplicate_anchor_multiplicity_is_not_erased(self) -> None:
        """Existing authored duplicate choices remain distinct obligations during repair."""
        original = items() + [{"anchorIndex": 1, "label": "Keep the backup copy"}]
        pending = fill_list_spec(beat(), original, "Protect the source")
        self.assert_pending_retry(pending, items("Retain footage until export review passes"))

    def test_exact_original_duplicate_choices_can_complete_repair(self) -> None:
        """This copy-only change does not newly forbid a legacy original anchor sequence."""
        original = items() + [{"anchorIndex": 1, "label": "Keep the backup copy"}]
        pending = fill_list_spec(beat(), original, "Protect the source")
        rewritten = copy.deepcopy(original)
        rewritten[0]["label"] = "Retain footage until export review passes"
        result = fill_list_spec(pending, rewritten, "Protect the source")
        self.assertNotIn("copyRepair", result)
        self.assertEqual([result["spec"][f"at{i}"] for i in (1, 2, 3)], [0.5, 2.0, 2.0])

    def test_failed_anchor_retry_never_rebaselines_original_choices(self) -> None:
        """Successive fitting omissions keep the first full obligation until all choices return."""
        pending, rewritten = pending_choices()
        rejected = self.assert_pending_retry(pending, rewritten[:2])
        rejected = self.assert_pending_retry(rejected, rewritten[1:])
        result = fill_list_spec(rejected, rewritten, "Protect the source")
        self.assertNotIn("copyRepair", result)
        self.assertEqual(result["spec"]["item3"], "Keep the backup copy")
        self.assertEqual(result["spec"]["at3"], 3.5)

    def test_omitted_title_cannot_erase_original_title_repair(self) -> None:
        """Default empty title is not an authored shorter complete formulation."""
        original_title = "Keep every source until review is complete"
        selected = items("Keep originals until review passes")
        pending = fill_list_spec(beat(), selected, original_title)
        result = fill_list_spec(pending, selected)
        self.assertEqual(result, pending)
        self.assertIsNot(result, pending)
        self.assertEqual(result["copyRepair"]["originalTitle"], original_title)


if __name__ == "__main__":
    unittest.main()

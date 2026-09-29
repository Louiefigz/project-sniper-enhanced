"""Role packet scope: applicable-rule retention, feature conditions, index entries and recorded size.

Fixtures are TEST-labelled synthetic plans; no packet here grants or implies any review.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import json
import sys
import unittest
from itertools import product
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import context as entry
from role_packet_catalog import CHECKS, FEATURES, INSTRUCTIONS, OBLIGATIONS, ROLES, WHOLE
from role_packet_native import plan_features, plan_focus
from role_packet_scope import with_reading
from role_packet_sections import base_range, instruction_row, read_instruction
from role_packet_text import render_role_packet
from role_packets import RoleRequest, resolve_role_packet
from _role_packet_fixture import RolePacketFixture, sha

REPO = entry.REPO
CRITICS = ("plan-critic", "motion-critic", "final-critic")
ABSENT = {name: False for name in FEATURES}
PRESENT = {name: True for name in FEATURES}
# Rules a native Short plan critic must always be assigned, whatever the plan uses (document, line prefix).
PLAN_CRITIC_RULES = (
    ("docs/producer/NATIVE_SHORTS_WORKFLOW.md", "### Preserve the actual request before choosing assets"),
    ("docs/producer/NATIVE_SHORTS_WORKFLOW.md", "For an approved Short or batch, follow"),  # P0 adapt: src :641
    ("docs/producer/NATIVE_SHORTS_WORKFLOW.md", "### Author the pacing record"),
    ("docs/producer/NATIVE_SHORTS_WORKFLOW.md", "### Bind the authored story to executable visuals"),
    ("docs/producer/NATIVE_SHORTS_WORKFLOW.md", "### One asset decision across images and video"),
    ("docs/producer/NATIVE_SHORTS_WORKFLOW.md", "Every element of authored extension markup"),
    ("docs/producer/NATIVE_SHORTS_WORKFLOW.md", "For a confirmed caption spelling correction"),
    ("docs/producer/NATIVE_SHORTS_WORKFLOW.md", "For progressive native reveals"),
    ("docs/producer/NATIVE_SHORTS_DEADLINE_BATCH.md", "Run `context.py --role clip-owner`"),  # P0 adapt: src :133
    ("docs/producer/NATIVE_SHORTS_WORKFLOW.md", "Native Shorts stage catalog HTML through"),
    ("docs/producer/NATIVE_SHORTS_WORKFLOW.md", "Native delivery shares dialogue cleanup"),
    ("docs/producer/NATIVE_SHORTS_WORKFLOW.md", "Background music in native Shorts remains unsupported"),
    (".claude/skills/producer/SKILL.md", "Establish who speaks each retained passage"),
    (".claude/skills/producer/SKILL.md", "**Explicit reference targets:**"),
    (".claude/skills/producer/SKILL.md", "   **MANDATORY, before round 1:**"),
    (".claude/skills/producer/SKILL.md", "   - **b. Independent strategy critic"),
    (".claude/skills/producer/SKILL.md", "     - **Claims — VERIFY every claim-bearing card"),
    ("docs/PIPELINE.md", "**September 16 visual-storytelling correction:**"),
    ("docs/PIPELINE.md", "Agent-selected transition effects come from the HyperFrames catalog"),
    ("docs/producer/NATIVE_PREBUILD_STRATEGY_2026-09-10.md", "## Why this Short bypassed the useful structure"),
    ("docs/producer/NATIVE_PREBUILD_STRATEGY_2026-09-10.md", "## Shared planning sequence"),
    ("docs/producer/NATIVE_PREBUILD_STRATEGY_2026-09-10.md", "## Standing directing requirements — September 16, 2026"),
    ("docs/producer/NATIVE_TITLE_CARD_TEMPLATE_2026-09-10.md", "## Exact user-supplied titles"),
    ("docs/producer/NATIVE_TITLE_CARD_TEMPLATE_2026-09-10.md", "## Layout decisions for this change"),
    ("docs/producer/VISUAL_SOURCE_POLICY.md", "## Native source decisions"),
)
# Rules other units add; asserted assigned whenever the document carries them (C3 b3cd114 caption suppressions).
PLAN_CRITIC_RULES_AFTER_MERGE = (
    ("docs/producer/NATIVE_SHORTS_WORKFLOW.md", "For frames where native captions must not draw"),
)


def base_selectors(selector: tuple) -> tuple:
    """The plain heading/range/whole selector underneath a conditional or subtracting one."""
    if selector[0] == "when":
        return base_selectors(selector[2])
    if selector[0] == "except":
        return base_selectors(selector[1])
    return selector


def covered(sections: list[dict]) -> set[int]:
    """Every line number inside the ranges."""
    return {line for row in sections for line in range(row["startLine"], row["endLine"] + 1)}


def assigned_lines(role: str, features: dict | None) -> dict[str, set[int]]:
    """Assigned line numbers per catalog document for one role."""
    return {spec[0]: covered(instruction_row(REPO, spec, features)["sections"]) for spec in INSTRUCTIONS[role]}


def line_of(relative: str, prefix: str) -> int:
    """The unique 1-based line starting with prefix."""
    _sha, lines = read_instruction(REPO / relative)
    found = [index + 1 for index, line in enumerate(lines) if line.startswith(prefix)]
    assert len(found) == 1, f"{relative}: {prefix!r} matched {len(found)} lines"
    return found[0]


def anchor_line(relative: str, anchor: str) -> int | None:
    """The line a check anchor names: a heading, else a unique paragraph start, else a code key."""
    _sha, text = read_instruction(REPO / relative)
    patterns = ((lambda line: line.startswith("#") and line.lstrip("#").strip().startswith(anchor)),
                (lambda line: line.strip().startswith(anchor)), (lambda line: f'"{anchor}": [' in line))
    for pattern in patterns:
        found = [index + 1 for index, line in enumerate(text) if pattern(line)]
        if found:
            return found[0] if len(found) == 1 or pattern is patterns[0] else None
    return None


class RetentionTests(unittest.TestCase):
    """Exclusions never drop an applicable rule, and every one is recorded with its reason."""

    def test_every_selector_resolves_whether_features_are_present_absent_or_unknown(self) -> None:
        """Excluded sections are still resolved, so a renamed section fails closed in every case."""
        for (role, spec), features in product(((role, spec) for role in ROLES for spec in INSTRUCTIONS[role]),
                                              (None, ABSENT, PRESENT)):
            row = instruction_row(REPO, spec, features)
            self.assertTrue(all(item["reason"] for item in row["excluded"]), f"{role} {spec[0]}")

    def test_assigned_plus_excluded_is_exactly_the_selected_sections(self) -> None:
        """Nothing is silently dropped: every selected line is either assigned or excluded with a reason, never both."""
        for role in CRITICS:
            for spec in INSTRUCTIONS[role]:
                _sha, lines = read_instruction(REPO / spec[0])
                selectors = (("whole",),) if spec[1] == WHOLE else spec[1]
                selected = covered([base_range(lines, base_selectors(item)) for item in selectors])
                row = instruction_row(REPO, spec, ABSENT)
                kept, dropped = covered(row["sections"]), covered(row["excluded"])
                self.assertFalse(kept & dropped, f"{role} {spec[0]}")
                self.assertEqual(kept | dropped, selected, f"{role} {spec[0]}")

    def test_plan_critic_keeps_every_named_rule_even_when_no_feature_is_used(self) -> None:
        """The rules a native Short plan review applies stay assigned with every feature absent."""
        lines = assigned_lines("plan-critic", ABSENT)
        for relative, prefix in PLAN_CRITIC_RULES:
            self.assertIn(line_of(relative, prefix), lines[relative], f"{relative}: {prefix}")
        for relative, prefix in PLAN_CRITIC_RULES_AFTER_MERGE:
            present = [index + 1 for index, line in enumerate(read_instruction(REPO / relative)[1]) if line.startswith(prefix)]
            self.assertTrue(all(number in lines[relative] for number in present), f"{relative}: {prefix}")

    def test_check_sources_point_at_assigned_sections(self) -> None:
        """Every check anchor into a governing file (heading, unique paragraph or code key) is assigned."""
        checked, unresolved = 0, set()
        assigned = {role: assigned_lines(role, ABSENT) for role in CRITICS}
        cited = [(role, identifier, part) for role in CRITICS for identifier, _text, source in CHECKS[role]
                 for part in source.split("; ") if part.partition("#")[0] in assigned[role] and "#" in part]
        for role, identifier, part in cited:
            relative, _sep, anchor = part.partition("#")
            line = anchor_line(relative, anchor)
            if line is None:
                unresolved.add(part)
                continue
            checked += 1
            self.assertIn(line, assigned[role][relative], f"{role} {identifier}: {part}")
        self.assertGreaterEqual(checked, 25)
        self.assertEqual(unresolved, {".claude/skills/producer/SKILL.md#4b"})

    def test_plan_critic_drops_long_palmier_and_retired_route_text_only(self) -> None:
        """No Palmier doctrine, Long export or retired-app control text stays assigned in the route documents."""
        lines = assigned_lines("plan-critic", ABSENT)
        for relative in ("docs/PIPELINE.md", "docs/producer/NATIVE_SHORTS_WORKFLOW.md",
                         "docs/producer/NATIVE_PREBUILD_STRATEGY_2026-09-10.md"):
            _sha, text = read_instruction(REPO / relative)
            leaked = [number for number in lines[relative] if any(word in text[number - 1] for word in (
                "Palmier", "New native long exports", "10-minute video", "The optional app offers"))]
            self.assertEqual(leaked, [], relative)

    def test_conditions_follow_the_subject_and_unknown_keeps_sections(self) -> None:
        """Each feature adds its sections when used, removes them when unused and keeps them when unknown."""
        cases = (("plan-critic", "reference-route", "docs/producer/REFERENCE_SHOT_REUSE.md", "## When to use this"),
                 ("plan-critic", "related-group", "docs/producer/NATIVE_SHORTS_WORKFLOW.md",
                  "### Prepare related Shorts as one group"),
                 ("plan-critic", "source-burned-captions", "docs/producer/NATIVE_SHORTS_WORKFLOW.md",
                  "For an inspected source with existing burned-in captions"),
                 ("plan-critic", "catalog-staging", "docs/producer/VISUAL_SOURCE_POLICY.md",
                  "## Staging catalog components in a native Short"),
                 ("motion-critic", "supporting-media", "docs/producer/WEB_BROLL_WORKFLOW.md", "### Bind the selected shot"))
        for role, feature, relative, prefix in cases:
            line = line_of(relative, prefix)
            used = assigned_lines(role, {**ABSENT, feature: True})[relative]
            unused = instruction_row(REPO, next(spec for spec in INSTRUCTIONS[role] if spec[0] == relative),
                                     {**PRESENT, feature: False})
            unknown = assigned_lines(role, {**ABSENT, feature: None})[relative]
            self.assertIn(line, used, feature)
            self.assertIn(line, unknown, feature)
            self.assertNotIn(line, covered(unused["sections"]), feature)
            self.assertIn(feature, {item.get("condition") for item in unused["excluded"]})

    def test_owner_reads_whole_documents_without_conditions(self) -> None:
        """The author's packet is not scoped: the adapter requires the whole skill and workflow."""
        for spec in INSTRUCTIONS["clip-owner"]:
            row = instruction_row(REPO, spec, None)
            self.assertEqual(row["excluded"], [], spec[0])


class FeatureTests(RolePacketFixture):
    """Plan features and index entries are located facts, never judgments."""

    def request(self, value: dict) -> dict:
        """A request packet binding for the plan."""
        file = self.write("requests/features/SHORT-REQUEST.json", value)
        return {"path": str(file), "sha256": sha(file)}

    def test_features_come_from_plan_fields_and_the_bound_request(self) -> None:
        """Unbound requests leave request-derived features unknown; explicit fields decide the rest."""
        plain = {"canvas": {}, "assets": []}
        self.assertEqual(plan_features(plain), {"catalog-staging": False, "reference-route": None, "related-group": None,
                                                "source-burned-captions": False, "caption-suppressions": False,
                                                "supporting-media": False})
        rich = {"canvas": {"captionMode": "source-burned", "titleCard": {}},
                "assets": [{"role": "supporting-video"}], "visualSources": {"decisions": [{"route": "catalog"}]},
                "requestPacket": self.request({"selectedReferences": [], "relatedStyleContext": {"TEST": 1}})}
        self.assertEqual(plan_features(rich), {"catalog-staging": True, "reference-route": False, "related-group": True,
                                               "source-burned-captions": True, "caption-suppressions": False,
                                               "supporting-media": True})
        routed = {**rich, "visualSources": {"decisions": [{"route": "reference"}]}}
        self.assertTrue(plan_features(routed)["reference-route"])

    def test_index_entries_are_located_by_exact_id(self) -> None:
        """Mounted, decided and inspected catalog ids and title anchors become pointers; absent ids are reported."""
        index = self.write("requests/x/CATALOG-INDEX.json", {"items": [{"id": "TEST-a"}, {"id": "TEST-b"}, {"id": "TEST-c"}]})
        library = self.write("requests/x/DIRECTOR-LIBRARY.json", {"anchors": [{"id": "TEST-hook"}, {"id": "TEST-card"}]})
        rows = [{"key": "request:CATALOG-INDEX.json", "path": str(index)},
                {"key": "request:DIRECTOR-LIBRARY.json", "path": str(library)}, {"key": "asset-0-runtime", "path": "x"}]
        plan = {"catalogFiles": [{"catalogId": "TEST-b"}, {"catalogId": "TEST-missing"}],
                "catalogTitle": {"copy": {"anchor": "TEST-hook"}}, "canvas": {"titleCard": {"copy": {"anchor": "TEST-card"}}},
                "visualSources": {"decisions": [{"route": "catalog", "catalog": [{"id": "TEST-a"}]}]}}
        catalog, director, runtime = with_reading(rows, plan_focus(plan))
        self.assertEqual((catalog["read"], [row["pointer"] for row in catalog["entries"]], catalog["missingEntries"]),
                         ("entries", ["/items/0", "/items/1"], ["TEST-missing"]))
        self.assertEqual([row["pointer"] for row in director["entries"]], ["/anchors/0", "/anchors/1"])
        self.assertEqual(runtime["read"], "bound")
        custom = {**plan, "visualSources": {"decisions": [{"route": "custom", "inspected": [{"id": "TEST-c"}]}]}}
        searched = with_reading(rows[:1], plan_focus(custom))[0]
        self.assertEqual((searched["read"], [row["id"] for row in searched["entries"]]), ("inspect", ["TEST-b", "TEST-c"]))
        self.assertEqual(with_reading(rows[:1], plan_focus({"visualSources": {"decisions": []}}))[0]["read"], "bound")
        self.assertEqual(with_reading(rows[:1], plan_focus({}))[0]["read"], "inspect")
        self.assertEqual(with_reading(rows[:1], None)[0]["read"], "inspect")


class SizeTests(RolePacketFixture):
    """Packets record their own size and state their obligations."""

    def test_packet_records_its_exact_size_and_assignment(self) -> None:
        """packetBytes equals the published file; section and token totals add up; the briefing prints them."""
        result = resolve_role_packet(RoleRequest(role="plan-critic", plan=str(self.plan())), REPO)
        packet, published = result["packet"], result["published"]
        size = packet["size"]
        self.assertEqual(size["packetBytes"], Path(published["packet"]).stat().st_size)
        self.assertEqual(size["instructions"]["sections"], sum(len(row["sections"]) for row in packet["instructions"]))
        estimate = size["estimatedReadingTokens"]
        self.assertEqual(estimate["total"], estimate["packet"] + estimate["instructions"] + estimate["artifacts"])
        self.assertGreater(size["instructions"]["excludedSections"], 0)
        self.assertEqual(json.loads(Path(published["packet"]).read_text())["size"], size)
        text = render_role_packet(packet, published)
        self.assertIn("Size: packet", text)
        self.assertIn("Not assigned to this role and subject", text)

    def test_every_packet_states_obligations_backed_by_its_checks(self) -> None:
        """Independence, source inspection and playback/listening are explicit and cite real checks."""
        for role in ROLES:
            self.assertEqual(set(OBLIGATIONS[role]), {"independence", "sourceInspection", "playbackListening"}, role)
            identifiers = {row[0] for row in CHECKS[role]}
            for statement, checks in OBLIGATIONS[role].values():
                self.assertTrue(statement and set(checks) <= identifiers, role)
        packet = resolve_role_packet(RoleRequest(role="plan-critic", plan=str(self.plan())), REPO)["packet"]
        self.assertEqual(packet["obligations"]["independence"]["checks"], ["PC-13"])


if __name__ == "__main__":
    unittest.main()

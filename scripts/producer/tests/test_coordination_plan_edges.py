"""Edges of the P3a plan record that X211 named (MASTER-PLAN M-081): exact derived ranges, the motion end pose, region
verdicts, single reads, depth, malformed homes, and the S2 edge cases. Each test names the review mutant it kills
(REVIEW.md §4, V1-V18). TEST data only; no child process.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _coordination_fixture import BATCH, TASK, UNIT, PlanFixture, authored, long_record, pin_of
from role_packet_native import plan_hash
from studio.native_short_regions import DERIVATION
from studio.production.coordination_catalog import RESPONSIBILITIES
from studio.production.plan_fields import nesting_problem, raw_depth
from studio.production.plan_record import (
    affected_sections, approved_content_problem, classify, changed_entries, homes_problem, read_plan_record, task_slice,
    validate_plan_record,
)
from studio.production.plan_short_projection import derived_problem, short_sections

RANGES = {('graphics', 'region-0'): [15, 45], ('graphics', 'title-card'): [0, 30], ('graphics', 'text-0'): [30, 60],
          ('graphics', 'shape-0'): [40, 50], ('graphics', 'motion-0'): [32, 60], ('graphics', 'visual-sources'): None,
          ('captions', 'group-0'): [0, 45], ('captions', 'group-1'): [45, 60], ('captions', 'caption-style'): None,
          ('story', 'beat-0'): [0, 45], ('story', 'beat-1'): [45, 60], ('holds', 'scene-0'): [0, 45],
          ('holds', 'scene-1'): [45, 60], ('transitions', 'boundary-0'): [0, 60], ('framing', 'view-0'): [0, 45],
          ('framing', 'view-1'): [45, 60], ('framing', 'speaker-evidence'): None, ('audio', 'audio-finishing'): None,
          ('sourceFacts', 'interval-1-0'): [0, 45], ('sourceFacts', 'interval-2-1'): [45, 60]}
UNPROVEN = {**UNIT, 'isolation': {'status': 'global', 'reason': 'TEST isolation not proven'}}
SECTIONS = ('story', 'holds', 'framing', 'captions', 'graphics', 'transitions', 'audio', 'sourceFacts')


def refused(test: unittest.TestCase, record: dict, words: str) -> None:
    """``validate_plan_record`` refuses ``record`` with ``words`` in its named refusal."""
    with test.assertRaises(ValueError) as caught:
        validate_plan_record(record)
    test.assertIn(words, str(caught.exception))
    test.assertTrue(str(caught.exception).startswith('Coordination plan: '))


class Case(PlanFixture):
    """A derived version 1 Short record with sealed evidence."""

    def setUp(self) -> None:
        """The plan, its sealed evidence, its project and its record."""
        super().setUp()
        self.plan = self.native_plan()
        self.evidence = self.sealed_v2()
        self.homes = self.project(self.plan, evidence=self.evidence)
        self.record = self.short_record(self.homes)

    def mapped(self, name: str, units: list[dict], schema: int = 2) -> dict:
        """Homes of a project whose pinned region map holds ``units`` (a TEST rewrite of the generated map)."""
        homes = self.project(self.plan, name=name, evidence=self.evidence)
        file = Path(homes['project']) / 'REVIEW-REGIONS.json'
        file.write_text(json.dumps({'schemaVersion': schema, 'derivation': DERIVATION, 'units': units}))
        return {**homes, 'regions': pin_of(file)}


class Ranges(Case):
    """Every derived entry's frame range (kills V3, V4, V6 and the round-1 motion range)."""

    def test_every_derived_range_is_exact(self) -> None:
        """Title card, cues, motion through its held end pose, caption groups, beats, scenes, views and facts."""
        found = {(section, row['id']): row['range'] for section in SECTIONS for row in self.record[section]}
        self.assertEqual({key: found.get(key, KeyError) for key in RANGES}, RANGES)

    def test_a_motion_end_pose_change_moves_frames_after_the_tween(self) -> None:
        """X211(5): a changed end pose shows from the tween's end to the target's end, so a [45, 60] scope moves."""
        plan = copy.deepcopy(self.plan)
        plan['canvas']['motion'][0]['to']['opacity'] = 0.5
        after = self.short_record(self.project(plan, name='pose', evidence=self.evidence))
        late = {'range': [45, 60], 'entryIds': None}
        self.assertNotEqual(task_slice(self.record, ('graphics-motion',), late), task_slice(after, ('graphics-motion',), late))
        self.assertEqual((classify(self.record, after), [row['id'] for row in changed_entries(self.record, after)]),
                         ('local', ['motion-0']))


    def test_a_plan_without_beats_has_one_beat_holding_every_word(self) -> None:
        """No pacing beats derive beat-0 over the whole clock with every kept word (V16)."""
        plan = copy.deepcopy(self.plan)
        plan['strategy']['pacing']['beats'] = []
        story = self.short_record(self.project(plan, name='beatless', evidence=self.evidence))['story']
        self.assertEqual([(row['id'], row['range'], row['occurrenceIds']) for row in story], [('beat-0', [0, 60], [0, 1, 2])])


class Regions(Case):
    """A region's recorded verdict and its one pinned read (kills V1, V8; X211 minor)."""

    def test_an_unproven_region_is_a_global_entry(self) -> None:
        """A region whose map says ``global`` is a global graphics entry, and its composition change is global (V1)."""
        record = self.short_record(self.mapped('unproven-a', [UNPROVEN]))
        self.assertEqual({row['id']: row for row in record['graphics']}['region-0']['isolation'], 'global')
        with self.staged({'lower-third.html': '<div data-hf-reveal="0.6">TEST lower third</div>'}):
            after = self.short_record(self.mapped('unproven-b', [UNPROVEN]))
        self.assertEqual(classify(record, after), 'global')

    def test_the_derivation_reads_the_pinned_region_bytes_once(self) -> None:
        """No second unpinned read: ``region_map`` is never called, and bytes changed after the pin are refused."""
        with mock.patch('studio.native_short_regions.region_map', side_effect=AssertionError('second read')):
            self.assertEqual(short_sections(self.homes)['graphics'], self.record['graphics'])
        file = Path(self.homes['regions']['path'])
        file.write_text(json.dumps(json.loads(file.read_text()), indent=1))
        with self.assertRaisesRegex(ValueError, '^Coordination plan: derived: '):
            short_sections(self.homes)

    def test_the_region_map_header_and_rows_are_checked(self) -> None:
        """A map of another schema, and a unit that is not its composition's actual mount, are refused."""
        with self.assertRaisesRegex(ValueError, 'derived: invalid native Short review region map'):
            short_sections(self.mapped('schema', [UNIT], schema=1))
        with self.assertRaisesRegex(ValueError, '^Coordination plan: derived: .*review region must cover'):
            short_sections(self.mapped('mount', [{**UNIT, 'startFrame': 14}]))

    def test_the_regions_pin_names_the_project_file(self) -> None:
        """An identical copy of the map pinned from elsewhere is refused by path (V8)."""
        copied = self.root / 'elsewhere' / 'REVIEW-REGIONS.json'
        copied.parent.mkdir()
        copied.write_bytes(Path(self.homes['regions']['path']).read_bytes())
        refused(self, {**self.record, 'homes': {**self.homes, 'regions': pin_of(copied)}},
                'regions must be <project>/REVIEW-REGIONS.json')


class Homes(Case):
    """Approved content, malformed bindings and a missing native plan (kills V7; X211 minor; MINOR-11)."""

    def test_an_approved_content_change_is_global(self) -> None:
        """Another approval (here a new title) moves every slice (V7)."""
        after = self.short_record(self.homes, row=self.approval_row(title='TEST other title'))
        self.assertEqual((classify(self.record, after), len(changed_entries(self.record, after))), ('global', 0))

    def test_a_malformed_evidence_binding_is_refused_by_name(self) -> None:
        """``homes_problem`` names a non-object ``sharedEvidence`` in the native plan instead of raising."""
        file = Path(self.homes['nativePlan']['path'])
        native = {**json.loads(file.read_text()), 'sharedEvidence': 'TEST not a binding'}
        file.write_text(json.dumps(native))
        homes = {**self.homes, 'nativePlan': pin_of(file), 'planHash': plan_hash(native)}
        self.assertIn("the native plan's sharedEvidence binding is malformed", homes_problem({**self.record, 'homes': homes}))

    def test_a_short_without_a_native_plan_is_refused(self) -> None:
        """A Short whose ``homes.nativePlan`` is null is refused by the shape check (S2 edge case)."""
        refused(self, {**self.record, 'homes': {**self.homes, 'nativePlan': None}}, 'Coordination plan: homes')


class Depth(unittest.TestCase):
    """The nesting bound replaces ``RecursionError`` with a named refusal (X211 minor, MINOR-8)."""

    def test_validation_refuses_deep_nesting_by_name(self) -> None:
        """A 100,000-deep value is refused as ``shape`` without recursing."""
        deep: list = []
        for _ in range(100_000):
            deep = [deep]
        refused(self, {**long_record(), 'decisions': deep}, 'Coordination plan: shape: the record')

    def test_reading_refuses_deep_nesting_before_parsing(self) -> None:
        """200,000 ``[`` (under the size bound) are refused as ``read`` before ``json.loads``."""
        file = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve() / 'plan.json'
        file.write_bytes(b'[' * 200_000)
        with self.assertRaisesRegex(ValueError, 'Coordination plan: read: plan record nests deeper than 32 levels'):
            read_plan_record(pin_of(file))

    def test_the_bound_admits_its_limit(self) -> None:
        """32 levels pass and 33 are refused, for values and for bytes."""
        value: list = []
        for _ in range(31):
            value = [value]
        self.assertEqual((nesting_problem(value, 32), raw_depth(json.dumps(value).encode())), (None, 32))
        self.assertEqual(nesting_problem([value], 32), 'nests deeper than 32 levels')

    def test_brackets_inside_strings_do_not_count(self) -> None:
        """``raw_depth`` counts structure only."""
        self.assertEqual((raw_depth(b'{"a":"[[[[\\"]]"}'), raw_depth(b'[[{}]]')), (1, 3))


class LongEdges(unittest.TestCase):
    """Long-record checks that only the reviewer's mutants reached (kills V9-V12, V14, V15, V18; MINOR-11)."""

    def test_parent_digest_and_frame_rate_shape(self) -> None:
        """A parent whose sha256 is not 64-hex, and a ``30/1/1`` rate, are refused (V9, V10)."""
        later = {'version': 2, 'parent': {'version': 1, 'sha256': 'TEST'}, 'changeClass': 'local'}
        refused(self, {**long_record(), **later}, 'Coordination plan: parent')
        refused(self, {**long_record(), 'clock': {'frameRate': '30/1/1', 'totalFrames': 300}}, 'Coordination plan: clock')

    def test_speaker_text_bound(self) -> None:
        """A 120-byte speaker passes; 121 bytes are refused (V11)."""
        fact = {'id': 's1', 'range': [0, 10], 'certainty': 'probable', 'basis': 'visual-and-stereo'}
        validate_plan_record({**long_record(), 'sourceFacts': [authored(**fact, speaker='S' * 120)]})
        refused(self, {**long_record(), 'sourceFacts': [authored(**fact, speaker='S' * 121)]}, 'Coordination plan: sourceFacts')

    def test_long_approved_content_names_the_output_identity(self) -> None:
        """A Long names its output's identity; another identity is refused (V12)."""
        authority = {'batchId': BATCH, 'status': 'active', 'clips': {'L1': {'output': {'identity': 'b' * 64}}}}
        self.assertIsNone(approved_content_problem(authority, long_record()))
        other = {**authority, 'clips': {'L1': {'output': {'identity': 'c' * 64}}}}
        self.assertIn('does not name the output identity', approved_content_problem(other, long_record()))

    def test_story_tiles_the_clock(self) -> None:
        """Beats with a gap are refused (V14)."""
        story = [authored(id=f'beat-{key}', range=span, occurrenceIds=None, purpose='TEST')
                 for key, span in zip('ABC', ([0, 100], [110, 200], [200, 300]))]
        refused(self, {**long_record(), 'story': story}, 'Coordination plan: story')

    def test_derived_sections_are_a_short_check_only(self) -> None:
        """A Long has no executable home, so ``derived_problem`` is None (V15)."""
        self.assertIsNone(derived_problem(long_record()))

    def test_plan_inputs_are_pins(self) -> None:
        """An input that is not an exact-byte pin is refused (V18)."""
        refused(self, {**long_record(), 'inputs': [{'path': 'relative.json', 'sha256': 'TEST'}]}, 'Coordination plan: inputs')

    def test_a_one_frame_long(self) -> None:
        """totalFrames 1 with one section and one beat is valid; 0 frames are refused (S2 edge case)."""
        plan = one_section_long(1)
        validate_plan_record(plan)
        refused(self, {**plan, 'clock': {'frameRate': '30/1', 'totalFrames': 0}}, 'Coordination plan: clock')

    def test_one_section_over_the_whole_clock(self) -> None:
        """A Long with one section is valid, and a graphics change affects exactly that section (S2 edge case)."""
        plan = one_section_long(300)
        validate_plan_record(plan)
        fields = {key: value for key, value in plan['graphics'][0].items() if key != 'digest'}
        after = {**plan, 'graphics': [authored(**{**fields, 'lane': 'upper'})]}
        self.assertEqual(affected_sections(plan, after), {'A'})


def one_section_long(total: int) -> dict:
    """A TEST Long with one section and one beat over the whole clock (a graphic only when it fits)."""
    plan = long_record()
    plan.update(clock={'frameRate': '30/1', 'totalFrames': total}, sections=[{'id': 'A', 'range': [0, total]}],
                story=[authored(id='beat-A', range=[0, total], occurrenceIds=None, purpose='TEST whole clock')],
                transitions=[], ownership=[{'responsibility': name, 'range': [0, total], 'owner': {'task': TASK}}
                                           for name in RESPONSIBILITIES])
    if total < 60:
        plan.update(graphics=[], holds=[])
    return plan

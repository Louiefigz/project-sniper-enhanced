"""P3a S2 (MASTER-PLAN M-081) §4.0.6: slices, ``reads``, change classes and Long section rules. TEST data only.

Split from ``test_coordination_plan_record`` for the 300-line rule; M-081's Verify names both.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import copy
import unittest
from pathlib import Path

from _coordination_fixture import PlanFixture, authored, long_record
from studio.production.coordination_catalog import RESPONSIBILITIES, reads
from studio.production.plan_record import (
    affected_sections, changed_entries, classify, slice_digest, task_slice, validate_plan_record,
)

WHOLE = {'range': None, 'entryIds': None}


def moved(before: dict, after: dict, scope: dict = WHOLE) -> set[str]:
    """Responsibilities whose slice over ``scope`` differs between two records."""
    return {name for name in RESPONSIBILITIES if slice_digest(before, name, scope) != slice_digest(after, name, scope)}


class Slices(PlanFixture):
    """Local changes move only their owners' slices; global ones move every slice."""

    def setUp(self) -> None:
        """A derived version 1 Short record with sealed evidence."""
        super().setUp()
        self.plan = self.native_plan()
        self.evidence = self.sealed_v2()
        self.record = self.short_record(self.project(self.plan, evidence=self.evidence))

    def test_local_change_changes_only_owner_slices(self) -> None:
        """A new reveal cue in region unit lower-third (frames 15-45) moves graphics-motion there and nothing else."""
        homes = self.project(self.plan, name='cue', evidence=self.evidence)
        (Path(homes['project']) / 'compositions' / 'lower-third.html').write_text('<div data-hf-reveal="0.6">TEST</div>')
        after = self.short_record(homes)
        self.assertEqual(classify(self.record, after), 'local')
        self.assertEqual(changed_entries(self.record, after),
                         [{'section': 'graphics', 'id': 'region-0', 'responsibility': 'graphics-motion', 'range': [15, 45]}])
        self.assertEqual(moved(self.record, after), {'graphics-motion'})
        self.assertEqual(moved(self.record, after, {'range': [45, 60], 'entryIds': None}), set())

    def test_depends_closure(self) -> None:
        """A sourceFacts change moves a graphics-motion task's slice (DEPENDS) but not an audio-only task's."""
        after = copy.deepcopy(self.record)
        after['sourceFacts'][0]['digest'] = 'f' * 64
        self.assertNotEqual(task_slice(self.record, ('graphics-motion',), WHOLE), task_slice(after, ('graphics-motion',), WHOLE))
        self.assertEqual(task_slice(self.record, ('audio-dialogue',), WHOLE), task_slice(after, ('audio-dialogue',), WHOLE))

    def test_scope_entry_ids_select_entries_outside_the_range(self) -> None:
        """An entry listed in ``scope.entryIds`` counts even outside ``scope.range``."""
        after = copy.deepcopy(self.record)
        after['framing'][1]['digest'] = 'f' * 64
        narrow = {'range': [0, 10], 'entryIds': None}
        self.assertEqual(moved(self.record, after, narrow), set())
        self.assertEqual(moved(self.record, after, {**narrow, 'entryIds': ['view-1']}), {'source-speaker-fidelity'})

    def test_global_entry_changes_every_slice(self) -> None:
        """A global graphics entry (an unlisted canvas key) moves every responsibility's slice."""
        plan = copy.deepcopy(self.plan)
        plan['canvas']['background'] = '#111111'
        after = self.short_record(self.project(plan, name='background', evidence=self.evidence))
        self.assertEqual(classify(self.record, after), 'global')
        self.assertEqual(moved(self.record, after, {'range': [0, 1], 'entryIds': None}), set(RESPONSIBILITIES))

    def test_story_change_is_global(self) -> None:
        """A beat change is global: every slice moves."""
        after = copy.deepcopy(self.record)
        after['story'][1]['digest'] = 'f' * 64
        self.assertEqual(classify(self.record, after), 'global')
        self.assertEqual(moved(self.record, after), set(RESPONSIBILITIES))

    def test_classify_initial_local_global(self) -> None:
        """No parent is initial; an unchanged global digest is local; a changed clock is global."""
        self.assertEqual(classify(None, self.record), 'initial')
        self.assertEqual(classify(self.record, copy.deepcopy(self.record)), 'local')
        self.assertEqual(classify(self.record, {**self.record, 'clock': {'frameRate': '30/1', 'totalFrames': 61}}), 'global')


class Reads(unittest.TestCase):
    """``reads`` is one step of DEPENDS; structural roles read everything."""

    def test_reads_rule(self) -> None:
        """graphics-motion reads the four responsibilities whose change affects it; audio reads transitions."""
        self.assertEqual(reads(('graphics-motion',)), frozenset(
            {'graphics-motion', 'source-speaker-fidelity', 'transitions', 'captions-timing', 'story-pacing'}))
        self.assertEqual(reads(('audio-dialogue',)), frozenset({'audio-dialogue', 'transitions', 'story-pacing'}))
        self.assertEqual(reads(('story-pacing',)), frozenset({'story-pacing'}))
        self.assertEqual(reads(('independent-review',)), frozenset(RESPONSIBILITIES))
        with self.assertRaisesRegex(ValueError, 'unknown names'):
            reads(('graphics',))


class Long(unittest.TestCase):
    """A Long's authored sections, cross-section transitions and affected sections."""

    def refused(self, record: dict, words: str) -> None:
        """Refused with ``words`` in the message."""
        with self.assertRaises(ValueError) as caught:
            validate_plan_record(record)
        self.assertIn(words, str(caught.exception))

    def test_sections_contiguous(self) -> None:
        """Three contiguous sections are valid; a gap, a fourth section and a Short-style speech are refused."""
        validate_plan_record(long_record())
        record = long_record()
        record['sections'][1]['range'] = [110, 200]
        self.refused(record, 'rows are not contiguous at frame 100')
        record = long_record()
        record['sections'].append({'id': 'D', 'range': [300, 300]})
        self.refused(record, 'sections')
        self.refused({**long_record(), 'speech': {}}, 'a Long has no derived speech')

    def test_cross_section_transition_owned_by_integration(self) -> None:
        """A transition across A|B owned by another task is refused; inside one section it may be delegated."""
        record = long_record()
        record['transitions'] = [authored(id='t-ab', boundaryFrame=100, range=[90, 110], outgoing='A', incoming='B',
                                          state='planned', owner={'section': 'A'})]
        self.refused(record, 't-ab crosses a section boundary, so the integration task owns it')
        record['transitions'] = [authored(id='t-a', boundaryFrame=50, range=[40, 60], outgoing='A', incoming='A',
                                          state='planned', owner={'section': 'A'})]
        validate_plan_record(record)

    def test_affected_sections(self) -> None:
        """A graphic in A affects A; a whole-output caption rule affects every section; a story change is global."""
        before = long_record()
        after = copy.deepcopy(before)
        after['graphics'][0]['digest'] = 'f' * 64
        self.assertEqual(affected_sections(before, after), {'A'})
        after = copy.deepcopy(before)
        after['captions'][0]['digest'] = 'f' * 64
        self.assertEqual(affected_sections(before, after), {'A', 'B', 'C'})
        self.assertEqual(affected_sections(before, copy.deepcopy(before)), set())

    def test_authored_digests_recompute(self) -> None:
        """An authored entry whose digest does not recompute is refused."""
        record = long_record()
        record['holds'][0]['minimumFrames'] = 21
        self.refused(record, "entries ['holds/h1'] do not recompute")


class LongGraphics(unittest.TestCase):
    """A Long graphics rule's reveal and feasibility rules (§4.0.2)."""

    def rule(self, **changes: object) -> dict:
        """The record with its graphics rule changed (digest recomputed)."""
        record = long_record()
        fields = {key: value for key, value in record['graphics'][0].items() if key != 'digest'}
        record['graphics'][0] = authored(**{**fields, **changes})
        return record

    def test_reveal_outside_range_refused(self) -> None:
        """``a <= revealFrame < b``: frames 9 and 60 are outside [10, 60)."""
        for frame in (9, 60):
            with self.subTest(frame=frame), self.assertRaisesRegex(ValueError, 'g1 reveal must lie in'):
                validate_plan_record(self.rule(revealFrame=frame))
        validate_plan_record(self.rule(revealFrame=59))

    def test_unverified_feasibility_needs_unresolved_row(self) -> None:
        """An unverified graphic needs a graphics-motion gap blocking final or execution over its frames."""
        record = self.rule(feasibility='unverified')
        with self.assertRaisesRegex(ValueError, 'g1 is unverified'):
            validate_plan_record(record)
        gap = {'id': 'u1', 'responsibility': 'graphics-motion', 'range': [0, 100], 'statement': 'TEST gap',
               'blocks': 'final', 'decisionId': 'd1'}
        validate_plan_record({**record, 'unresolved': [gap]})
        for change in ({'blocks': 'none'}, {'responsibility': 'audio-dialogue'}, {'range': [20, 100]}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'g1 is unverified'):
                validate_plan_record({**record, 'unresolved': [{**gap, **change}]})

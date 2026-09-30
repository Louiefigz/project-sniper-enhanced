"""P3a S2 (MASTER-PLAN M-081): every stated bound and field rule of the plan record (§4.0.1, §4.0.2). TEST data only.

Split from ``test_coordination_plan_record`` for the 300-line rule; M-081's Verify names it too.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import unittest

from _coordination_fixture import TASK, authored, long_record
from studio.production.coordination_catalog import (
    COORDINATION_LIMITS, LONG_REPAIR_RESERVE, PACKET_ROLES, RESPONSIBILITIES, SHORT_REPAIR_RESERVE,
)
from studio.production.plan_record import validate_plan_record


def tiled(count: int, total: int = 300) -> list[dict]:
    """``count`` authored beats tiling [0, total)."""
    edges = [index * total // count for index in range(count)] + [total]
    return [authored(id=f'beat-{index}', range=[edges[index], edges[index + 1]], occurrenceIds=None, purpose=None)
            for index in range(count)]


def rows_of(section: str, count: int) -> list[dict]:
    """``count`` valid rows of a list section of the TEST Long record."""
    if section == 'story':
        return tiled(count)
    build = {
        'captions': lambda i: authored(id=f'c{i}', range=None, rule='TEST rule'),
        'graphics': lambda i: authored(id=f'gx{i}', lane=f'l{i}', range=[10, 60], revealFrame=20, hiddenUntilReveal=True,
                                       source={'kind': 'catalog', 'ref': 'TEST'}, feasibility='feasible', evidence=[],
                                       isolation='scoped'),
        'holds': lambda i: authored(id=f'h{i}', subject='g1', range=[10, 60], minimumFrames=1),
        'transitions': lambda i: authored(id=f't{i}', boundaryFrame=50, range=[40, 60], outgoing='A', incoming='A',
                                          state='planned', owner={'task': TASK}),
        'sourceFacts': lambda i: authored(id=f's{i}', range=[0, 10], speaker='S1', certainty='probable',
                                          basis='visual-and-stereo'),
        'unresolved': lambda i: {'id': f'u{i}', 'responsibility': 'audio-dialogue', 'range': None, 'statement': 'TEST',
                                 'blocks': 'none', 'decisionId': f'd{i}'},
        'contributions': lambda i: {'taskId': f'task{i}', 'responsibility': 'audio-dialogue', 'decisionId': None,
                                    'result': {'path': f'/TEST/{i}/result.json', 'sha256': 'e' * 64, 'bytes': 1},
                                    'disposition': 'accepted'},
        'conflicts': lambda i: {'id': f'k{i}', 'kind': 'declared', 'parties': [TASK], 'entryIds': ['g1'], 'range': None,
                                'status': 'resolved', 'decisionId': f'd{i}'},
        'decisions': lambda i: f'd{i}',
    }[section]
    found = [build(index) for index in range(count)]
    return found if section != 'graphics' else [long_record()['graphics'][0], *found[1:]]


def owners(count: int) -> list[dict]:
    """``count`` ownership rows: five whole-output rows and graphics-motion split into the rest."""
    split = count - 5
    edges = [index * 300 // split for index in range(split)] + [300]
    rows = [{'responsibility': name, 'range': [0, 300], 'owner': {'task': TASK}}
            for name in RESPONSIBILITIES if name != 'graphics-motion']
    return rows + [{'responsibility': 'graphics-motion', 'range': [edges[index], edges[index + 1]], 'owner': {'task': TASK}}
                   for index in range(split)]


class Bounds(unittest.TestCase):
    """Every stated bound admits its limit and refuses one more (§4.0.1, §4.0.2)."""

    LIMITS = {'story': 64, 'captions': 512, 'graphics': 128, 'holds': 128, 'transitions': 64, 'sourceFacts': 128,
              'unresolved': 64, 'contributions': 32, 'conflicts': 32, 'decisions': 128}

    def edge(self, section: str, limit: int) -> None:
        """``limit`` rows pass; ``limit + 1`` are refused naming the section."""
        validate_plan_record({**long_record(), section: rows_of(section, limit)})
        with self.assertRaisesRegex(ValueError, f'Coordination plan: {section}'):
            validate_plan_record({**long_record(), section: rows_of(section, limit + 1)})

    def test_list_bounds(self) -> None:
        """At the limit a list is accepted; one row more is refused naming its section."""
        for section, limit in self.LIMITS.items():
            with self.subTest(section=section):
                self.edge(section, limit)

    def test_ownership_bound(self) -> None:
        """64 ownership rows are accepted; 65 are refused."""
        validate_plan_record({**long_record(), 'ownership': owners(64)})
        with self.assertRaisesRegex(ValueError, 'Coordination plan: ownership: must list 0..64 rows'):
            validate_plan_record({**long_record(), 'ownership': owners(65)})

    def test_clock_and_version_bounds(self) -> None:
        """totalFrames 1..54000 with an N/D rate; versions 1..8 with the parent one before."""
        validate_plan_record({**long_record(), 'clock': {'frameRate': '24000/1001', 'totalFrames': 300}})
        for clock in ({'frameRate': '30/1', 'totalFrames': 54_001}, {'frameRate': '30/0', 'totalFrames': 300},
                      {'frameRate': '030/1', 'totalFrames': 300}, {'frameRate': '30', 'totalFrames': 300}):
            with self.subTest(clock=clock), self.assertRaisesRegex(ValueError, 'Coordination plan: clock'):
                validate_plan_record({**long_record(), 'clock': clock})
        parent = {'version': 7, 'sha256': 'f' * 64}
        later = {'parent': parent, 'changeClass': 'local', 'workPlan': {**long_record()['workPlan'], 'reserve': 'none'}}
        validate_plan_record({**long_record(), 'version': 8, **later})
        with self.assertRaisesRegex(ValueError, 'Coordination plan: version'):
            validate_plan_record({**long_record(), 'version': 9, **later, 'parent': {**parent, 'version': 8}})
        with self.assertRaisesRegex(ValueError, 'Coordination plan: parent: must be version - 1'):
            validate_plan_record({**long_record(), 'version': 8, **later, 'parent': {**parent, 'version': 6}})


def with_rows(section: str, rows: list) -> dict:
    """The TEST Long record with one section replaced."""
    return {**long_record(), section: rows}


class FieldRules(unittest.TestCase):
    """text(n), ranges, ids and the Long cross-field rules, each at its edge."""

    def refused(self, record: dict, words: str) -> None:
        """Refused with ``words`` in the message."""
        with self.assertRaises(ValueError) as caught:
            validate_plan_record(record)
        self.assertIn(words, str(caught.exception))

    def gap(self, **changes: object) -> dict:
        """The record with one unresolved row changed."""
        row = {'id': 'u1', 'responsibility': 'audio-dialogue', 'range': [0, 10], 'statement': 'TEST', 'blocks': 'none',
               'decisionId': 'd1'}
        return with_rows('unresolved', [{**row, **changes}])

    def test_text_and_range_edges(self) -> None:
        """500 bytes pass and 501 fail; NUL, a newline and blank text fail; ranges are non-empty and inside the clock."""
        validate_plan_record(self.gap(statement='x' * 500))
        for statement in ('x' * 501, 'TEST\x00', 'TEST\nline', '   '):
            with self.subTest(statement=statement[:6]):
                self.refused(self.gap(statement=statement), 'must be one non-empty line of at most 500 bytes')
        validate_plan_record(self.gap(range=[299, 300]))
        for span in ([10, 10], [-1, 5], [0, 301], [1.0, 5]):
            with self.subTest(span=span):
                self.refused(self.gap(range=span), 'is not [a, b] with 0 <= a < b <= 300')

    def test_ids_repeat_is_refused(self) -> None:
        """A decision id listed twice, and a conflict id used twice, are refused."""
        self.refused(with_rows('decisions', ['d1', 'd1']), 'decisions: ids repeat')
        conflict = {'id': 'k1', 'kind': 'declared', 'parties': [TASK], 'entryIds': ['g1'], 'range': None,
                    'status': 'blocking', 'decisionId': 'd1'}
        self.refused(with_rows('conflicts', [conflict, conflict]), 'conflicts: ids repeat')
        self.refused(with_rows('conflicts', [{**conflict, 'parties': ['z', 'a']}]), 'k1 parties must be sorted')

    def test_long_hold_and_transition_rules(self) -> None:
        """A hold shorter than its minimum or naming no entry, and a boundary on its range's edge, are refused."""
        hold = {'id': 'h1', 'subject': 'g1', 'range': [10, 60], 'minimumFrames': 50}
        validate_plan_record(with_rows('holds', [authored(**hold)]))
        self.refused(with_rows('holds', [authored(**{**hold, 'minimumFrames': 51})]), 'h1 is shorter than its minimum')
        self.refused(with_rows('holds', [authored(**{**hold, 'subject': 'none'})]), "subject 'none' names no entry")
        edge = authored(id='t1', boundaryFrame=40, range=[40, 60], outgoing='A', incoming='A', state='planned',
                        owner={'task': TASK})
        self.refused(with_rows('transitions', [edge]), 't1 boundary is not inside its range')

    def test_contribution_and_work_plan_rules(self) -> None:
        """A rejected contribution needs its decision; the reserve is one-repair exactly at version 1."""
        row = {'taskId': 'task1', 'responsibility': 'audio-dialogue', 'decisionId': None, 'disposition': 'rejected',
               'result': {'path': '/TEST/result.json', 'sha256': 'e' * 64, 'bytes': 1}}
        self.refused(with_rows('contributions', [row]), 'task1 rejected needs a plan-disposition decision')
        validate_plan_record(with_rows('contributions', [{**row, 'decisionId': 'd1'}]))
        self.refused(with_rows('workPlan', {**long_record()['workPlan'], 'reserve': 'none'}),
                     'reserve is one-repair at version 1 and none after it')
        self.refused({**long_record(), 'changeClass': 'local'}, 'changeClass: is initial exactly at version 1')

    def test_long_audio_asset_is_a_plan_input(self) -> None:
        """A Long audio event's asset pin must be one of the record's inputs."""
        asset = {'path': '/TEST/music.wav', 'sha256': 'e' * 64, 'bytes': 1}
        event = authored(id='a1', kind='music', range=[0, 100], asset=asset, levelDb=-12, isolation='scoped')
        self.refused(with_rows('audio', [event]), 'a1 asset must be a plan input')
        validate_plan_record({**with_rows('audio', [event]), 'inputs': [asset]})

    def test_a_story_needs_a_beat(self) -> None:
        """An empty story is refused by name."""
        self.refused(with_rows('story', []), 'story: needs at least one beat')

    def test_catalog_overrides(self) -> None:
        """X9: planning is the only coordination cap here; the reserves and packet roles are §4.0.1/§4.0.8's."""
        self.assertEqual(COORDINATION_LIMITS, {'planning': 3})
        self.assertEqual(SHORT_REPAIR_RESERVE, {'repairCycle': 1, 'planReview': 1, 'review': 2})
        self.assertEqual(LONG_REPAIR_RESERVE, {'repairCycle': 1, 'review': 2})
        self.assertEqual(sorted(PACKET_ROLES), ['clip-owner', 'final-critic', 'motion-critic', 'plan-critic'])

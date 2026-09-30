"""P3a S2 (MASTER-PLAN M-081): the shared plan record's shape, exact bytes, Short derivation, approved content (A5),
responsibility coverage (A8) and source facts in P2-07's vocabulary (X53). TEST data only; no child process.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import copy
import json
import unittest

from _coordination_fixture import OUTPUT, TASK, PlanFixture, canonical_size, padded_long, pin_of, write_plan
from cross_runtime_canonical_json import canonical_compact_json
from studio.production.plan_record import approved_content_problem, read_plan_record, validate_plan_record
from studio.production.plan_short_projection import derived_problem, short_sections, unlisted_keys

LIMIT = 1_048_576


class Case(PlanFixture):
    """A derived TEST Short record over a project with one region unit and sealed shared evidence."""

    def setUp(self) -> None:
        """The native plan, its project (with the sealed v2 record) and the version 1 record."""
        super().setUp()
        self.plan = self.native_plan()
        self.evidence = self.sealed_v2()
        self.homes = self.project(self.plan, evidence=self.evidence)
        self.record = self.short_record(self.homes)

    def refused(self, record: dict, words: str) -> None:
        """``validate_plan_record`` refuses with a message containing ``words``."""
        with self.assertRaises(ValueError) as caught:
            validate_plan_record(record)
        self.assertIn(words, str(caught.exception))
        self.assertTrue(str(caught.exception).startswith('Coordination plan: '))


class Shape(Case):
    """Closed keys, the 1 MiB bound, exact canonical bytes and unique entry ids."""

    def test_minimal_short_plan_valid(self) -> None:
        """The derived record validates and reads back from its exact bytes."""
        pin = write_plan(self.root / 'records' / 'plan-record.json', self.record)
        self.assertEqual(read_plan_record(pin), self.record)

    def test_unknown_key_refused(self) -> None:
        """An extra key, and a missing one, are refused (closed shape)."""
        self.refused({**self.record, 'extra': 1}, 'shape')
        self.refused({key: value for key, value in self.record.items() if key != 'decisions'}, 'shape')

    def test_size_bound(self) -> None:
        """A Long record of exactly 1,048,576 canonical bytes is accepted; one byte more is refused."""
        plan = padded_long(LIMIT)
        self.assertEqual(canonical_size(plan), LIMIT)
        validate_plan_record(plan)
        self.refused(padded_long(LIMIT + 1), f'{LIMIT + 1} canonical bytes exceed {LIMIT}')

    def test_noncanonical_bytes_refused(self) -> None:
        """Spaced JSON, a duplicate key, a missing newline and changed bytes are refused at reading."""
        file = self.root / 'records' / 'plan-record.json'
        canonical = canonical_compact_json(self.record)
        for raw in (json.dumps(self.record, indent=1) + '\n', canonical[:-1] + ',"kind":"sniper-coordination-plan"}\n',
                    canonical):
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(raw)
            with self.subTest(raw=raw[-40:]), self.assertRaises(ValueError) as caught:
                read_plan_record(pin_of(file))
            self.assertIn('not exact canonical JSON', str(caught.exception))
        pin = write_plan(file, self.record)
        file.write_bytes(file.read_bytes().replace(b'"Q9"', b'"Q8"'))
        with self.assertRaisesRegex(ValueError, 'plan record bytes changed'):
            read_plan_record(pin)

    def test_duplicate_entry_ids_refused(self) -> None:
        """An entry id used in two sections is refused."""
        record = copy.deepcopy(self.record)
        record['framing'][0]['id'] = record['story'][0]['id']
        self.refused(record, 'entry ids')

    def test_a_linked_record_is_refused(self) -> None:
        """A record reached through a symbolic link is never read."""
        pin = write_plan(self.root / 'records' / 'plan-record.json', self.record)
        link = self.root / 'records' / 'link.json'
        link.symlink_to(pin['path'])
        with self.assertRaisesRegex(ValueError, 'Coordination plan: read'):
            read_plan_record({**pin, 'path': str(link)})


class Derived(Case):
    """A Short's content sections are the code's derivation, byte for byte."""

    def test_short_sections_equal_derivation(self) -> None:
        """The record's sections equal ``short_sections(homes)`` and the freeze check passes."""
        self.assertIsNone(derived_problem(self.record))
        derived = short_sections(self.homes)
        self.assertEqual([row['id'] for row in derived['story']], ['beat-0', 'beat-1'])
        self.assertEqual([row['id'] for row in derived['transitions']], ['boundary-0'])
        self.assertEqual(derived['graphics'][0]['id'], 'region-0')

    def test_hand_edited_derived_section_refused(self) -> None:
        """A hand-edited hold is refused by name at freeze."""
        record = copy.deepcopy(self.record)
        record['holds'][0]['holdFrames'] = 11
        validate_plan_record(record)
        self.assertEqual(derived_problem(record),
                         'Coordination plan: derived: derived section holds differs from its executable home')

    def test_unlisted_key_is_global(self) -> None:
        """A key the table does not name becomes a global graphics entry."""
        plan = {**self.plan, 'futureKey': {'TEST': 1}}
        plan['canvas'] = {**plan['canvas'], 'futureCanvasKey': 2}
        self.assertIn('plan.futureKey', unlisted_keys(plan))
        self.assertIn('canvas.futureCanvasKey', unlisted_keys(plan))
        graphics = short_sections(self.project(plan, name='future'))['graphics']
        rows = {row['id']: row for row in graphics}
        self.assertEqual(rows['key-plan.futureKey']['isolation'], 'global')
        self.assertEqual(rows['key-canvas.futureCanvasKey']['isolation'], 'global')

    def test_missing_regions_file_is_one_global_unit(self) -> None:
        """Without REVIEW-REGIONS.json the compositions are one global ``project`` unit."""
        graphics = short_sections(self.project(self.plan, name='bare', regions=False))['graphics']
        self.assertEqual(graphics[0], {**graphics[0], 'id': 'project', 'range': None, 'isolation': 'global'})
        self.assertNotIn('region-0', {row['id'] for row in graphics})


class ShortApprovedContent(Case):
    """Freeze reopens no approved word or title (A5), through ``role_packet_given.bound_facts``."""

    def problem(self, change: object = None, row: dict | None = None) -> str | None:
        """The approved-content problem of the record whose native plan ``change`` edited."""
        plan = copy.deepcopy(self.plan)
        if change:
            change(plan)
        record = {**self.record, 'homes': self.project(plan, name='edited') if change else self.homes}
        return approved_content_problem(self.authority(row or self.approval_row()), record)

    def test_matches_current_approval(self) -> None:
        """The TEST plan keeps exactly the approved words, frames and title."""
        self.assertIsNone(self.problem())

    def test_changed_title_refused(self) -> None:
        """A different on-screen title reopens approved content."""
        found = self.problem(lambda plan: plan['canvas']['titleCard']['copy'].update(text='TEST other title'))
        self.assertIn('reopens approved content: title different', found)

    def test_plan_drops_an_approved_word_refused(self) -> None:
        """Dropping word 11 is named as missing from the selection."""
        found = self.problem(lambda plan: plan['canvas']['occurrences'].pop(1))
        self.assertIn("selection {'sourceMatches': True, 'transcriptMatches': True, 'missingWords': [11]", found)

    def test_plan_reorders_words_refused(self) -> None:
        """Swapping the order of words 10 and 11 is refused as another order."""
        def swap(plan: dict) -> None:
            """Exchange the source words (and texts) of the first two kept words."""
            first, second = plan['canvas']['occurrences'][:2]
            first[2], first[5], second[2], second[5] = second[2], second[5], first[2], first[5]
        found = self.problem(swap)
        self.assertIn("'otherOrder': True", found)

    def test_plan_adds_a_word_refused(self) -> None:
        """Adding word 12 is named as extra."""
        found = self.problem(lambda plan: plan['canvas']['occurrences'].append([3, 1, 12, 50, 55, 'w12', 0]))
        self.assertIn("'extraWords': [12]", found)

    def test_the_record_must_name_the_current_approval(self) -> None:
        """A stale approval identity, and an output with no approval, are refused by name."""
        stale = self.approval_row(title='TEST earlier title')
        self.assertIn('does not name the current approval', approved_content_problem(self.authority(stale), self.record))
        empty = {**self.authority(stale), 'clips': {OUTPUT: {'approvals': []}}}
        self.assertIn(f'output {OUTPUT} has no approved title and script', approved_content_problem(empty, self.record))


class Coverage(Case):
    """Each of the six responsibilities is owned over every frame (A8)."""

    def test_six_responsibilities_owned(self) -> None:
        """The author holds all six over the whole clock; dropping one responsibility is refused."""
        validate_plan_record(self.record)
        self.refused({**self.record, 'ownership': self.record['ownership'][1:]},
                     'responsibility source-speaker-fidelity has no owner for frames 0-60')

    def test_gap_in_graphics_ownership_refused(self) -> None:
        """Frames 20-40 of graphics-motion without an owner are named."""
        rows = [row for row in self.record['ownership'] if row['responsibility'] != 'graphics-motion']
        rows += [{'responsibility': 'graphics-motion', 'range': span, 'owner': {'task': TASK}} for span in ([0, 20], [40, 60])]
        self.refused({**self.record, 'ownership': rows}, 'responsibility graphics-motion has no owner for frames 20-40')

    def test_one_owner_holds_all_six(self) -> None:
        """Split rows for one responsibility are accepted; an overlap (two owners of a frame) is refused."""
        rows = [row for row in self.record['ownership'] if row['responsibility'] != 'captions-timing']
        split = [{'responsibility': 'captions-timing', 'range': span, 'owner': {'task': TASK}} for span in ([0, 30], [30, 60])]
        validate_plan_record({**self.record, 'ownership': rows + split})
        split[1]['range'] = [29, 60]
        self.refused({**self.record, 'ownership': rows + split}, 'captions-timing has two owners at frame 29')


class SourceFacts(Case):
    """P2-07's vocabulary verbatim (X53), copied from the sealed record."""

    def fact(self, **changes: object) -> dict:
        """The record with its first source fact changed."""
        record = copy.deepcopy(self.record)
        record['sourceFacts'][0].update(changes)
        return record

    def test_facts_are_the_sealed_intervals_on_output_frames(self) -> None:
        """Intervals (8, 12) and (12, 20) reach cuts 0 and 1: frames 0-45 and 45-60."""
        facts = [(row['id'], row['range'], row['speaker'], row['certainty'], row['basis']) for row in self.record['sourceFacts']]
        self.assertEqual(facts, [('interval-1-0', [0, 45], 'S2', 'established', 'operator-statement'),
                                 ('interval-2-1', [45, 60], None, 'unresolved', 'transcript-only')])

    def test_established_needs_listening_or_operator_statement(self) -> None:
        """``established`` on visual-and-stereo, or on transcript-only, is refused (X53)."""
        for basis in ('visual-and-stereo', 'transcript-only'):
            with self.subTest(basis=basis):
                self.refused(self.fact(basis=basis), 'established needs basis listening or operator-statement')

    def test_probable_visual_and_stereo_is_accepted(self) -> None:
        """``probable`` on visual-and-stereo is a valid fact (the old still-frames case under X53)."""
        validate_plan_record(self.fact(certainty='probable', basis='visual-and-stereo'))

    def test_speaker_is_null_exactly_when_unresolved(self) -> None:
        """A named unresolved speaker, and an unknown vocabulary value, are refused."""
        self.refused(self.fact(certainty='unresolved'), 'speaker is null exactly when certainty is unresolved')
        self.refused(self.fact(certainty='none'), 'must be P2-07 values')

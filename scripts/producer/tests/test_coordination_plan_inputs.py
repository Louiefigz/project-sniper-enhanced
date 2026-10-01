"""X211(3) and the W3-D8 minor (MASTER-PLAN M-081): the sealed record's picture evidence moves the source-speaker
slices, and renamed, missing or malformed P2 fields stop the derivation by name. TEST data only; no child process.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import copy
import json
from pathlib import Path

from _coordination_fixture import PlanFixture, moved, pin_of
from studio.production.coordination_catalog import P2_FIELDS
from studio.production.plan_record import changed_entries, classify
from studio.production.plan_short_projection import short_sections
from studio.production.plan_short_unlisted import unlisted_keys, vocabulary_problem

SPEAKER = frozenset({'source-speaker-fidelity'})


def renamed(plan: dict, field: str) -> dict:
    """A copy of ``plan`` with one (dotted) field renamed to ``<name>Renamed``."""
    plan = copy.deepcopy(plan)
    holder = plan['canvas'] if field.startswith('canvas.') else plan
    key = field.split('.')[-1]
    holder[f'{key}Renamed'] = holder.pop(key)
    return plan


class Case(PlanFixture):
    """A writer-shaped version 1 record with sealed evidence."""

    def setUp(self) -> None:
        """The plan, its sealed evidence, its project and its record."""
        super().setUp()
        self.plan = self.native_plan()
        self.evidence = self.sealed_v2()
        self.homes = self.project(self.plan, evidence=self.evidence)
        self.record = self.short_record(self.homes)

    def refused(self, homes: dict, words: str) -> None:
        """The derivation stops with ``words`` in its named refusal."""
        with self.assertRaises(ValueError) as caught:
            short_sections(homes)
        self.assertIn(words, str(caught.exception))
        self.assertTrue(str(caught.exception).startswith('Coordination plan: derived: '))

    def edited(self, change: object, name: str, evidence: bool = True) -> dict:
        """Homes of a project whose plan ``change`` edited."""
        plan = copy.deepcopy(self.plan)
        change(plan)
        return self.project(plan, name=name, evidence=self.evidence if evidence else None)


class SpeakerEvidence(Case):
    """X211(3): observations and every face region on this source move the source-speaker-fidelity slices."""

    def test_the_evidence_is_one_whole_output_framing_entry(self) -> None:
        """The record adds a ``speaker-evidence`` framing entry over the whole output."""
        rows = {row['id']: row for row in self.record['framing']}
        self.assertIsNone(rows['speaker-evidence']['range'])

    def test_new_speaker_observations_move_source_speaker_fidelity(self) -> None:
        """A reseal whose only change is the bound observations moves source-speaker-fidelity only (the review probe)."""
        evidence = self.sealed_v2(observations=self.observe(name='observe-2', missing={'S2': 4}))
        after = self.short_record(self.project(copy.deepcopy(self.plan), name='reobserved', evidence=evidence))
        self.assertEqual((classify(self.record, after), moved(self.record, after)), ('local', SPEAKER))
        self.assertIn('speaker-evidence', {row['id'] for row in changed_entries(self.record, after)})

    def test_an_unnamed_face_region_moves_source_speaker_fidelity(self) -> None:
        """S1 is neither speaker nor visible in any fact on this Short's frames; a change to S1's face region still moves
        the slices, through the speaker-evidence entry alone."""
        def record(x_range: list[int], name: str) -> dict:
            """A record whose sealed intervals on this Short show S2 only, and S1's face region spans ``x_range``."""
            def change(value: dict) -> None:
                """Edit the TEST draft before sealing."""
                for row in value['speakers']['intervals'][1:]:
                    row['visible'] = ['S2']
                value['speakers']['people'][0]['faceRegion']['xRange'] = x_range
            return self.short_record(self.project(copy.deepcopy(self.plan), name=name, evidence=self.sealed_v2(change)))
        before, after = record([0, 900], 'face-a'), record([0, 800], 'face-b')
        self.assertEqual(([row['id'] for row in changed_entries(before, after)], moved(before, after)),
                         (['speaker-evidence'], SPEAKER))


    def test_a_named_person_without_a_face_region_moves_through_the_facts(self) -> None:
        """S2 with no face region: a change to S2 moves the two facts naming S2 (speaker, visible), not the evidence."""
        def faceless(description: str) -> object:
            """A record edit: S2 has no face region (it is optional) and takes ``description``."""
            def change(value: dict) -> None:
                """Edit the TEST draft before sealing."""
                value['speakers']['people'][1].pop('faceRegion')
                value['speakers']['people'][1]['description'] = description
            return change
        records = [self.short_record(self.project(copy.deepcopy(self.plan), name=f'faceless-{index}',
                                                  evidence=self.sealed_v2(faceless(f'TEST person S2 {index}'))))
                   for index in range(2)]
        self.assertEqual([row['id'] for row in changed_entries(*records)], ['interval-1-0', 'interval-2-1'])

    def test_picture_decisions_are_one_whole_output_framing_entry(self) -> None:
        """L-R 4f1f4704: decisions only P2-08 reads are one whole-output framing entry, never a global key."""
        rows = [{'startFrame': 0, 'endFrame': 45, 'kind': 'listener-reaction', 'reason': 'TEST reason long enough here'}]
        before = self.short_record(self.edited(lambda plan: plan.__setitem__('speakerPictureDecisions', rows), 'decided'))
        changed = [{**rows[0], 'endFrame': 30}]
        after = self.short_record(self.edited(lambda plan: plan.__setitem__('speakerPictureDecisions', changed), 'redecided'))
        self.assertEqual((classify(before, after), [row['id'] for row in changed_entries(before, after)], moved(before, after)),
                         ('local', ['speaker-picture-decisions'], SPEAKER))
        self.assertIsNone({row['id']: row for row in before['framing']}['speaker-picture-decisions']['range'])
        self.assertNotIn('plan.speakerPictureDecisions', unlisted_keys({**self.plan, 'speakerPictureDecisions': rows}))

    def test_picture_decisions_need_shared_evidence(self) -> None:
        """Decisions answer sealed facts, so a plan binding no record may not carry them (the writer's unboundDecisions)."""
        self.refused(self.edited(lambda plan: plan.__setitem__('speakerPictureDecisions', []), 'unbound-decisions',
                                 evidence=False), 'speakerPictureDecisions need sharedEvidence')


class Vocabulary(Case):
    """W3-D8 (X211 minor): renamed or missing P2 fields and malformed bindings stop by name."""

    def test_renamed_p2_fields_stop_by_name(self) -> None:
        """A renamed canvas field and a renamed top-level field each name themselves."""
        def rename_phrases(plan: dict) -> None:
            """``captionProtectedPhrases`` under another name."""
            plan['canvas']['protectedCaptionPhrases'] = plan['canvas'].pop('captionProtectedPhrases')
        self.refused(self.edited(rename_phrases, 'phrases'), "'canvas.protectedCaptionPhrases'] are not in the writer")
        self.refused(self.edited(lambda plan: plan.__setitem__('speakerPictures', []), 'pictures'),
                     "['speakerPictures'] are not in the writer vocabulary")

    def test_every_p2_field_renamed_stops_by_name(self) -> None:
        """Each P2 field the writer does not yet emit (P2_FIELDS), renamed in the written plan, names itself."""
        written = json.loads(Path(self.homes['nativePlan']['path']).read_text())
        written['speakerPictureDecisions'] = []
        for field in P2_FIELDS:
            with self.subTest(field=field):
                self.assertRaisesRegex(ValueError, f"'{field}Renamed'] are not in the writer vocabulary",
                                       vocabulary_problem, renamed(written, field))

    def test_missing_protected_phrases_stop_by_name(self) -> None:
        """The sealed record protects words 10-11, which this Short keeps, so the plan's field must be there."""
        self.refused(self.edited(lambda plan: plan['canvas'].pop('captionProtectedPhrases'), 'missing'),
                     'canvas.captionProtectedPhrases is missing although the sealed record protects 1 phrase')

    def test_a_phrase_on_words_this_short_drops_needs_no_field(self) -> None:
        """A record protecting words 2-3 (Q1's, not kept here) asks nothing of this Short's canvas."""
        evidence = self.sealed_v2(lambda value: value['captionPhrases'][0].update(sourceWordIndexes=[2, 3]))
        plan = copy.deepcopy(self.plan)
        plan['canvas'].pop('captionProtectedPhrases')
        facts = short_sections(self.project(plan, name='dropped', evidence=evidence))['sourceFacts']
        self.assertEqual(facts, self.record['sourceFacts'])

    def test_the_evidence_binding_and_its_home_agree(self) -> None:
        """No pinned record for a bound plan, a pinned record for an unbound plan, and another record all stop."""
        self.refused({**self.homes, 'sharedEvidence': None}, 'binds sharedEvidence (P2-08) exactly when homes pins')
        unbound = self.edited(lambda plan: plan.pop('sharedEvidence', None), 'unbound', evidence=False)
        self.refused({**unbound, 'sharedEvidence': pin_of(self.evidence)}, 'exactly when homes pins a sealed record')
        other = self.sealed_v2(lambda value: value['speakers']['intervals'][1].update(note='TEST other'))
        self.refused({**self.homes, 'sharedEvidence': pin_of(other)}, 'is not the record the native plan binds')

    def test_malformed_bindings_and_p2_fields_stop_by_name(self) -> None:
        """A binding with other keys and malformed P2 fields name themselves."""
        cases = {'binding preparedSources must be': lambda plan: plan['preparedSources'].pop('sha256'),
                 'P2 field speakerPictureDecisions is malformed': lambda plan: plan.__setitem__('speakerPictureDecisions', 'x'),
                 'P2 field canvas.captionProtectedPhrases is malformed':
                     lambda plan: plan['canvas'].__setitem__('captionProtectedPhrases', [1])}
        for index, (words, change) in enumerate(cases.items()):
            with self.subTest(words=words):
                self.refused(self.edited(change, f'malformed-{index}'), words)

    def test_a_motion_needs_its_target_cue(self) -> None:
        """A motion naming no cue, or outrunning its cue, stops as the writer does."""
        self.refused(self.edited(lambda plan: plan['canvas']['motion'][0].update(id='nobody'), 'nobody'),
                     "motion 'nobody' has no text or shape cue whose window holds it")
        self.refused(self.edited(lambda plan: plan['canvas']['motion'][0].update(durationFrames=40), 'long'),
                     "motion 'label' has no text or shape cue whose window holds it")

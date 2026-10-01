"""X211(3) and the W3-D8 minor (MASTER-PLAN M-081): the sealed record's picture evidence moves the source-speaker
slices, and renamed, missing or malformed P2 fields stop the derivation by name. TEST data only; no child process.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import copy

from _coordination_fixture import PlanFixture, moved, pin_of
from studio.production.plan_record import changed_entries, classify
from studio.production.plan_short_projection import short_sections

SPEAKER = frozenset({'source-speaker-fidelity'})


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
        """S1 is named by no fact on this Short's frames; a change to S1's face region still moves the slices."""
        evidence = self.sealed_v2(lambda value: value['speakers']['people'][0]['faceRegion'].update(xRange=[0, 800]))
        after = self.short_record(self.project(copy.deepcopy(self.plan), name='face', evidence=evidence))
        self.assertNotIn('S1', {row['speaker'] for row in self.record['sourceFacts']})
        self.assertEqual(moved(self.record, after), SPEAKER)


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

    def test_missing_protected_phrases_stop_by_name(self) -> None:
        """The sealed record protects words 10-11, which this Short keeps, so the plan's field must be there."""
        self.refused(self.edited(lambda plan: plan['canvas'].pop('captionProtectedPhrases'), 'missing'),
                     'canvas.captionProtectedPhrases is missing although the sealed record protects 1 phrase')

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

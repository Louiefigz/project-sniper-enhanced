"""X201 (MASTER-PLAN M-081): every row of the Short derivation table moves exactly the slices it should, the global
fallbacks included, and no native-plan change can move no slice. TEST data only; no child process.

Each row edits one input of the TEST project, derives the record again and compares the change class and the set of
responsibilities whose whole-output slice moved (a global change moves every slice).
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import copy
from collections.abc import Callable
from pathlib import Path

from _coordination_fixture import PlanFixture
from studio.production.coordination_catalog import RESPONSIBILITIES, SHORT_DERIVATION
from studio.production.plan_record import classify, slice_digest

WHOLE = {'range': None, 'entryIds': None}
ALL = frozenset(RESPONSIBILITIES)
GRAPHICS = frozenset({'graphics-motion'})
SCENE = frozenset({'graphics-motion', 'transitions'})
# Plan leaves whose change moves no slice, by rule: a generated binding (planHash leaves it out too) and an asset's
# location, whose bytes the asset's own sha256 pins (plan_projection omits paths).
EXEMPT = {('prebuildReview', 'path'), ('prebuildReview', 'sha256'), ('assets', 0, 'path')}


def moved(before: dict, after: dict) -> frozenset[str]:
    """Responsibilities whose whole-output slice differs."""
    return frozenset(name for name in RESPONSIBILITIES if slice_digest(before, name, WHOLE) != slice_digest(after, name, WHOLE))


def planned(change: Callable[[dict], object]) -> Callable:
    """A row that edits the native plan before its project is written."""
    def edit(case: PlanFixture, plan: dict, name: str) -> dict:
        """Apply the edit and write the project."""
        change(plan)
        return case.project(plan, name=name, evidence=case.evidence)
    return edit


def composed(file: str, content: str) -> Callable:
    """A row that edits one composition file of the written project."""
    def edit(case: PlanFixture, plan: dict, name: str) -> dict:
        """Write the project, then the composition."""
        homes = case.project(plan, name=name, evidence=case.evidence)
        (Path(homes['project']) / 'compositions' / file).write_text(content)
        return homes
    return edit


def bare(case: PlanFixture, plan: dict, name: str) -> dict:
    """The project without REVIEW-REGIONS.json."""
    return case.project(plan, name=name, regions=False, evidence=case.evidence)


def canvas(key: str, value: object) -> Callable:
    """Set one canvas key."""
    return planned(lambda plan: plan['canvas'].__setitem__(key, value))


# (section, input and its source at stack 35eca01b, edit, change class, moved responsibilities)
ROWS = (
    ('clock', 'canvas.totalFrames (native-short-composition.ts:34)', canvas('totalFrames', 61), 'global', ALL),
    ('speech', 'canvas.occurrences (:38; guided-proposal-speech.ts:7)',
     planned(lambda plan: plan['canvas']['occurrences'][0].__setitem__(5, 'TEST!')), 'global', ALL),
    ('story', 'strategy.pacing.beats (native-short-pacing.ts:11)',
     planned(lambda plan: plan['strategy']['pacing']['beats'][1].update(reason='TEST other')), 'global', ALL),
    ('holds', 'strategy.scenes[].holdFrames (native-short-strategy.ts:38-41)',
     planned(lambda plan: plan['strategy']['scenes'][1].update(holdFrames=6)), 'local', SCENE),
    ('framing', 'canvas.pictureViews (native-short-composition.ts:44)',
     planned(lambda plan: plan['canvas']['pictureViews'][1].update(crop=[800, 0, 720, 1080])), 'local',
     frozenset({'source-speaker-fidelity'})),
    ('captions', 'canvas.captionGroups (:38)', canvas('captionGroups', [[0], [1, 2]]), 'local', frozenset({'captions-timing'})),
    ('captions', 'canvas.captionProtectedPhrases (P2-05 plan text; L-R, not integrated)',
     canvas('captionProtectedPhrases', [[0, 1]]), 'local', frozenset({'captions-timing'})),
    ('captions', 'canvas.captionSuppressions (:43)',
     canvas('captionSuppressions', [{'startFrame': 50, 'endFrame': 60, 'reason': 'TEST'}]), 'local',
     frozenset({'captions-timing'})),
    ('graphics', 'region composition bytes: a data-hf-reveal cue (F-1; L-B native-reveal-declarations.ts:18)',
     composed('lower-third.html', '<div data-hf-reveal="0.6">TEST lower third</div>'), 'local', GRAPHICS),
    ('graphics', 'a composition outside every region (F-1)', composed('extra.html', '<div>TEST changed</div>'),
     'global', ALL),
    ('graphics', 'no REVIEW-REGIONS.json: one global project unit', bare, 'global', ALL),
    ('graphics', 'canvas.titleCard (native-short-composition.ts:46)',
     planned(lambda plan: plan['canvas']['titleCard'].update(top=120)), 'local', GRAPHICS),
    ('graphics', 'canvas.text (:45)', planned(lambda plan: plan['canvas']['text'][0].update(text='TEST other')), 'local',
     GRAPHICS),
    ('graphics', 'canvas.shapes (:45)', planned(lambda plan: plan['canvas']['shapes'][0].update(fill='#fff')), 'local',
     GRAPHICS),
    ('graphics', 'canvas.motion (:45)', planned(lambda plan: plan['canvas']['motion'][0].update(durationFrames=12)),
     'local', GRAPHICS),
    ('graphics', 'visualSources.decisions (native-short-project.ts:35)',
     planned(lambda plan: plan['visualSources']['decisions'][0].update(item='TEST other')), 'local', GRAPHICS),
    ('transitions', 'strategy.scenes boundary (native-short-strategy.ts:38-41)',
     planned(lambda plan: plan['strategy']['scenes'][0].update(exitReason='TEST other')), 'local', SCENE),
    ('audio', 'audioFinishing (native-short-project.ts:50; F-2)',
     planned(lambda plan: plan['audioFinishing']['audioEnhance'].update(preset='voice-rnn')), 'local',
     frozenset({'audio-dialogue'})),
    ('audio', 'assets stay global (F-2; native-short-strategy.ts:12-17)',
     planned(lambda plan: plan['assets'].append({**plan['assets'][0], 'file': 'assets/other.mp4', 'role': 'image'})),
     'global', ALL),
    ('graphics', 'speakerPictureDecisions (F-4; P2-08 plan text, L-R, not integrated)',
     planned(lambda plan: plan.__setitem__('speakerPictureDecisions', [
         {'startFrame': 0, 'endFrame': 45, 'kind': 'two-shot', 'reason': 'TEST reason'}])), 'global', ALL),
    ('graphics', 'strategy.pacing.holds outside the projection (F-5)',
     planned(lambda plan: plan['strategy']['pacing']['holds'][0].update(minimumFrames=6)), 'global', ALL),
    ('graphics', 'an unlisted projection key: extension (F-3; native-short-project.ts:52)',
     planned(lambda plan: plan.__setitem__('extension', {'markup': '', 'css': 'TEST', 'motion': ''})), 'global', ALL),
)


def leaves(value: object, path: tuple = ()) -> list[tuple]:
    """Every scalar, and every empty list or object, of a JSON value, as its key path."""
    if isinstance(value, dict) and value:
        return [leaf for key, item in value.items() for leaf in leaves(item, (*path, key))]
    if isinstance(value, list) and value:
        return [leaf for index, item in enumerate(value) for leaf in leaves(item, (*path, index))]
    return [path]


def perturbed(plan: dict, path: tuple) -> dict:
    """A copy of ``plan`` with the leaf at ``path`` changed."""
    changed = copy.deepcopy(plan)
    holder = changed
    for key in path[:-1]:
        holder = holder[key]
    value = holder[path[-1]]
    swaps = {bool: lambda: not value, int: lambda: value + 1, float: lambda: value + 0.5, str: lambda: value + 'x',
             list: lambda: [*value, 'TEST'], dict: lambda: {**value, 'TEST': 1}, type(None): lambda: 'TEST'}
    holder[path[-1]] = swaps[type(value)]()
    return changed


class DerivationRows(PlanFixture):
    """One test per derivation-table row (X201), the global fallbacks included."""

    def setUp(self) -> None:
        """A derived version 1 Short record with sealed evidence."""
        super().setUp()
        self.plan = self.native_plan()
        self.evidence = self.sealed_v2()
        self.record = self.short_record(self.project(self.plan, evidence=self.evidence))

    def test_every_table_row_is_exercised(self) -> None:
        """Each SHORT_DERIVATION section has a row here, or its own test (sourceFacts)."""
        self.assertEqual({row[0] for row in ROWS} | {'sourceFacts'}, set(SHORT_DERIVATION))

    def test_each_row_moves_the_slices_it_should(self) -> None:
        """Local rows move exactly their owners' slices; global rows move every slice."""
        for index, (section, source, edit, change_class, expected) in enumerate(ROWS):
            with self.subTest(section=section, source=source):
                after = self.short_record(edit(self, copy.deepcopy(self.plan), f'row-{index}'))
                self.assertEqual(classify(self.record, after), change_class)
                self.assertEqual(moved(self.record, after), expected)

    def test_resealed_evidence_moves_only_source_speaker_fidelity(self) -> None:
        """A new sealed record whose interval changed moves source-speaker-fidelity only (homes.sharedEvidence)."""
        evidence = self.sealed_v2(lambda value: value['speakers']['intervals'][1].update(note='TEST heard again'))
        after = self.short_record(self.project(copy.deepcopy(self.plan), name='resealed', evidence=evidence))
        self.assertEqual(classify(self.record, after), 'local')
        self.assertEqual(moved(self.record, after), frozenset({'source-speaker-fidelity'}))

    def test_without_regions_a_composition_change_is_global(self) -> None:
        """With no REVIEW-REGIONS.json, a change to any composition moves every slice (the project unit)."""
        before = self.short_record(bare(self, copy.deepcopy(self.plan), 'bare-before'))
        homes = bare(self, copy.deepcopy(self.plan), 'bare-after')
        (Path(homes['project']) / 'compositions' / 'extra.html').write_text('<div>TEST changed</div>')
        after = self.short_record(homes)
        self.assertEqual(classify(before, after), 'global')
        self.assertEqual(moved(before, after), ALL)


class NoSilentChange(PlanFixture):
    """The X201 attack: a change to any native-plan leaf moves a slice or refuses the derivation."""

    def test_every_plan_leaf_moves_a_slice_or_refuses(self) -> None:
        """Only the named exemptions move nothing; every other leaf change is seen."""
        plan = self.native_plan()
        before = self.short_record(self.project(plan))
        silent, refused = set(), 0
        for index, path in enumerate(leaves(plan)):
            try:
                after = self.short_record(self.project(perturbed(plan, path), name=f'leaf-{index}'))
            except ValueError as error:
                self.assertTrue(str(error).startswith('Coordination plan: '), str(error))
                refused += 1
                continue
            silent |= set() if moved(before, after) else {path}
        self.assertEqual(silent, EXEMPT)
        self.assertLess(refused, len(leaves(plan)) // 4)

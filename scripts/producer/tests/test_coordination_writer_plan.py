"""X211(1), (2) and (4) on a writer-shaped plan (MASTER-PLAN M-081): writer-verified summaries are derived paths whose
every source moves a slice; prepared media moves the audio, caption and picture slices; dropped row fields are
digested and only a row's location moves nothing. TEST data only; no child process.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import copy
import json
from pathlib import Path

from _coordination_fixture import PlanFixture, leaves, moved, perturbed, summarised
from studio.native_short_regions import region_map, shared_inputs
from studio.production.coordination_catalog import GENERATED_EXEMPT, SUMMARY_SOURCES
from studio.production.plan_record import changed_entries, classify
from studio.production.plan_short_unlisted import unlisted_keys

PREPARED = frozenset({'audio-dialogue', 'captions-timing', 'source-speaker-fidelity'})
REVEAL = '<div data-hf-reveal="0.6">TEST lower third</div>'


def written(homes: dict) -> dict:
    """The native plan as the project holds it (after the writer refresh)."""
    return json.loads(Path(homes['nativePlan']['path']).read_text())


def value_at(plan: dict, dotted: str) -> object:
    """The value at a dotted path, or a sentinel when a key is absent."""
    holder: object = plan
    for key in dotted.split('.'):
        if not isinstance(holder, dict) or key not in holder:
            return KeyError
        holder = holder[key]
    return holder


class Case(PlanFixture):
    """A writer-shaped version 1 record with sealed evidence."""

    def setUp(self) -> None:
        """The plan, its project and its record."""
        super().setUp()
        self.plan = self.native_plan()
        self.evidence = self.sealed_v2()
        self.homes = self.project(self.plan, evidence=self.evidence)
        self.record = self.short_record(self.homes)

    def after(self, change: object, name: str) -> tuple[dict, dict]:
        """(record, written plan) after ``change`` edited a copy of the plan."""
        plan = copy.deepcopy(self.plan)
        change(plan)
        homes = self.project(plan, name=name, evidence=self.evidence)
        return self.short_record(homes), written(homes)


class Summaries(Case):
    """X211(4): writer-verified summaries are derived paths, on the condition every source they cover moves a slice."""

    def test_summaries_and_generated_bindings_are_not_global_keys(self) -> None:
        """No summary, generated binding, prepared media or evidence binding becomes a key-entry."""
        keys = unlisted_keys(written(self.homes))
        for root in (*SUMMARY_SOURCES, *GENERATED_EXEMPT, 'preparedSources', 'sharedEvidence'):
            with self.subTest(root=root):
                self.assertEqual([key for key in keys if key == f'plan.{root}' or key.startswith(f'plan.{root}.')], [])

    def test_every_summarised_source_moves_a_slice(self) -> None:
        """Every plan leaf a summary covers, changed with the summaries following, moves a slice or is refused."""
        homes = self.project(self.plan, name='plain')
        plain, base = self.short_record(homes), Path(homes['nativePlan']['path']).read_bytes()
        sources = sorted({source for paths in SUMMARY_SOURCES.values() for source in paths})
        covered = [leaf for leaf in leaves(self.plan) if not summarised(leaf) and leaf[0] not in GENERATED_EXEMPT
                   and any(f'{".".join(map(str, leaf))}.'.startswith(f'{source}.') for source in sources)]
        outcomes = {}
        for leaf in covered:
            kind, after = self.leaf_outcome(self.plan, leaf, base)
            outcomes[leaf] = kind if kind != 'derived' else bool(moved(plain, after))
        self.assertGreater(len(covered), 100)
        silent = {leaf for leaf, result in outcomes.items() if result is False}
        self.assertEqual(silent, {('assets', 0, 'path'), ('assets', 1, 'path'), ('catalogFiles', 0, 'path'),
                                  ('catalogFiles', 1, 'path')})

    def test_local_edits_stay_local_while_every_summary_follows(self) -> None:
        """MAJOR-4: a text-cue edit and a region reveal edit change the writer's summaries yet stay local."""
        text, edited = self.after(lambda plan: plan['canvas']['text'][0].update(text='TEST other'), 'text')
        for path in ('strategy.pacing.visualHash', 'visualSources.subjectSha256', 'strategy.assetUse.revisionHash',
                     'strategy.story.revisionHash'):
            self.assertNotEqual(value_at(edited, path), value_at(written(self.homes), path), path)
        self.assertEqual((classify(self.record, text), moved(self.record, text)), ('local', frozenset({'graphics-motion'})))
        with self.staged({'lower-third.html': REVEAL}):
            homes = self.project(self.plan, name='reveal', evidence=self.evidence)
        before, after = written(self.homes), written(homes)
        for path in ('visualSources.subjectSha256', 'strategy.visualPlanApplication'):
            self.assertNotEqual(value_at(after, path), value_at(before, path), path)
        region = self.short_record(homes)
        self.assertEqual((classify(self.record, region), moved(self.record, region)), ('local', frozenset({'graphics-motion'})))


class Prepared(Case):
    """X211(1): the prepared working media is an input of the audio, caption and picture slices."""

    def test_prepared_media_moves_audio_captions_and_picture(self) -> None:
        """A re-prepared package (new sha256) moves exactly those slices, through their four entries."""
        after, _plan = self.after(lambda plan: plan['preparedSources'].update(sha256='5' * 64), 'prepared')
        self.assertEqual((classify(self.record, after), moved(self.record, after)), ('local', PREPARED))
        self.assertEqual({row['id'] for row in changed_entries(self.record, after)},
                         {'audio-finishing', 'caption-style', 'view-0', 'view-1'})

    def test_dropping_prepared_media_moves_the_same(self) -> None:
        """Removing the package is the same change as replacing it."""
        after, _plan = self.after(lambda plan: plan.pop('preparedSources'), 'unprepared')
        self.assertEqual(moved(self.record, after), PREPARED)


class RowFields(Case):
    """X211(2): fields plan_projection drops are digested; only a row's location moves nothing."""

    def test_region_bound_catalog_fields_stay_in_their_region(self) -> None:
        """A dropped field of a region file's catalog row moves only that region's entry (X211(2))."""
        after, _plan = self.after(lambda plan: plan['catalogFiles'][0].update(sourceSha256='8' * 64), 'catalog')
        self.assertEqual(classify(self.record, after), 'local')
        self.assertEqual([row['id'] for row in changed_entries(self.record, after)], ['region-0'])

    def test_unprojected_asset_and_catalog_fields_are_global(self) -> None:
        """origin, webCapture and an unbound catalog file's sourceSha256 each move every slice."""
        for name, change in (('origin', lambda plan: plan['assets'][0]['origin'].update(path='/TEST/other-origin.json')),
                             ('web', lambda plan: plan['assets'][1]['webCapture'].update(supervisionSha256='6' * 64)),
                             ('source', lambda plan: plan['catalogFiles'][1].update(sourceSha256='7' * 64))):
            with self.subTest(field=name):
                after, _plan = self.after(change, name)
                self.assertEqual(classify(self.record, after), 'global')

    def test_locations_leave_the_executable_identity_unchanged(self) -> None:
        """A row's path moves no slice, and the engine's executable identity (``shared_inputs``) is byte-equal."""
        before = shared_inputs(Path(self.homes['project']), written(self.homes),
                               region_map(Path(self.homes['project']), self.plan['canvas']))
        for path in (('assets', 0, 'path'), ('catalogFiles', 0, 'path'), ('preparedSources', 'path')):
            with self.subTest(path=path):
                homes = self.project(perturbed(self.plan, path), name='-'.join(map(str, path)), evidence=self.evidence)
                project = Path(homes['project'])
                self.assertEqual(moved(self.record, self.short_record(homes)), frozenset())
                self.assertEqual(shared_inputs(project, written(homes), region_map(project, self.plan['canvas'])), before)

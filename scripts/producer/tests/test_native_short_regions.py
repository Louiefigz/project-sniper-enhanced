"""Schema-2 native Short dependency packets, risk events and schedules on TEST projects."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused
from _pending import pending
from _native_short_region_fixture import ShortRegionProject, composition
from studio.native_preview_events import risk_events
from studio.native_preview_schedule import MAX_WINDOWS, preview_schedule
from studio.native_review_regions import preview_windows
from studio.native_short_regions import mount_frames, mount_rows, short_packet

FRAMES = Path(__file__).resolve().parent / 'fixtures/native_review_region_frames.json'


def changed(after: dict, before: dict) -> set[str]:
    """Unit identities whose dependency hash differs between two packets."""
    old = {row['id']: row['hash'] for row in before['units']}
    return {row['id'] for row in after['units'] if old.get(row['id']) != row['hash']}


class ShortRegionPacketTests(unittest.TestCase):
    """Content hashes decide reuse; paths, prose and derived mirrors never do."""

    def setUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.project = ShortRegionProject(self.base / 'native-v1')

    def packet(self, project: ShortRegionProject | None = None) -> dict:
        return short_packet((project or self.project).request())

    def test_frame_vectors_match_the_typescript_writer(self) -> None:
        for row in json.loads(FRAMES.read_text())['vectors']:
            frames = mount_frames({'data-start': row['start'], 'data-duration': row['duration']}, Fraction(row['rate']))
            self.assertEqual(list(frames) if frames else None, row['frames'], row)

    def test_scoped_style_edit_reuses_unrelated_units(self) -> None:
        before = self.packet()
        file = self.project.directory / 'compositions/card-b.html'
        file.write_text(composition('card-b', 'color:#fff;font-size:48px'))
        after = self.packet()
        self.assertEqual(after['sharedHash'], before['sharedHash'])
        self.assertEqual(changed(after, before), {'card-b'})
        self.assertEqual(preview_windows(after, before), [{'startFrame': 240, 'endFrame': 420}])
        self.assertTrue(any(row['id'].startswith('project-window-') for row in after['units']))

    def test_unproven_composition_edit_invalidates_every_unit(self) -> None:
        self.project.regions['card-b'] = ('10', '2', 300, 360, 'global')
        self.project.write()
        before = self.packet()
        (self.project.directory / 'compositions/card-b.html').write_text(composition('card-b', 'color:red'))
        after = self.packet()
        self.assertNotEqual(after['sharedHash'], before['sharedHash'])
        self.assertEqual(changed(after, before), {row['id'] for row in after['units']})

    def test_revision_folder_and_prepared_paths_never_enter_hashes(self) -> None:
        before = self.packet()
        moved = self.base / 'native-v2'
        shutil.copytree(self.project.directory, moved)
        plan = json.loads((moved / 'SHORT-PROJECT.json').read_text())
        plan['preparedSources']['path'] = str(moved) + '.sources/stage.json'
        plan['assets'][0]['path'] = '/TEST/other-revision/original.mp4'
        plan['catalogFiles'][1]['path'] = '/TEST/catalog/card-b-v2.html'
        plan['strategy']['pacing']['lanes']['motion'] = 'TEST revised rationale prose'
        plan['strategy']['story']['revisionHash'] = 'f' * 64
        (moved / 'SHORT-PROJECT.json').write_text(json.dumps(plan))
        prepared = json.loads((moved / 'PREPARED-SOURCES.json').read_text())
        prepared['package']['path'] = str(moved) + '.sources/stage.json'
        (moved / 'PREPARED-SOURCES.json').write_text(json.dumps(prepared))
        after = short_packet({**self.project.request(), 'project': str(moved)})
        self.assertEqual((after['sharedHash'], after['units']), (before['sharedHash'], before['units']))

    def test_genuinely_different_media_brief_or_title_changes_shared_inputs(self) -> None:
        before = self.packet()['sharedHash']
        mutations = {
            'prepared bytes': lambda project: (project.directory / 'assets/source.mp4').write_bytes(b'TEST other bytes'),
            'prepared mapping': lambda project: project.prepared['mappings'][0].update(mediaStart=2),
            'brief payoff': lambda project: project.plan['strategy'].update(payoff='TEST different payoff'),
            'title copy': lambda project: project.plan['catalogTitle']['copy'].update(text='TEST other title'),
            'caption suppression': lambda project: project.plan['canvas'].update(captionSuppressions=[
                {'startFrame': 0, 'endFrame': 60, 'reason': 'TEST catalog title holds'}]),
        }
        for name, mutate in mutations.items():
            project = ShortRegionProject(self.base / name.replace(' ', '-'))
            mutate(project)
            project.write()
            with self.subTest(name=name):
                self.assertNotEqual(self.packet(project)['sharedHash'], before)

    def test_generated_rows_must_match_the_executable_mounts(self) -> None:
        file = self.project.directory / 'REVIEW-REGIONS.json'
        original = json.loads(file.read_text())
        for change in ({'endFrame': 59}, {'id': 'project-card'}, {'isolation': {'status': 'scoped'}},
                       {'isolation': 'scoped'}):
            mapping = json.loads(json.dumps(original))
            mapping['units'][0].update(change)
            file.write_text(json.dumps(mapping))
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.packet()
        file.write_text(json.dumps(original))
        index = self.project.directory / 'index.html'
        index.write_text(index.read_text().replace('<div id="card-a"', '<section data-start="1"><div id="card-a"', 1)
                         .replace('</div><div id="card-b"', '</div></section><div id="card-b"', 1))
        with self.assertRaisesRegex(ValueError, 'root-clock'):
            self.packet()


    @pending('P4', 'planned_preview_workload (base e049e03c) is absent from src studio/native_preview_sections.py and has '
             'no production caller; resolve per X38 (d)')
    def test_workload_hook_counts_planned_and_donated_sections(self) -> None:
        from studio.native_preview_sections import planned_preview_workload
        request = self.project.request()
        cold = planned_preview_workload(request)
        self.assertEqual((cold['windows'], cold['sectionsToRun']), (len(cold['rows']), 2 * len(cold['rows'])))
        self.assertEqual(cold['framesToRender'], cold['frames'])
        donated = planned_preview_workload({**request, 'previewSectionDonors': {'preview-picture-0': '/TEST/seal'}})
        self.assertEqual(donated['framesToRender'], cold['frames'] - cold['rows'][0]['frames'])
        self.assertEqual(donated['sectionsToRun'], cold['sectionsToRun'] - 1)

    def test_motion_preview_receipt_fields_only_for_schema_two(self) -> None:
        from studio.native_preview_schedule import schedule_summary
        packet = self.packet()
        summary = schedule_summary(packet, None)
        self.assertEqual(set(summary), {'schedule', 'navigation', 'uncoveredEvents'})
        self.assertEqual(summary['schedule']['windows'], preview_windows(packet))
        self.assertEqual(schedule_summary({**packet, 'schemaVersion': 1}, None), {})


class RiskEventScheduleTests(unittest.TestCase):
    """A10: long changed units preview their joins, titles and mounts, not three samples."""

    def plan(self) -> dict:
        joins = [0, 205, 444, 552, 773, 1000]
        return {'canvas': {'frameRate': '30/1', 'totalFrames': 1207,
                           'segments': [{'startFrame': start} for start in joins],
                           'titleCard': {'endFrame': 144}, 'captionViews': [{'startFrame': 0, 'endFrame': 1207}]},
                'strategy': {'pacing': {'holds': [{'startFrame': 6, 'endFrame': 135}]}},
                'expectations': [{'frame': 900}], 'audioFinishing': {'audioGain': [{'outStart': 20.0, 'outEnd': 22.5}]}}

    def packet(self, plan: dict) -> dict:
        events = risk_events(plan, [], [])
        return {'schemaVersion': 2, 'canvas': plan['canvas'], 'events': events,
                'units': [{'id': 'project', 'kind': 'project', 'startFrame': 0, 'endFrame': 1207, 'hash': 'x'}]}

    def test_events_name_every_declared_risk_frame(self) -> None:
        events = {row['frame']: row['kinds'] for row in risk_events(self.plan(), [], [])}
        self.assertEqual(events[205], ['source-join'])
        self.assertIn('title-exit', events[144])
        self.assertEqual(events[135], ['hold-end'])
        self.assertEqual(events[900], ['checkpoint'])
        self.assertEqual((events[600], events[675]), (['audio-gain'], ['audio-gain']))

    def test_caption_suppression_edges_are_named_review_events(self) -> None:
        plan = self.plan()
        plan['canvas']['captionViews'] = [{'startFrame': 144, 'endFrame': 600}, {'startFrame': 660, 'endFrame': 1207}]
        plan['canvas']['captionSuppressions'] = [
            {'startFrame': 0, 'endFrame': 144, 'reason': 'TEST title card holds'},
            {'startFrame': 600, 'endFrame': 660, 'reason': 'TEST full-frame chart'},
            {'startFrame': 'x', 'endFrame': 5000, 'reason': 'TEST malformed rows never become events'}]
        events = {row['frame']: row['kinds'] for row in risk_events(plan, [], [])}
        self.assertIn('caption-suppression-start', events[0])
        self.assertEqual(events[144], ['caption-suppression-end', 'caption-view', 'title-exit'])
        self.assertEqual(events[600], ['audio-gain', 'caption-suppression-start', 'caption-view'])
        self.assertEqual(events[660], ['caption-suppression-end', 'caption-view'])
        self.assertNotIn(5000, events)
        schedule = preview_schedule(self.packet(plan))
        self.assertTrue({144, 600, 660} <= {row['frame'] for row in schedule['navigation']}, schedule)

    def test_whole_program_change_windows_every_join_and_title_exit_within_budget(self) -> None:
        packet = self.packet(self.plan())
        schedule = preview_schedule(packet)
        covered = {row['frame'] for row in schedule['navigation']}
        self.assertTrue({144, 205, 444, 552, 773, 1000} <= covered, schedule)
        self.assertLessEqual(len(schedule['windows']), MAX_WINDOWS)
        self.assertEqual(schedule['workload']['frames'],
                         sum(row['endFrame'] - row['startFrame'] for row in schedule['windows']))
        legacy = [row for row in preview_windows({**packet, 'schemaVersion': 1})]
        self.assertFalse(any(row['startFrame'] <= 1000 < row['endFrame'] for row in legacy))

    def test_budget_reports_every_uncovered_event_explicitly(self) -> None:
        plan = self.plan()
        plan['canvas']['segments'] = [{'startFrame': frame} for frame in range(0, 1200, 90)]
        schedule = preview_schedule(self.packet(plan))
        self.assertLessEqual(len(schedule['windows']), MAX_WINDOWS)
        self.assertTrue(schedule['uncovered'])
        self.assertTrue(all(row['reason'] == 'preview-window-budget' and row['deferredTo'] == 'full-output-review'
                            for row in schedule['uncovered']))
        shown = {row['frame'] for row in schedule['navigation']} | {row['frame'] for row in schedule['uncovered']}
        self.assertTrue({frame for frame in range(90, 1200, 90)} <= shown)
        self.assertEqual(schedule['unpreviewedUnits'], [])

    def test_units_the_budget_cannot_show_are_reported(self) -> None:
        packet = self.packet(self.plan())
        packet['units'] = [{'id': f'card-{index}', 'kind': 'region', 'startFrame': index * 120,
                            'endFrame': index * 120 + 60, 'hash': 'x'} for index in range(10)]
        schedule = preview_schedule(packet)
        self.assertLessEqual(len(schedule['windows']), MAX_WINDOWS)
        self.assertTrue(schedule['unpreviewedUnits'])
        self.assertTrue(set(schedule['unpreviewedUnits']) <= set(schedule['changedUnits']))

    def test_unchanged_units_schedule_nothing(self) -> None:
        packet = self.packet(self.plan())
        self.assertEqual(preview_schedule(packet, packet)['windows'], [])

    def test_mount_scan_marks_timed_ancestors_instead_of_failing(self) -> None:
        directory = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (directory / 'index.html').write_text('<section data-start="1"><div data-composition-src="compositions/x.html">'
                                              '</div></section><div data-composition-src="compositions/y.html"></div>')
        self.assertEqual([row['__timed__'] for row in mount_rows(directory)], [True, False])


class CaptionSuppressionIdentityTests(unittest.TestCase):
    """A reasoned caption suppression is a picture edit: previews rerun, the audio identity stays."""

    def test_suppression_changes_picture_dependencies_but_not_audio_identity(self) -> None:
        from _native_audio_stage_fixture import AudioProjectFixture, canvas
        from studio.native_audio_contract import audio_input_contract, audio_input_identity
        base = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp'))).resolve()
        fixture = AudioProjectFixture(base)
        value = canvas()
        value['captionViews'] = [{'startFrame': 45, 'endFrame': 150, 'box': [120, 1660, 840, 160]}]
        value['captionSuppressions'] = [{'startFrame': 0, 'endFrame': 45, 'reason': 'TEST opening title holds'}]
        suppressed = fixture.write(base / 'suppressed', canvas=value)

        def identity(project: Path) -> str:
            return audio_input_identity(audio_input_contract(project, 'native-short-v1', fixture.tools))

        def packet(project: Path) -> dict:
            return short_packet({'project': str(project), 'runtime': '/TEST/runtime', 'tools': fixture.tools,
                                 'captureMode': 'sdk-streaming', 'sourceCacheMode': 'acquire-sdk-preflight',
                                 'audioProfile': 'TEST', 'pins': {}})
        self.assertEqual(identity(suppressed), identity(fixture.project))
        before, after = packet(fixture.project), packet(suppressed)
        self.assertNotEqual(after['sharedHash'], before['sharedHash'])
        self.assertEqual(changed(after, before), {row['id'] for row in after['units']})
        self.assertIn('caption-suppression-end', {kind for row in after['events'] for kind in row['kinds']})


if __name__ == '__main__':
    unittest.main()

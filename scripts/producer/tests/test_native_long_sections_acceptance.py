"""Independent section acceptance: real dependency/seal readers, synthetic owners.

These checks establish orchestration contracts only. No browser, decode, audible
playback, production timing or representative Long quality is claimed.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from _native_long_sections_acceptance_fixture import CANVAS, HTML, LongSectionsFixture
from studio.native_export_history import register_attempt
from studio.native_runtime import digest
from studio.native_segments import owners
from studio.native_segments import supervision
from studio.native_segments.dependency import picture_changes
from studio.native_segments.plan import repair_long_plan
from studio.native_segments.reviews import SectionReviewPending, assembly_snapshot, review_pins
from studio.native_short_pipeline import NativeShortPipeline, NativeStageFailure


class LongSectionsAcceptanceTests(unittest.TestCase):
    """A failed C must not discard verified A/B or accept unsealed partial media."""

    def setUp(self) -> None:
        """Isolate all stage bytes; fake owners never acquire the user's render pool."""
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.enterContext(patch('studio.native_export_history.history_directory',
                                return_value=self.base / 'history'))
        self.fixture = LongSectionsFixture(self.base)
        register_attempt(self.fixture.request)
        self.enterContext(patch('studio.native_short_pipeline.NativeRun',
                                side_effect=self.fixture.owner_factory))
        self.enterContext(patch.object(supervision, 'section_capacity', return_value=1))
        self.enterContext(patch.object(supervision.SectionProcesses, 'launch', autospec=True,
                                      side_effect=lambda process, phase:
                                      self.fixture.launch_section(process.pipeline, phase)))

    def fail_last(self) -> NativeShortPipeline:
        """Finish A/B through real seal validation, then fail C's synthetic owner."""
        self.fixture.failures['segment-picture-2'] = True
        pipeline = NativeShortPipeline(self.fixture.request, {})
        with self.assertRaises(NativeStageFailure):
            owners.run_revision_windows(pipeline)
        return pipeline

    def test_failed_c_keeps_sealed_a_b_and_c_cannot_satisfy_currentness(self) -> None:
        """Completion receipts require successful ownership, not merely a media path."""
        pipeline = self.fail_last()
        for phase in ('segment-picture-0', 'segment-picture-1'):
            row = owners.current_window(pipeline.request, phase)
            self.assertEqual(row['piece']['sha256'], digest(Path(row['piece']['path'])))
        self.fixture.write_phase('segment-picture-2', pipeline.root)
        with self.assertRaises((ValueError, FileNotFoundError)):
            owners.current_window(pipeline.request, 'segment-picture-2')
        self.assertFalse((pipeline.root / 'picture.mp4').exists())

    def test_restart_reuses_a_b_bytes_and_runs_only_c(self) -> None:
        """Original sealed artifacts remain byte-identical after donor restoration."""
        pipeline = self.fail_last()
        before = {file.name: digest(file) for file in pipeline.root.iterdir()}
        request = self.fixture.restart()
        with patch.object(owners, 'known_attempts', return_value=[pipeline.root]):
            request = owners.bind_window_recovery(request)
        self.fixture.write_request(request)
        register_attempt(request)
        self.fixture.calls.clear()
        self.fixture.failures.clear()
        resumed = NativeShortPipeline(request, {})
        owners.run_revision_windows(resumed)
        self.assertEqual([label for label, _ in self.fixture.calls], ['segment-picture-2'])
        self.assertEqual(before, {file.name: digest(file) for file in pipeline.root.iterdir()})
        for phase in ('segment-picture-0', 'segment-picture-1', 'segment-picture-2'):
            self.assertEqual(owners.current_window(request, phase)['window']['id'],
                             f"section-{int(phase.rsplit('-', 1)[1]):03d}")

    def test_corrupt_saved_a_refuses_recovery_instead_of_reusing_it(self) -> None:
        """A saved filename cannot replace a matching seal and actual matching bytes."""
        pipeline = self.fail_last()
        row = owners.current_window(pipeline.request, 'segment-picture-0')
        Path(row['piece']['path']).write_bytes(b'TEST corrupted retained section')
        with patch.object(owners, 'known_attempts', return_value=[pipeline.root]):
            with self.assertRaises(ValueError):
                owners.bind_window_recovery(self.fixture.restart())

    def test_local_b_dependency_edit_preserves_a_c_technical_identities(self) -> None:
        """Actual immutable HTML comparison drives B repair and both adjacent joins."""
        child = self.base / 'child'
        shutil.copytree(self.fixture.project, child)
        (child / 'index.html').write_text(HTML.format(middle='B corrected'))
        changes = picture_changes(self.fixture.project, child)
        repaired = repair_long_plan(self.fixture.request['revision'], changes, CANVAS)
        self.assertEqual(repaired['repair']['affectedSections'], [1])
        self.assertEqual(repaired['repair']['recheckJoins'], [0, 1])
        for index in (0, 2):
            self.assertEqual(repaired['renderWindows'][index],
                             self.fixture.request['revision']['renderWindows'][index])
        self.assertGreater(repaired['renderWindows'][1]['generation'], 1)

    def test_global_css_change_invalidates_all_sections(self) -> None:
        """A shared style edit must widen beyond the local section that noticed it."""
        child = self.base / 'global'
        shutil.copytree(self.fixture.project, child)
        html = HTML.format(middle='B').replace('<body>', '<style>*{font-size:40px}</style><body>')
        (child / 'index.html').write_text(html)
        changes = picture_changes(self.fixture.project, child)
        repaired = repair_long_plan(self.fixture.request['revision'], changes, CANVAS)
        self.assertEqual(repaired['repair']['affectedSections'], [0, 1, 2])
        self.assertEqual(repaired['repair']['technicalReuseSections'], [])

    def reviewed_request(self, mutation: str | None = None) -> dict:
        """Complete fake owners and pin a separately created fictional review bundle."""
        owners.run_revision_windows(NativeShortPipeline(self.fixture.request, {}))
        file, bundle = self.fixture.review_bundle()
        row = bundle['reviews'][1]
        if mutation == 'stale':
            row['generation'] += 1
        elif mutation == 'failed':
            row['checks']['neighboringContext'] = False
        elif mutation == 'self-review':
            row['reviewerTaskId'] = row['authorTaskId']
        elif mutation == 'missing':
            bundle['reviews'].pop()
        elif mutation == 'old-neighbors':
            bundle['reviews'][0]['planIdentity'] = 'b' * 64
        file.write_text(json.dumps(bundle))
        request = self.fixture.restart()
        request['sectionReviews'] = str(file)
        request['pins'].update(review_pins(file))
        with patch.object(owners, 'known_attempts', return_value=[self.fixture.root]):
            request = owners.bind_window_recovery(request)
        self.fixture.write_request(request)
        register_attempt(request)
        owners.run_revision_windows(NativeShortPipeline(request, {}))
        return request

    def test_all_seals_without_independent_reviews_block_assembly(self) -> None:
        """Technical section completion alone never grants the final join."""
        owners.run_revision_windows(NativeShortPipeline(self.fixture.request, {}))
        with self.assertRaises(SectionReviewPending):
            assembly_snapshot(self.fixture.request)

    def test_long_pipeline_saves_sections_but_does_not_start_join_without_qc(self) -> None:
        """The real Long render entry must enforce the barrier before its picture owner."""
        pipeline = NativeShortPipeline(self.fixture.request, {})
        with patch('studio.native_motion_previews.require_motion_previews', return_value={}):
            with self.assertRaises(SectionReviewPending):
                pipeline.render()
        self.assertEqual([label for label, _ in self.fixture.calls],
                         ['segment-picture-0', 'segment-picture-1', 'segment-picture-2'])
        self.assertFalse((pipeline.root / 'picture.mp4').exists())
        self.assertFalse((pipeline.root / 'render-stage.json').exists())

    def test_missing_early_preview_evidence_launches_no_section_owner(self) -> None:
        """Known missing early evidence is rejected before expensive section dispatch."""
        with self.assertRaises((ValueError, FileNotFoundError)):
            NativeShortPipeline(self.fixture.request, {}).render()
        self.assertEqual(self.fixture.calls, [])

    def test_current_reviews_of_restored_sections_allow_frozen_snapshot(self) -> None:
        """Approval follows the exact retained bytes despite a fresh output directory."""
        request = self.reviewed_request()
        snapshot = assembly_snapshot(request)
        self.assertEqual(len(snapshot['sections']), 3)
        self.assertEqual(snapshot['planIdentity'], request['revision']['identity'])

    def test_stale_review_blocks_assembly(self) -> None:
        """An old or future section generation cannot approve the current bytes."""
        request = self.reviewed_request('stale')
        with self.assertRaisesRegex(ValueError, 'stale section review'):
            assembly_snapshot(request)

    def test_failed_join_context_blocks_assembly(self) -> None:
        """Each section must include passing neighboring-context review."""
        request = self.reviewed_request('failed')
        with self.assertRaisesRegex(ValueError, 'missing or failing'):
            assembly_snapshot(request)

    def test_self_review_blocks_assembly(self) -> None:
        """Assigned authors cannot also supply their independent acceptance."""
        request = self.reviewed_request('self-review')
        with self.assertRaisesRegex(ValueError, 'independent reviewer'):
            assembly_snapshot(request)

    def test_missing_c_review_blocks_assembly(self) -> None:
        """Two approved sections cannot produce a truncated final program."""
        request = self.reviewed_request('missing')
        with self.assertRaisesRegex(ValueError, 'omit or duplicate'):
            assembly_snapshot(request)

    def test_unchanged_section_with_old_neighbor_review_blocks_assembly(self) -> None:
        """Identical A bytes cannot retain a join judgment from an older shared plan."""
        request = self.reviewed_request('old-neighbors')
        with self.assertRaisesRegex(ValueError, 'neighboring-context review'):
            assembly_snapshot(request)

    def test_review_evidence_changes_after_freeze_block_assembly(self) -> None:
        """Changing a recorded judgment invalidates the assembly's exact snapshot."""
        request = self.reviewed_request()
        assembly_snapshot(request)
        (self.base / 'TEST-review-evidence.txt').write_text('TEST changed after freeze')
        with self.assertRaisesRegex(ValueError, 'evidence changed'):
            assembly_snapshot(request)

    def test_capacity_two_runs_two_owners_and_queues_third(self) -> None:
        """The dispatcher respects supplied qualified capacity without granting new slots."""
        gate, lock = threading.Barrier(2), threading.Lock()
        active, peak = set(), [0]

        def launch(process: object, phase: str) -> dict:
            """Hold the first pair concurrently before writing real stage seals."""
            with lock:
                active.add(phase)
                peak[0] = max(peak[0], len(active))
            if phase in ('segment-picture-0', 'segment-picture-1'):
                gate.wait(timeout=5)
            try:
                return self.fixture.launch_section(process.pipeline, phase)
            finally:
                with lock:
                    active.remove(phase)

        with patch.object(supervision, 'section_capacity', return_value=2):
            with patch.object(supervision.SectionProcesses, 'launch', new=launch):
                owners.run_revision_windows(NativeShortPipeline(self.fixture.request, {}))
        self.assertEqual(peak[0], 2)
        self.assertEqual(len(self.fixture.calls), 3)
        for index in range(3):
            owners.current_window(self.fixture.request, f'segment-picture-{index}')

    def test_newer_recorded_attempt_blocks_old_frozen_assembly(self) -> None:
        """A later launch supersedes an otherwise unchanged approved older request."""
        request = self.reviewed_request()
        assembly_snapshot(request)
        later_root = self.base / 'later'
        later_root.mkdir()
        newer = {**request, 'output': str(later_root), 'sectionAttemptSequence': 3}
        self.fixture.write_request(newer)
        register_attempt(newer)
        with self.assertRaisesRegex(ValueError, 'superseded'):
            assembly_snapshot(request)

    def test_superseded_final_result_publishes_failure_not_checked_delivery(self) -> None:
        """A late final QC callback cannot promote an older completed assembly."""
        request = self.reviewed_request()
        root = Path(request['output'])
        (root / 'revision-picture.json').write_text(json.dumps({'sectionSnapshot': assembly_snapshot(request)}))
        newer_root = self.base / 'replacement'
        newer_root.mkdir()
        newer = {**request, 'output': str(newer_root), 'sectionAttemptSequence': 3}
        self.fixture.write_request(newer)
        register_attempt(newer)
        result = {'status': 'native-long-checked-for-review'}
        NativeShortPipeline(request, {}).publish_delivery(result)
        delivered = json.loads((root / 'delivery.json').read_text())
        self.assertEqual(delivered['status'], 'failed')
        self.assertEqual(delivered['failureCategory'], 'section-publication-stale')

    def test_failed_whole_program_qc_never_becomes_checked_delivery(self) -> None:
        """Passing individual section checks does not waive the final verification owner."""
        request = self.reviewed_request()
        root = Path(request['output'])
        self.fixture.write_media(root)
        self.fixture.failures['verification'] = True
        with self.assertRaises(NativeStageFailure):
            NativeShortPipeline(request, {}).verify(digest(root / 'review.mp4'))
        self.assertFalse((root / 'delivery.json').exists())


if __name__ == '__main__':
    unittest.main()

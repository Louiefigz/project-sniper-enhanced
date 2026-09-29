"""Public Long chunk contract readers over real private files; no editorial/media qualification."""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import argparse
import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _native_long_isolation_fixture import write_static_project
from studio.native_long_chunk_evidence import CONTRACT, boundary_frames, boundary_neighbors, chunk_geometry, transition_evidence
from studio.native_long_chunks import (KIND, bind_chunk_request, read_chunk_contract, require_chunk_request,
                                       require_chunk_review, scoped_chunk_inputs, validate_chunk_options)
from studio.native_long_options import section_boundaries
from studio.native_long_prebuild import prebuild_snapshot
from studio.native_segments.long_plan import initial_long_plan
from studio.native_segments.dependency import picture_changes
from studio.production.section_plan import pin_file, read_plan


class ChunkAdmissionTests(unittest.TestCase):
    """Use exact registered-plan shapes and explicit TEST authored transition assessments."""

    def setUp(self) -> None:
        """Freeze the shared creative geometry before writing the authored chunk contract."""
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.canvas = {'width': 320, 'height': 180, 'frameRate': '25/1', 'totalFrames': 15000}
        self.project = write_static_project(self.base / 'project', self.canvas, ('A', 'B'))
        self.plan = {'canvas': self.canvas, 'scenes': [{'startFrame': start, 'endFrame': start + 1500,
                     'mediaIds': []} for start in range(0, 15000, 1500)]}
        self.write(self.project / 'LONG-PROJECT.json', self.plan)
        shared = self.base / 'creative.txt'
        shared.write_text('TEST shared creative plan; no independent approval')
        self.planfile = self.base / 'assignments.json'
        self.write(self.planfile, {'schemaVersion': 1, 'kind': 'native-long-section-assignments',
            'authority': str(self.base / 'authority'), 'batchId': 'test-batch', 'clipId': 'test-long',
            'directorTaskId': 'test-director', 'deadlineElapsed': 3600, 'outputRoot': str(self.base / 'owned'),
            'sharedPlan': pin_file(shared), 'assignments': [{'sectionId': key, 'generation': 1,
            'frameRange': [index * 7500, (index + 1) * 7500], 'inputs': [pin_file(shared)],
            'projectFiles': {'composition.html': f'compositions/unit-{index}.html'}} for index, key in enumerate(('A', 'B'))]})
        self.context = read_plan(self.planfile)
        self.geometry = chunk_geometry(self.project, self.context)
        self.value = self.authored_contract()
        self.publish()

    def write(self, file: Path, value: dict) -> None:
        """Write an isolated fixture artifact, never a production review."""
        file.write_text(json.dumps(value))

    def publish(self) -> None:
        """Publish the current TEST authored contract for the actual cold reader."""
        self.write(self.project / CONTRACT, self.value)

    def authored_contract(self) -> dict:
        """Supply explicit TEST purposes instead of allowing the engine to manufacture assessments."""
        transitions = []
        for index, frame in enumerate(boundary_frames(self.geometry)):
            owners = list(dict.fromkeys(row['sectionId'] for row in boundary_neighbors(self.geometry, frame)))
            span = [frame - 1, frame + 1]
            transitions.append({'id': f'join-{index}', 'version': 1, 'frame': frame,
                'purpose': 'TEST authored scene handoff', 'ownerSectionId': owners[0], 'frameRange': span,
                'neighborSectionIds': owners, 'clockPolicy': 'absolute-no-restart',
                'continuity': {key: 'TEST authored assessment; no real playback claim'
                               for key in ('imagery', 'motion', 'layering', 'audio', 'captions')},
                **transition_evidence(self.project, self.geometry, span)})
        assignments = []
        for declared, mapping in zip(self.context['assignments'], self.geometry['maps']):
            assignments.append({key: declared[key] for key in ('sectionId', 'generation', 'inputIdentity', 'frameRange')} |
                {'mapIdentity': mapping['identity'], 'chunks': [{'id': row['id'], 'frameRange': row['frameRange'],
                  'purpose': 'TEST natural scene group'} for row in mapping['chunks']],
                 'transitionIds': [row['id'] for row in transitions if declared['sectionId'] in row['neighborSectionIds']]})
        return {'schemaVersion': 1, 'kind': KIND, 'sectionPlan': self.context['plan'],
                'assignments': assignments, 'transitions': transitions}

    def request(self) -> dict:
        """Create a synthetic admitted request shape; real source/render gates remain separate."""
        file = self.project / CONTRACT
        return {'adapter': 'native-long', 'project': str(self.project),
                'sectionProduction': self.context,
                'revision': initial_long_plan(self.canvas, 'a' * 64, self.geometry['encoderBoundaries']),
                'pins': {str(file): pin_file(file)['sha256']},
                'prebuildReview': {'status': 'recorded-independent-plan-pass', 'scope': 'native-long-full-project'}}

    def args(self, **changes: object) -> argparse.Namespace:
        """Model the public Long options without creating any budget launch."""
        return argparse.Namespace(**({'project': self.project, 'chunks': True, 'section_plan': self.planfile,
                                      'resume_from': None, 'repair_from': None} | changes))

    def test_public_geometry_and_worker_request_bind_current_authored_contract(self) -> None:
        """The explicit option derives encoder geometry and cold-checks it again at launch."""
        validate_chunk_options(self.args(), self.project)
        self.assertEqual(section_boundaries(self.args(), self.canvas), self.geometry['encoderBoundaries'])
        request = bind_chunk_request(self.request())
        require_chunk_request(request)
        self.assertEqual(len(request['sectionChunks']['assignments']), 2)
        del request['sectionChunks']
        with self.assertRaisesRegex(ValueError, 'worker admission'):
            require_chunk_request(request)

    def test_option_cannot_silently_omit_contract_or_assignment_plan(self) -> None:
        """Legacy Long stays available, but opting into chunks requires the whole new contract."""
        with self.assertRaisesRegex(ValueError, 'explicit --chunks'):
            validate_chunk_options(self.args(chunks=False), self.project)
        with self.assertRaisesRegex(ValueError, 'section-plan'):
            validate_chunk_options(self.args(section_plan=None), self.project)
        request = self.request()
        (self.project / CONTRACT).unlink()
        with self.assertRaisesRegex(ValueError, 'requires authored'):
            validate_chunk_options(self.args(), self.project)
        validate_chunk_options(self.args(chunks=False), self.project)
        self.assertNotIn('sectionChunks', bind_chunk_request(request))

    def test_existing_independent_prebuild_must_explicitly_review_contract_bytes(self) -> None:
        """Hash-current whole-project review cannot omit this specific authored transition evidence."""
        with self.assertRaisesRegex(ValueError, 'explicit independent'):
            require_chunk_review(self.project, {'evidence': []})
        pin = pin_file(self.project / CONTRACT)
        require_chunk_review(self.project, {'evidence': [{'path': pin['path'], 'sha256': pin['sha256']}]})
        with patch('studio.native_long_prebuild.require_current_long_policy'):
            snapshot = prebuild_snapshot(self.project)
        self.assertEqual(snapshot['pins'][str(self.planfile)], self.context['plan']['sha256'])
        self.assertEqual(snapshot['pins'][pin['path']], pin['sha256'])

    def test_empty_purpose_missing_neighbor_and_restart_are_refused(self) -> None:
        """Recorded purposes, single ownership and clock continuity cannot be unchecked flags."""
        original = copy.deepcopy(self.value)
        for update in ({'purpose': ' '}, {'ownerSectionId': 'stranger'}, {'neighborSectionIds': []},
                       {'clockPolicy': 'restart-local'}, {'frameRange': [1499, 1500]}):
            self.value = copy.deepcopy(original)
            self.value['transitions'][0].update(update)
            self.publish()
            with self.subTest(update=update), self.assertRaises(ValueError):
                read_chunk_contract(self.project)

    def test_changed_actual_source_or_transition_state_is_not_current(self) -> None:
        """Recorded dependency prose cannot substitute for the actual current executable bytes."""
        file = self.project / 'compositions/unit-0.html'
        file.write_text(file.read_text().replace('>A<', '>changed<'))
        with self.assertRaisesRegex(ValueError, 'source or state evidence changed'):
            read_chunk_contract(self.project)

    def test_shared_transition_change_invalidates_both_neighbor_projections(self) -> None:
        """A boundary owned once still participates in the dependency closure on each side."""
        before = [scoped_chunk_inputs(self.project, bounds) for bounds in ([7000, 7500], [7500, 8000], [0, 250])]
        row = next(row for row in self.value['transitions'] if row['frame'] == 7500)
        row['version'] += 1
        row['continuity']['imagery'] = 'TEST changed current boundary imagery assessment'
        self.publish()
        after = [scoped_chunk_inputs(self.project, bounds) for bounds in ([7000, 7500], [7500, 8000], [0, 250])]
        self.assertNotEqual(before[0], after[0])
        self.assertNotEqual(before[1], after[1])
        self.assertEqual(before[2], after[2])

    def test_encoder_geometry_and_prebuild_status_cannot_be_forged(self) -> None:
        """A current contract does not bypass existing prebuild or exact window checks."""
        request = self.request()
        request['prebuildReview']['status'] = 'pending'
        with self.assertRaisesRegex(ValueError, 'prebuild admission'):
            bind_chunk_request(request)
        request = self.request()
        request['revision']['renderWindows'][0]['startFrame'] = 1
        with self.assertRaisesRegex(ValueError, 'manifest changed'):
            bind_chunk_request(request)

    def test_repair_dependency_reader_invalidates_only_both_transition_sides(self) -> None:
        """An updated boundary contract uses the existing repair authority without global widening."""
        previous = self.base / 'previous'
        shutil.copytree(self.project, previous)
        row = next(row for row in self.value['transitions'] if row['frame'] == 7500)
        row['continuity']['imagery'] = 'TEST revised boundary state'
        self.publish()
        with self.assertRaisesRegex(ValueError, 'advance its version'):
            picture_changes(previous, self.project)
        row['version'] += 1
        self.publish()
        changes = picture_changes(previous, self.project)
        self.assertFalse(changes['global'])
        self.assertEqual(changes['ranges'], [[7499, 7501]])

    def test_source_subject_digest_does_not_form_a_contract_self_reference(self) -> None:
        """Source selection stays bound while its derived whole-subject hash remains independently admitted."""
        file = self.project / 'VISUAL-SOURCES.json'
        self.write(file, {'subjectSha256': 'a' * 64, 'decisions': ['TEST admitted source choice']})
        self.geometry = chunk_geometry(self.project, self.context)
        self.value = self.authored_contract()
        self.publish()
        first = read_chunk_contract(self.project)
        self.write(file, {'subjectSha256': 'b' * 64, 'decisions': ['TEST admitted source choice']})
        self.assertEqual(first['value'], read_chunk_contract(self.project)['value'])
        self.write(file, {'subjectSha256': 'b' * 64, 'decisions': ['TEST changed actual source choice']})
        with self.assertRaisesRegex(ValueError, 'source or state evidence changed'):
            read_chunk_contract(self.project)

    def test_global_widening_cannot_skip_transition_version_fencing(self) -> None:
        """Even a mandatory full rerender must preserve each changed transition's immutable version history."""
        shared = self.project / 'shared-policy.txt'
        shared.write_text('TEST shared initial policy')
        self.geometry = chunk_geometry(self.project, self.context)
        self.value = self.authored_contract()
        self.publish()
        previous = self.base / 'global-parent'
        shutil.copytree(self.project, previous)
        shared.write_text('TEST changed shared policy')
        self.geometry = chunk_geometry(self.project, self.context)
        self.value = self.authored_contract()
        self.publish()
        with self.assertRaisesRegex(ValueError, 'advance its version'):
            picture_changes(previous, self.project)
        for row in self.value['transitions']:
            row['version'] += 1
        self.publish()
        self.assertTrue(picture_changes(previous, self.project)['global'])


if __name__ == '__main__':
    unittest.main()

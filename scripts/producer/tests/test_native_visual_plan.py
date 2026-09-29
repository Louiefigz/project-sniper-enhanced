"""Native Long projects retain the allocated whole-project visual plan."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from _visual_plan_fixture import (
    candidate, opportunity, reseal_controller_authorities, visual_plan,
)
from planner.visual_plan_allocator import allocate_visual_plan
from planner.visual_plan_contract import invalidation_inputs
from planner.catalog_receipt_issuer import issue_catalog_receipts
from studio.native_visual_plan import (
    same_audio_reuse_identity,
    validate_long_visual_plan,
    visual_plan_reuse_identity,
)
from studio.native_visual_plan_application import (
    _catalog_bindings,
    validate_long_visual_plan_application,
)
from studio.native_visual_execution_binding import validate_execution_binding


class NativeVisualPlanTests(unittest.TestCase):
    """Validate the external binding, native route, and frozen project bytes."""

    def fixture(self, root: Path, route_class: str = 'native') -> tuple[dict, Path]:
        """Write one allocated Long plan and return its Long-project binding."""
        row = candidate('candidate:visual', 'custom-native',
                        routeClass=route_class)
        value = visual_plan(opportunity('opportunity:visual', 0, [row]))
        value['project']['mode'] = 'long'
        value['project']['aspect'] = '16:9'
        reseal_controller_authorities(value)
        allocated = allocate_visual_plan(value)
        source = root / 'source-visual-plan.json'
        source.write_text(json.dumps(allocated), encoding='utf-8')
        content = source.read_bytes()
        binding = {'schemaVersion': 1, 'path': str(source),
                   'byteHash': hashlib.sha256(content).hexdigest(),
                   **invalidation_inputs(allocated)}
        (root / 'VISUAL-PLAN.json').write_bytes(content)
        return {'visualPlan': binding}, source

    def application_fixture(self, project: Path) -> dict:
        """Bind the selected catalog candidate to one real mounted Long implementation."""
        plan, source = self.fixture(project)
        visual = json.loads(source.read_text())
        opportunity = visual['opportunities'][0]
        decision = visual['allocation']['decisions'][0]
        candidate_row = opportunity['candidates'][0]
        html = '<div id="visual-root" data-start="0" data-duration="0.8"></div>'
        (project / 'index.html').write_text(html)
        plan.update(schemaVersion=2,
                    canvas={'frameRate': '30/1'},
                    scenes=[{'startFrame': 0, 'endFrame': 30, 'mediaIds': [],
                             'visualIds': ['visual-root']}],
                    visualPlanApplication={
                        'schemaVersion': 1, 'route': 'native-long',
                        'visualPlanSha256': plan['visualPlan']['visualPlanSha256'],
                        'decisions': [{
                            'opportunityId': decision['opportunityId'],
                            'candidateId': decision['candidateId'],
                            'anatomy': candidate_row['composition']['anatomy'],
                            'development': candidate_row['composition']['development'],
                            'startFrame': opportunity['timing']['startFrame'],
                            'endFrameExclusive': opportunity['timing']['endFrameExclusive'],
                            'sceneIndexes': [0], 'visibleIds': ['visual-root'],
                            'catalogBindings': [],
                            'binding': {'kind': 'custom-native',
                                'visibleIds': ['visual-root'],
                                'implementationSha256': hashlib.sha256(
                                    html.encode()).hexdigest(),
                                'outputRange': opportunity['timing']},
                        }],
                    })
        return plan

    def test_native_long_route_binds_frozen_plan(self) -> None:
        """An allocated native Long plan contributes its frozen project pin."""
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw).resolve()
            plan, _source = self.fixture(project)
            self.assertEqual(validate_long_visual_plan(project, plan), {
                plan['visualPlan']['path']: plan['visualPlan']['byteHash'],
                str(project / 'VISUAL-PLAN.json'): plan['visualPlan']['byteHash']})

    def test_native_long_catalog_plan_rechecks_receipt_authority(self) -> None:
        """A full-catalog winner remains admissible through the Long cold reader."""
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw).resolve()
            row = candidate('candidate:catalog', 'catalog', routeClass='native')
            value = visual_plan(opportunity('opportunity:catalog', 0, [row]))
            value['project']['mode'] = 'long'; value['project']['aspect'] = '16:9'
            reseal_controller_authorities(value)
            issued = issue_catalog_receipts(value, str(project))
            source = project / 'source-catalog-plan.json'
            source.write_text(json.dumps(issued.plan), encoding='utf-8')
            content = source.read_bytes()
            binding = {'schemaVersion': 1, 'path': str(source),
                       'byteHash': hashlib.sha256(content).hexdigest(),
                       **invalidation_inputs(issued.plan, issued.authority),
                       'catalogReceiptAuthority': issued.authority}
            (project / 'VISUAL-PLAN.json').write_bytes(content)
            pins = validate_long_visual_plan(project, {'visualPlan': binding})
            self.assertEqual(pins[issued.authority['path']], issued.authority['sha256'])

    def test_wrong_route_or_changed_source_is_rejected(self) -> None:
        """Ordinary allocation and post-binding mutation cannot enter native Long."""
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw).resolve()
            ordinary, _source = self.fixture(project, 'compatibility')
            with self.assertRaisesRegex(ValueError, 'native-long'):
                validate_long_visual_plan(project, ordinary)
            native, source = self.fixture(project)
            source.write_text(source.read_text() + ' ', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'source changed'):
                validate_long_visual_plan(project, native)

    def test_changed_frozen_copy_is_rejected(self) -> None:
        """The project copy cannot drift from the bound planning authority."""
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw).resolve()
            plan, _source = self.fixture(project)
            (project / 'VISUAL-PLAN.json').write_text('{}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'differs'):
                validate_long_visual_plan(project, plan)

    def test_visual_change_invalidates_picture_but_preserves_audio_authority(self) -> None:
        """Split hashes allow audio reuse only when upstream/audio inputs stay exact."""
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw).resolve()
            first, _source = self.fixture(project)
            first['audio'] = {'file': 'audio/program.wav'}
            changed = json.loads(json.dumps(first))
            changed['visualPlan']['pictureInputSha256'] = 'd' * 64
            first_identity = visual_plan_reuse_identity(first, 'dialogue-v1')
            changed_identity = visual_plan_reuse_identity(changed, 'dialogue-v1')
            self.assertNotEqual(first_identity['pictureInputSha256'],
                                changed_identity['pictureInputSha256'])
            self.assertEqual(first_identity['audioReuseSha256'],
                             changed_identity['audioReuseSha256'])
            self.assertTrue(same_audio_reuse_identity(
                {'visualPlanReuse': first_identity},
                {'visualPlanReuse': changed_identity}))
            changed['visualPlan']['upstreamAuthoritySha256'] = 'e' * 64
            upstream = visual_plan_reuse_identity(changed, 'dialogue-v1')
            self.assertNotEqual(first_identity['audioReuseSha256'],
                                upstream['audioReuseSha256'])

    def test_native_long_application_binds_every_allocation_to_executable_bytes(self) -> None:
        """Selected plan candidates cannot be omitted or swapped during Long authoring."""
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw).resolve()
            plan = self.application_fixture(project)
            pins = validate_long_visual_plan_application(project, plan)
            self.assertIn(str(project / 'VISUAL-PLAN.json'), pins)
            changed = json.loads(json.dumps(plan))
            changed['visualPlanApplication']['decisions'][0]['candidateId'] = 'other'
            with self.assertRaisesRegex(ValueError, 'differs from its allocation'):
                validate_long_visual_plan_application(project, changed)
            missing = json.loads(json.dumps(plan))
            missing['visualPlanApplication']['decisions'] = []
            with self.assertRaisesRegex(ValueError, 'cover every allocation'):
                validate_long_visual_plan_application(project, missing)
            unrelated = json.loads(json.dumps(plan))
            unrelated['scenes'][0]['visualIds'] = ['unrelated-global-id']
            with self.assertRaisesRegex(ValueError, 'scene visual ownership'):
                validate_long_visual_plan_application(project, unrelated)
            (project / 'index.html').write_text(
                '<div id="visual-root" data-start="0.1" data-duration="0.7" '
                'data-composition-src="compositions/visual.html"></div>')
            with self.assertRaisesRegex(ValueError, 'executable timing'):
                validate_long_visual_plan_application(project, plan)
            (project / 'index.html').write_text(
                '<div id="visual-root" data-start="0" data-duration="0.8"></div>')
            drift = json.loads(json.dumps(plan))
            drift['styleApplication'] = {'choices': [{
                'sceneIndex': 0, 'visibleIds': ['visual-root'],
                'anatomy': 'split-card', 'development': 'different reveal'}]}
            with self.assertRaisesRegex(ValueError, 'disagree on composition development'):
                validate_long_visual_plan_application(project, drift)

    def test_native_long_custom_binding_rejects_implementation_substitution(self) -> None:
        """An ID-preserving HTML substitution cannot retain custom execution authority."""
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw).resolve()
            plan = self.application_fixture(project)
            (project / 'index.html').write_text(
                '<div id="visual-root" data-start="0" data-duration="0.8">changed</div>')
            with self.assertRaisesRegex(ValueError, 'binding differs'):
                validate_long_visual_plan_application(project, plan)

    def test_native_long_media_transition_presenter_and_omit_bind_exact_facts(self) -> None:
        """Every non-catalog modality derives authority from literal project bytes."""
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw).resolve()
            assets = project / 'assets'; assets.mkdir()
            source = assets / 'source.mp4'; source.write_bytes(b'exact staged media')
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            timing = {'startFrame': 0, 'endFrameExclusive': 24}
            video = ('<video id="media" src="assets/source.mp4" data-start="0" '
                     'data-duration="0.8" data-media-start="2"></video>')
            context = {'project': project, 'plan': {'canvas': {'frameRate': '30/1'}},
                       'html': video, 'timing': timing}
            source_range = {'startFrame': 60, 'endFrameExclusive': 84}
            common = {'elementId': 'media', 'assetFile': 'assets/source.mp4',
                      'sourceSha256': digest, 'sourceRange': source_range,
                      'outputRange': timing,
                      'elementSha256': hashlib.sha256(video.encode()).hexdigest()}
            item = {'catalogBindings': [], 'binding': {
                'kind': 'media', 'sourceRecordId': 'asset:one', **common}}
            candidate_row = {'modality': 'source-footage', 'source': {
                'recordId': 'asset:one', 'sourceSha256': digest,
                'range': source_range}}
            validate_execution_binding(context, item, candidate_row, ['media'])
            item['binding']['sourceSha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'binding differs'):
                validate_execution_binding(context, item, candidate_row, ['media'])
            presenter = {'catalogBindings': [], 'binding': {
                'kind': 'presenter', **common}}
            validate_execution_binding(context, presenter,
                                       {'modality': 'presenter'}, ['media'])
            seam = ('<div id="seam" data-start="0" data-duration="0.8" '
                    'data-transition-kind="whip"></div>')
            transition = {'catalogBindings': [], 'binding': {
                'kind': 'transition', 'elementId': 'seam', 'outputRange': timing,
                'mechanism': 'whip',
                'configurationSha256': hashlib.sha256(seam.encode()).hexdigest()}}
            validate_execution_binding({**context, 'html': seam}, transition,
                                       {'modality': 'transition'}, ['seam'])
            validate_execution_binding(context,
                                       {'catalogBindings': [], 'binding': {'kind': 'omit'}},
                                       {'modality': 'omit'}, [])

    def test_native_long_application_rejects_catalog_claim_for_custom_work(self) -> None:
        """A non-catalog winner cannot claim catalog execution evidence."""
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw).resolve()
            plan = self.application_fixture(project)
            plan['visualPlanApplication']['decisions'][0]['catalogBindings'] = [{
                'file': 'compositions/visual.html',
                'mountId': 'visual-root',
                'catalogId': 'catalog:forged',
                'sourceSha256': 'a' * 64,
                'implementationSha256': 'b' * 64,
            }]
            with self.assertRaisesRegex(ValueError, 'non-catalog'):
                validate_long_visual_plan_application(project, plan)

    def test_reference_catalog_requires_project_owned_adaptation(self) -> None:
        """A reference mirror cannot be mounted directly as its implementation."""
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw).resolve()
            compositions = project / 'compositions'; compositions.mkdir()
            source = compositions / 'reference.html'
            source.write_text('<template>reference</template>', encoding='utf-8')
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            relative = 'compositions/reference.html'
            html = f'<div id="mount" data-composition-src="{relative}"></div>'
            candidate_row = {'modality': 'catalog',
                             'source': {'recordId': 'catalog:one',
                                        'sourceSha256': digest},
                             'catalogAdmission': {'executionStatus': 'reference'}}
            binding = [{'file': relative, 'mountId': 'mount',
                        'catalogId': 'catalog:one', 'sourceSha256': digest,
                        'implementationSha256': digest}]
            context = {'project': project, 'html': html}
            with self.assertRaisesRegex(ValueError, 'project-owned adaptation'):
                _catalog_bindings(context, binding, candidate_row, ['mount'])
            source.write_text('<template>adapted</template>', encoding='utf-8')
            binding[0]['implementationSha256'] = hashlib.sha256(
                source.read_bytes()).hexdigest()
            _catalog_bindings(context, binding, candidate_row, ['mount'])

    def test_native_long_application_rejects_unrelated_visible_element(self) -> None:
        """An unrelated element cannot stand in for the selected visual."""
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw).resolve()
            plan = self.application_fixture(project)
            plan['visualPlanApplication']['decisions'][0]['visibleIds'] = ['unrelated']
            (project / 'index.html').write_text(
                '<div id="actual" '
                'data-composition-src="compositions/visual.html"></div>')
            with self.assertRaisesRegex(ValueError, 'absent executable visual'):
                validate_long_visual_plan_application(project, plan)


if __name__ == '__main__':
    unittest.main()

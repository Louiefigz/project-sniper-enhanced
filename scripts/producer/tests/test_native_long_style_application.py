"""Native Long style applications bind current research to executable visuals."""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

from copy import deepcopy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cut_preview_io import file_hash, write_new
from graphics.catalog_discovery import load_catalog
from graphics.reference_style_vocabulary import prepare_vocabulary
from studio.native_runtime import digest
from studio.native_style_application import validate_long_style_application


class NativeLongStyleApplicationTests(unittest.TestCase):
    """Exercise the actual vocabulary freezer and Long admission contract."""

    @classmethod
    def setUpClass(cls) -> None:
        """Select two real current catalog records once for the focused suite."""
        cls.catalog = load_catalog()
        cls.refs = [row['ref'] for row in cls.catalog.records if row['source']['exists']][:2]
        first = next(row for row in cls.catalog.records if row['ref'] == cls.refs[0])
        first['eligibility'] = {**first['eligibility'], 'prerequisites': []}
        cls.supplemental_ref = next(row['ref'] for row in cls.catalog.records
                                    if row['source']['exists'] and row['ref'] not in cls.refs)
        if len(cls.refs) != 2:
            raise unittest.SkipTest('TEST catalog lacks two source-backed candidates')

    def setUp(self) -> None:
        """Create a request, vocabulary and mounted project-owned adaptation."""
        self.enterContext(patch('studio.native_style_application.load_catalog',
                                return_value=self.catalog))
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.project = self.root / 'project'; self.project.mkdir()
        (self.project / 'compositions').mkdir()
        self.profile = self.root / 'profile.json'; self.profile.write_text('{"TEST":"profile"}')
        self.deep = self.root / 'deep.json'; self.deep.write_text('{"TEST":"deep study"}')
        self.frame = self.root / 'frame.jpg'; self.frame.write_bytes(b'TEST reviewed frame')
        self.vocabulary = prepare_vocabulary(self.draft(), self.catalog)
        self.vocabulary_file = self.root / 'SELECTED-REFERENCE-VOCABULARY.json'
        write_new(self.vocabulary_file, self.vocabulary)
        selected = [{'path': file, 'sha256': sha256}
                    for file, sha256 in self.vocabulary['inputPins'].items()]
        selected.append({'path': str(self.vocabulary_file),
                         'sha256': digest(self.vocabulary_file)})
        self.request = self.root / 'LONG-REQUEST.json'
        write_new(self.request, {'selectedReference': {'id': 'reference-1',
            'styleVocabularyAvailable': True}, 'selectedReferences': selected})
        self.implementation = self.project / 'compositions/comparison.html'
        self.implementation.write_text('<template data-width="1920" data-height="1080">TEST</template>')
        self.project.joinpath('index.html').write_text(
            '<div id="comparison-panel" data-composition-src="compositions/comparison.html"></div>')
        self.plan = {'requestPacket': {'path': str(self.request), 'sha256': digest(self.request)},
                     'scenes': [{'startFrame': 0, 'endFrame': 30, 'mediaIds': []}],
                     'styleApplication': self.application()}

    def evidence(self, identifier: str, role: str, file: Path) -> dict:
        """Describe one exact inspected test artifact."""
        return {'id': identifier, 'role': role, 'path': str(file),
                'sha256': file_hash(file), 'observation': f'TEST {role} reviewed'}

    def draft(self) -> dict:
        """Build a small two-option family with explicit limited coverage."""
        contender = lambda ref: {'catalogRef': ref, 'styleFit': 'TEST style fit',
            'bestFor': 'TEST comparisons', 'difference': f'TEST difference for {ref}',
            'configuration': 'TEST adapt timing and copy',
            'variationOptions': ['TEST reverse emphasis'],
            'availability': 'ready' if ref == self.refs[0] else 'research-only',
            'prerequisites': [] if ref == self.refs[0] else ['TEST research only'],
            'evidenceIds': ['frame'], 'confidence': 0.8}
        trait = lambda identifier: {'id': identifier, 'description': f'TEST {identifier}',
                                    'evidenceIds': ['profile', 'frame']}
        return {'referenceId': 'reference-1',
            'coverage': {'status': 'limited', 'reviewed': 'TEST profile, study and frame',
                         'limitations': ['TEST no full motion playback']},
            'evidence': [self.evidence('profile', 'style-profile', self.profile),
                         self.evidence('deep', 'deep-study', self.deep),
                         self.evidence('frame', 'frame', self.frame)],
            'stableTraits': [trait('hierarchy')], 'flexibleTraits': [trait('direction')],
            'signatureDevices': [trait('accent')],
            'families': [{'id': 'comparison', 'name': 'TEST comparison',
                'purposes': ['comparison'], 'sharedStyle': 'TEST shared hierarchy',
                'useWhen': 'TEST comparing states', 'avoidWhen': 'TEST one state only',
                'contenders': [contender(ref) for ref in self.refs]}],
            'selectionPolicy': {'coherence': 'TEST preserve hierarchy',
                'variation': 'TEST vary for information fit',
                'repetition': 'TEST repeat for callbacks',
                'uncertainty': 'TEST prefer supported conservative treatment'}}

    def application(self) -> dict:
        """Bind one contender to a real project file and visible HTML ID."""
        ref = self.refs[0]
        return {'schemaVersion': 1,
            'vocabulary': {'path': str(self.vocabulary_file),
                'sha256': digest(self.vocabulary_file), 'referenceId': 'reference-1'},
            'catalogBindings': [{'contenderRef': ref, 'file': 'compositions/comparison.html',
                'implementationSha256': digest(self.implementation),
                'sourceSha256': self.vocabulary['candidates'][ref]['source']['sha256']}],
            'choices': [{'choiceId': 'scene-0-comparison', 'sceneIndex': 0,
                'viewerNeed': 'TEST compare two states',
                'familyId': 'comparison', 'contenderRef': ref,
                'anatomy': 'TEST two-panel comparison with result accent',
                'configuration': 'TEST compact 16:9 configuration',
                'development': 'TEST reveal baseline then result',
                'catalogFiles': ['compositions/comparison.html'],
                'visibleIds': ['comparison-panel'],
                'consideredContenders': self.refs,
                'selectionReason': 'TEST best simultaneous comparison',
                'repeatMode': 'new', 'repeatReason': 'TEST first use'}],
            'limitations': ['TEST structural validation only']}

    def supplemental(self, application: dict, scene_index: int = 0) -> dict:
        """Add one exact full-catalog native adaptation and its relationship evidence."""
        record = next(row for row in self.catalog.records
                      if row['ref'] == self.supplemental_ref)
        implementation = self.project / 'compositions/supplemental.html'
        implementation.write_text('<template data-width="1920" data-height="1080">TEST</template>')
        application['supplementalBindings'] = [{'catalogRef': self.supplemental_ref,
            'file': 'compositions/supplemental.html',
            'implementationSha256': digest(implementation),
            'sourceSha256': file_hash(Path(record['source']['path']))}]
        row = {'choiceId': f'scene-{scene_index}-supplemental', 'sceneIndex': scene_index,
            'viewerNeed': 'TEST compare two states', 'catalogRef': self.supplemental_ref,
            'anatomy': 'TEST evidence card with one result accent',
            'configuration': 'TEST compact card at right',
            'development': 'TEST evidence enters then result holds',
            'catalogFiles': ['compositions/supplemental.html'],
            'visibleIds': ['supplemental-panel'], 'selectionReason': 'TEST content fit',
            'relationshipMode': 'coherent',
            'relationshipEvidence': 'TEST retains compact hierarchy and accent',
            'repeatMode': 'new', 'repeatReason': 'TEST first use'}
        application['supplementalChoices'] = [row]
        return row

    def test_accepts_current_mounted_style_choice_and_returns_external_pins(self) -> None:
        """Current vocabulary, evidence and executable adaptation share one frozen chain."""
        pins = validate_long_style_application(self.project, self.plan)
        self.assertEqual(pins[str(self.request)], digest(self.request))
        self.assertEqual(pins[str(self.vocabulary_file)], digest(self.vocabulary_file))

    def test_requires_application_only_for_a_vocabulary_enabled_request(self) -> None:
        """Legacy projects remain valid while a prepared vocabulary cannot be ignored."""
        plan = deepcopy(self.plan); del plan['styleApplication']
        with self.assertRaisesRegex(ValueError, 'requires a style application'):
            validate_long_style_application(self.project, plan)
        self.assertEqual(validate_long_style_application(self.project, {'scenes': []}), {})

    def test_rejects_stale_unmounted_and_unrelated_visual_choices(self) -> None:
        """Declared variety must still map to current executable project evidence."""
        plan = deepcopy(self.plan)
        plan['styleApplication']['choices'][0]['visibleIds'] = ['missing']
        with self.assertRaisesRegex(ValueError, 'absent from executable'):
            validate_long_style_application(self.project, plan)
        plan = deepcopy(self.plan)
        self.project.joinpath('index.html').write_text('<div id="comparison-panel"></div>')
        with self.assertRaisesRegex(ValueError, 'not mounted'):
            validate_long_style_application(self.project, plan)
        self.project.joinpath('index.html').write_text(
            '<div id="comparison-panel"></div>'
            '<div id="elsewhere" data-composition-src="compositions/comparison.html"></div>')
        with self.assertRaisesRegex(ValueError, 'scene-visible'):
            validate_long_style_application(self.project, plan)
        self.project.joinpath('index.html').write_text(
            '<div id="comparison-panel" data-composition-src="compositions/comparison.html"></div>')
        unavailable = deepcopy(plan)
        ref = self.refs[1]
        unavailable['styleApplication']['catalogBindings'][0]['contenderRef'] = ref
        unavailable['styleApplication']['catalogBindings'][0]['sourceSha256'] = (
            self.vocabulary['candidates'][ref]['source']['sha256'])
        unavailable['styleApplication']['choices'][0]['contenderRef'] = ref
        with self.assertRaisesRegex(ValueError, 'not ready'):
            validate_long_style_application(self.project, unavailable)
        self.frame.write_bytes(b'TEST changed evidence')
        with self.assertRaisesRegex(ValueError, 'changed|stale'):
            validate_long_style_application(self.project, deepcopy(self.plan))

    def test_repeat_needs_an_intentional_mode(self) -> None:
        """A duplicate treatment cannot present itself as a new decision."""
        plan = deepcopy(self.plan)
        plan['scenes'].append({'startFrame': 30, 'endFrame': 60, 'mediaIds': []})
        repeated = deepcopy(plan['styleApplication']['choices'][0])
        repeated['choiceId'] = 'scene-1-comparison'; repeated['sceneIndex'] = 1
        plan['styleApplication']['choices'].append(repeated)
        with self.assertRaisesRegex(ValueError, 'repeat mode'):
            validate_long_style_application(self.project, plan)
        repeated['repeatMode'] = 'callback'
        validate_long_style_application(self.project, plan)

    def test_full_catalog_choice_can_replace_all_vocabulary_choices(self) -> None:
        """The analyzed vocabulary guides style without becoming a partial allowlist."""
        plan = deepcopy(self.plan); application = plan['styleApplication']
        application['catalogBindings'] = []; application['choices'] = []
        self.supplemental(application)
        self.project.joinpath('index.html').write_text(
            '<div id="supplemental-panel" '
            'data-composition-src="compositions/supplemental.html"></div>')
        validate_long_style_application(self.project, plan)
        application['supplementalChoices'][0]['catalogRef'] = self.refs[0]
        with self.assertRaisesRegex(ValueError, 'not bound'):
            validate_long_style_application(self.project, plan)

    def test_catalog_id_change_does_not_hide_same_composition_formula(self) -> None:
        """A different source still repeats when anatomy and development are unchanged."""
        plan = deepcopy(self.plan); application = plan['styleApplication']
        row = self.supplemental(application, 1)
        first = application['choices'][0]
        for field in ('anatomy', 'configuration', 'development'):
            row[field] = first[field]
        plan['scenes'].append({'startFrame': 30, 'endFrame': 60, 'mediaIds': []})
        self.project.joinpath('index.html').write_text(
            '<div id="comparison-panel" data-composition-src="compositions/comparison.html"></div>'
            '<div id="supplemental-panel" data-composition-src="compositions/supplemental.html"></div>')
        with self.assertRaisesRegex(ValueError, 'repeat mode'):
            validate_long_style_application(self.project, plan)
        row['repeatMode'] = 'callback'
        validate_long_style_application(self.project, plan)


if __name__ == '__main__':
    unittest.main()

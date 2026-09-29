"""Static-scope cold derivation and canvas-specific probe comparisons; no renderer qualification."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image
from _native_long_isolation_fixture import write_static_project

from studio.native_region_contract import derive_region_map, read_region_map
from studio.native_review_regions import region_rows, region_packet, preview_windows
from studio.native_segments.compatibility import section_snapshot_compatibility
from studio.native_segments.dependency import inventory, picture_changes
from studio.native_segments.plan import long_probe_schedule
from studio.native_segments.section_closure import section_input_closure
from studio.native_segments.verify import verify_long_probes

CANVAS = {'width': 320, 'height': 180, 'totalFrames': 75, 'frameRate': '25/1'}


class LongRegionContractTests(unittest.TestCase):
    """Exercise real static DOM inputs, full pins and inherited readers in isolated directories."""

    def setUp(self) -> None:
        """Three mounted static logical units under one immutable root-clock scaffold."""
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.before = self.make_project('before', 'B')
        self.after = self.make_project('after', 'B changed')
        self.tool = self.base / 'TEST-tool'
        self.tool.write_text('TEST implementation, not executable qualification')

    def make_project(self, name: str, middle: str) -> Path:
        """Generate the bounded accepted static template subset on a full landscape clock."""
        return write_static_project(self.base / name, CANVAS, ('A', middle, 'C'))

    def publish(self, project: Path) -> None:
        """Write only freshly derived isolation evidence, never an authored scoped assertion."""
        (project / 'REVIEW-REGIONS.json').write_text(json.dumps(derive_region_map(project, CANVAS)))

    def request(self, project: Path) -> dict:
        """Bind every project and implementation byte, with no claimed StageEvidence or review."""
        pins = {str(project / name): sha for name, sha in inventory(project).items()}
        implementation = {str(self.tool): hashlib.sha256(self.tool.read_bytes()).hexdigest()}
        return {'adapter': 'native-long', 'project': str(project), 'runtime': str(self.base / 'TEST-runtime'),
                'tools': {'node': str(self.tool)}, 'sectionImplementationPins': implementation,
                'pins': {**pins, **implementation}}

    def test_preview_and_repair_read_same_cold_derived_contract(self) -> None:
        """One current schema is consumed by preview scheduling and local dependency planning."""
        self.assertEqual(region_rows(self.before, CANVAS), read_region_map(self.before, CANVAS))
        changes = picture_changes(self.before, self.after)
        self.assertFalse(changes['global'])
        self.assertEqual(changes['ranges'], [[25, 50]])
        for bounds in ([0, 25], [50, 75]):
            proof = section_snapshot_compatibility(self.request(self.before), self.request(self.after), bounds)
            self.assertEqual(proof['runtimeQualification'], 'not-established')
        with self.assertRaisesRegex(ValueError, 'dependencies changed'):
            section_snapshot_compatibility(self.request(self.before), self.request(self.after), [25, 50])

    def test_tampered_or_stale_isolation_map_cannot_claim_locality(self) -> None:
        """A hand-edited scoped hash or interval must match the executable cold derivation."""
        file = self.after / 'REVIEW-REGIONS.json'
        value = json.loads(file.read_text())
        value['units'][0]['isolation']['globalSha256'] = 'a' * 64
        file.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'differs from current'):
            read_region_map(self.after, CANVAS)
        self.assertTrue(picture_changes(self.before, self.after)['global'])

    def test_authored_cross_section_script_and_relational_css_are_global(self) -> None:
        """Even an unchanged script can read edited B and change A; no absence-of-diff shortcut."""
        additions = ('<script>document.querySelector("p").textContent="global"</script>',
                     '<style>body:has(.changed){color:red}</style>', '<style>p{visibility:visible}</style>')
        for markup in additions:
            with self.subTest(markup=markup):
                original = (self.after / 'index.html').read_text()
                (self.after / 'index.html').write_text(original.replace('<body>', '<body>' + markup))
                self.publish(self.after)
                self.assertTrue(picture_changes(self.before, self.after)['global'])
                with self.assertRaisesRegex(ValueError, 'static isolation'):
                    section_input_closure(self.after, [0, 25])
                (self.after / 'index.html').write_text(original)
                self.publish(self.after)

    def test_dynamic_sibling_contaminates_every_claim_not_only_its_own_unit(self) -> None:
        """A foreign script/active-media composition cannot silently coexist with scoped A."""
        file = self.after / 'compositions/unit-2.html'
        file.write_text(file.read_text().replace('</div>', '<script>window.changed=true</script></div>'))
        self.publish(self.after)
        self.assertTrue(all(row['isolation']['status'] == 'global' for row in read_region_map(self.after, CANVAS)))
        with self.assertRaisesRegex(ValueError, 'static isolation'):
            section_input_closure(self.after, [0, 25])

    def test_sibling_styles_cannot_change_unowned_section_pixels(self) -> None:
        """Ordinary global selectors in B cannot establish any A/C reuse proof."""
        file = self.after / 'compositions/unit-1.html'
        original = file.read_text()
        for selector in ('body', '.title', '[data-composition-id="unit-0"] .title',
                         '[data-composition-id="unit-1"] .title, .title',
                         '[data-composition-id="unit-1"] + .title'):
            with self.subTest(selector=selector):
                file.write_text(original + f'<style>{selector}{{color:red}}</style>')
                self.publish(self.after)
                self.assertTrue(picture_changes(self.before, self.after)['global'])
                with self.assertRaisesRegex(ValueError, 'static isolation'):
                    section_input_closure(self.after, [0, 25])

    def test_exact_host_styles_can_change_only_their_section(self) -> None:
        """A literal owning namespace plus descendants cannot select a sibling host."""
        for project, color in ((self.before, 'blue'), (self.after, 'red')):
            file = project / 'compositions/unit-1.html'
            file.write_text(file.read_text() + '<style>[data-composition-id="unit-1"] p'
                            + f'{{color:{color}}}</style>')
            self.publish(project)
        self.assertEqual(picture_changes(self.before, self.after)['ranges'], [[25, 50]])
        section_snapshot_compatibility(self.request(self.before), self.request(self.after), [0, 25])

    def test_region_integer_fields_cannot_be_impersonated_by_booleans(self) -> None:
        """Python numeric equality must not validate differently typed derived evidence."""
        file = self.after / 'REVIEW-REGIONS.json'
        value = json.loads(file.read_text())
        value['units'][0]['startFrame'] = False
        file.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'differs from current'):
            read_region_map(self.after, CANVAS)

    def test_timing_tool_and_frozen_snapshot_drift_refuse(self) -> None:
        """Clock, tool and original source equality are independent of section text equality."""
        original, current = self.request(self.before), self.request(self.after)
        altered = copy.deepcopy(current)
        altered['tools']['node'] = '/TEST/foreign-tool'
        with self.assertRaisesRegex(ValueError, 'runtime or tools'):
            section_snapshot_compatibility(original, altered, [0, 25])
        (self.before / 'compositions/unit-0.html').write_text('TEST mutated original')
        with self.assertRaisesRegex(ValueError, 'changed input'):
            section_snapshot_compatibility(original, current, [0, 25])

    def test_derived_source_subject_can_change_but_source_decisions_cannot(self) -> None:
        """Actual source admission stays separate; only its known derived executable subject hash is omitted."""
        for project, sha in ((self.before, 'a' * 64), (self.after, 'b' * 64)):
            (project / 'VISUAL-SOURCES.json').write_text(json.dumps({'subjectSha256': sha, 'decisions': ['TEST same']}))
        section_snapshot_compatibility(self.request(self.before), self.request(self.after), [0, 25])
        file = self.after / 'VISUAL-SOURCES.json'
        file.write_text(json.dumps({'subjectSha256': 'b' * 64, 'decisions': ['TEST changed source']}))
        with self.assertRaisesRegex(ValueError, 'dependencies changed'):
            section_snapshot_compatibility(self.request(self.before), self.request(self.after), [0, 25])

    def test_final_application_adds_only_frozen_sibling_execution(self) -> None:
        """Pending sibling execution may arrive without altering A's full planning authority."""
        decisions = [{'startFrame': index * 25, 'endFrameExclusive': (index + 1) * 25,
                      'visibleIds': [f'unit-{index}']} for index in range(3)]
        common = {'canvas': CANVAS, 'visualPlan': {'TEST': 'same immutable full allocation'},
                  'scenes': [{'visualIds': [f'unit-{index}']} for index in range(3)]}
        application = {'schemaVersion': 1, 'route': 'native-long', 'visualPlanSha256': 'a' * 64}
        for project, rows in ((self.before, decisions[:1]), (self.after, decisions)):
            (project / 'LONG-PROJECT.json').write_text(json.dumps({**common,
                'visualPlanApplication': {**application, 'decisions': rows}}))
        section_snapshot_compatibility(self.request(self.before), self.request(self.after), [0, 25])
        decisions[0]['visibleIds'] = ['changed-A']
        (self.after / 'LONG-PROJECT.json').write_text(json.dumps({**common,
            'visualPlanApplication': {**application, 'decisions': decisions}}))
        with self.assertRaisesRegex(ValueError, 'dependencies changed'):
            section_snapshot_compatibility(self.request(self.before), self.request(self.after), [0, 25])

    def test_admitted_landscape_probe_geometry_and_corruption(self) -> None:
        """The real image comparator receives 320x180, not the former portrait constant."""
        file = self.base / 'probe.png'
        Image.new('RGB', (320, 180), (0, 0, 0)).save(file)
        probe = {'frame': 1, 'path': str(file), 'sha256': hashlib.sha256(file.read_bytes()).hexdigest()}

        def compare(_delivered: Path, selection: object, callback: object, _directory: Path) -> tuple:
            """Supply synthetic decoded RGB to test the actual admitted shape and metrics path."""
            self.assertEqual(selection.shape, (180, 320, 3))
            return [callback(1, np.zeros(selection.shape, dtype=np.uint8))], {'TEST': 'synthetic decode'}

        with patch('studio.native_segments.verify.compare_selected_frames', side_effect=compare):
            result = verify_long_probes([probe], self.base / 'TEST.mp4', CANVAS, self.base / 'comparison')
            self.assertTrue(result['passed'])
            self.assertEqual(result['runtimeQualification'], 'not-established')
            file.write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, 'probe bytes changed'):
                verify_long_probes([probe], self.base / 'TEST.mp4', CANVAS, self.base / 'corrupt-comparison')

    def test_probe_schedule_preserves_absolute_edges_and_rejects_bad_frames(self) -> None:
        """Geometry-aware scheduling remains bounded and never supplies a runtime qualification."""
        windows = [{'startFrame': 0, 'endFrame': 25}, {'startFrame': 50, 'endFrame': 75}]
        schedule = long_probe_schedule(CANVAS, windows, [10, 35, 60])
        self.assertEqual(schedule['frames'], [0, 10, 24, 50, 60, 74])
        with self.assertRaisesRegex(ValueError, 'probe state'):
            long_probe_schedule(CANVAS, windows, [75])

    def test_scoped_preview_padding_cannot_render_unfinished_neighbor(self) -> None:
        """A full-canvas snapshot's A preview cannot cross into C because of context padding."""
        request = self.request(self.before)
        request['sectionScope'] = {'frameRange': [0, 25]}
        windows = preview_windows(region_packet(request))
        self.assertTrue(windows)
        self.assertTrue(all(0 <= row['startFrame'] < row['endFrame'] <= 25 for row in windows))


if __name__ == '__main__':
    unittest.main()

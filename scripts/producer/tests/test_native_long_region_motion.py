"""Closed GSAP compiler and immutable media confinement; no renderer qualification."""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from _native_long_isolation_fixture import write_static_project
from studio.native_region_contract import derive_region_map, read_region_map
from studio.native_region_motion import VERSION, compile_motion, motion_markup
from studio.native_region_runtime import GSAP_ASSET, implementation_pins
from studio.native_segments.compatibility import section_snapshot_compatibility
from studio.native_segments.dependency import inventory, picture_changes
from studio.native_segments.section_closure import section_input_closure
from studio.native_segments.probe import dependency_frames
from graphics.graphics_render import GSAP_CORE

CANVAS = {'width': 320, 'height': 180, 'totalFrames': 75, 'frameRate': '25/1'}


def declaration(key: str, total: int, tweens: list | None = None) -> dict:
    """Return bounded test motion; this is neither creative nor runtime approval."""
    return {'schemaVersion': 1, 'rule': VERSION, 'compositionId': key, 'frameRate': '25/1',
            'totalFrames': total, 'tweens': tweens or []}


def tween(x: int = 20) -> dict:
    """One numerical host-local transform with no callbacks or global selectors."""
    return {'target': 'title', 'startFrame': 0, 'endFrame': 20, 'from': {'x': 0},
            'to': {'x': x}, 'ease': 'power2.out'}


class LongMotionContractTests(unittest.TestCase):
    """Real staged library bytes and cold compiler comparisons over immutable snapshots."""

    def setUp(self) -> None:
        """Create two full clock projects with immutable root sources and three local timelines."""
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.before = self.project('before', 20)
        self.after = self.project('after', 30)

    def project(self, name: str, x: int) -> Path:
        """Stage known library and structurally literal test media, without claiming valid media bytes."""
        project = write_static_project(self.base / name, CANVAS, ('A', 'B', 'C'))
        runtime = project / GSAP_ASSET
        runtime.parent.mkdir(parents=True)
        runtime.write_text(Path(GSAP_CORE).read_text().replace('</script', '<\\/script'))
        (project / 'assets/source.mp4').write_bytes(b'TEST source placeholder, not admitted media')
        (project / 'assets/program.wav').write_bytes(b'TEST audio placeholder, not admitted media')
        file = project / 'index.html'
        text = file.read_text().replace('<body>', '<body><div data-composition-id="main" '
            'data-width="320" data-height="180" data-duration="3">')
        media = ('<video id="source" src="assets/source.mp4" muted="" data-start="0" data-duration="3"></video>'
                 '<audio id="audio" src="assets/program.wav" data-start="0" data-duration="3"></audio>')
        file.write_text(text.replace('</body>', media + '</div>' + f'<script src="{GSAP_ASSET}"></script>'
                                   + motion_markup(declaration('main', 75)) + '</body>'))
        for index in range(3):
            file = project / f'compositions/unit-{index}.html'
            text = file.read_text().replace('<p>', '<p data-motion-id="title">')
            motion = declaration(f'unit-{index}', 25, [tween(x if index == 1 else 20)])
            file.write_text(text.replace('</template>', motion_markup(motion) + '</template>'))
        self.publish(project)
        return project

    def publish(self, project: Path) -> None:
        """Write only currently cold-derived region evidence."""
        (project / 'REVIEW-REGIONS.json').write_text(json.dumps(derive_region_map(project, CANVAS)))

    def request(self, project: Path) -> dict:
        """Bind source and actual compiler/library bytes; no StageEvidence is fabricated."""
        implementation = implementation_pins(project)
        return {'adapter': 'native-long', 'project': str(project), 'runtime': '/TEST/shared-runtime', 'tools': {},
                'sectionImplementationPins': implementation,
                'pins': {**implementation, **{str(project / name): sha for name, sha in inventory(project).items()}}}

    def test_source_and_generated_motion_allow_only_owned_changes(self) -> None:
        """Root sources remain global; B motion can change without changing A/C input closures."""
        self.assertTrue(all(row['isolation']['status'] == 'scoped' for row in read_region_map(self.after, CANVAS)))
        self.assertEqual(picture_changes(self.before, self.after)['ranges'], [[25, 50]])
        for bounds in ([0, 25], [50, 75]):
            proof = section_snapshot_compatibility(self.request(self.before), self.request(self.after), bounds)
            self.assertEqual(proof['runtimeQualification'], 'not-established')
        (self.after / 'assets/source.mp4').write_bytes(b'TEST substituted source')
        with self.assertRaisesRegex(ValueError, 'dependencies changed'):
            section_snapshot_compatibility(self.request(self.before), self.request(self.after), [0, 25])

    def test_compiled_source_and_library_tampering_refuse(self) -> None:
        """A plausible declaration cannot certify arbitrary executable code or substituted GSAP."""
        file = self.after / 'compositions/unit-1.html'
        file.write_text(file.read_text().replace('const timeline =', 'window.bad=true;const timeline ='))
        self.publish(self.after)
        self.assertTrue(picture_changes(self.before, self.after)['global'])
        (self.before / GSAP_ASSET).write_text('TEST substituted runtime')
        self.publish(self.before)
        with self.assertRaisesRegex(ValueError, 'static isolation'):
            section_input_closure(self.before, [0, 25])

    def test_cross_host_target_callbacks_and_root_animation_refuse(self) -> None:
        """No authored callbacks, expressive selectors or parent timeline manipulation pass."""
        for change in ({'target': 'body p'}, {'onComplete': 'evil'}, {'ease': 'function(){}'}, {'to': {'visibility': 1}}):
            motion = declaration('unit-1', 25, [{**tween(), **change}])
            with self.subTest(change=change), self.assertRaises(ValueError):
                compile_motion(motion)
        file = self.after / 'index.html'
        text = file.read_text().replace('data-composition-src="compositions/unit-0.html"',
                                       'data-motion-id="title" data-composition-src="compositions/unit-0.html"')
        text = text.replace(motion_markup(declaration('main', 75)), motion_markup(declaration('main', 75, [tween()])))
        file.write_text(text)
        self.publish(self.after)
        self.assertTrue(picture_changes(self.before, self.after)['global'])

    def test_compiler_and_vendored_runtime_must_be_explicitly_pinned(self) -> None:
        """Media reuse cannot rely on the project copy alone when compiler source is unbound."""
        original, current = self.request(self.before), self.request(self.after)
        missing = str(Path(GSAP_CORE).resolve())
        for request in (original, current):
            request['sectionImplementationPins'].pop(missing)
        with self.assertRaisesRegex(ValueError, 'not pinned'):
            section_snapshot_compatibility(original, current, [0, 25])

    def test_duplicate_script_attribute_and_unknown_dom_control_refuse(self) -> None:
        """Recognized script types cannot hide duplicate attributes or unanalysed browser controls."""
        file = self.after / 'compositions/unit-1.html'
        original = file.read_text()
        for text in (original.replace('type="application/json"', 'type="application/json" type="text/javascript"'),
                     original.replace('<p ', '<p onclick="window.bad=true" '),
                     original.replace('data-motion-id="title"', 'data-motion-id="other"')):
            file.write_text(text)
            self.publish(self.after)
            self.assertTrue(picture_changes(self.before, self.after)['global'])

    def test_root_cannot_impersonate_child_motion_host(self) -> None:
        """A child selector must not resolve to the global root because of duplicated identity."""
        file = self.after / 'index.html'
        file.write_text(file.read_text().replace('data-composition-id="main"', 'data-composition-id="unit-0"'))
        with self.assertRaisesRegex(ValueError, 'must not collide'):
            derive_region_map(self.after, CANVAS)

    def test_dependency_schedule_includes_owned_motion_endpoint_neighborhoods(self) -> None:
        """B's end tween state at absolute45 is checked even between regular sparse samples."""
        frames = dependency_frames({'startFrame': 25, 'endFrame': 50}, self.after)
        self.assertTrue({25, 26, 44, 45, 46, 49} <= set(frames))
        self.assertTrue(all(25 <= frame < 50 for frame in frames))

    def test_generated_program_uses_real_gsap_absolute_forward_reverse_seeks(self) -> None:
        """Exercise the vendored engine's numerical timeline, without claiming DOM or encoded playback."""
        motion = declaration('unit-1', 25, [{**tween(100), 'ease': 'none'}])
        program = r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const input=JSON.parse(fs.readFileSync(0,'utf8')),runtime={exports:{},module:{},setTimeout,clearTimeout};
vm.runInNewContext(fs.readFileSync(input.library,'utf8'),runtime);
const {gsap}=runtime.exports;
const target={x:0},host={querySelector(selector){assert.equal(selector,'[data-motion-id="title"]');return target;}};
const context={gsap,window:{},document:{querySelector(selector){
  assert.equal(selector,'[data-composition-id="unit-1"]');return host;}}};
try {
  vm.runInNewContext(input.code,context);
  const timeline=context.window.__timelines['unit-1'];
  for(const [time,expected] of [[0,0],[.4,50],[.8,100],[.4,50],[0,0]]){
    timeline.seek(time,false);assert.ok(Math.abs(target.x-expected)<.0001);
  }
  timeline.kill();
} finally { gsap.ticker.sleep(); }
'''
        result = subprocess.run([shutil.which('node'), '-e', program], input=json.dumps(
            {'library': str(Path(GSAP_CORE).resolve()), 'code': compile_motion(motion)}),
            text=True, capture_output=True, timeout=15, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()

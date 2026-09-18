"""External local code must run in the same instance scope as inline code."""
from __future__ import annotations

from pathlib import Path
import tempfile
import json
import shutil
import subprocess
import unittest
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from studio import StudioProjectError
from studio.comp_dependencies import MOTION_ROOT, bind_mounted_duration, inline_local_body_scripts
from studio.comp_transform import InstancePlan, build_instance, parse_source_comp
from studio.comp_dependencies import STYLE_SCOPE, bind_instance_styles
from studio.sync_files import _rebuild_instance


class StudioCompDependencyTests(unittest.TestCase):
    """Use actual native pipeline code plus isolated negative dependency cases."""

    def test_real_pipeline_is_inlined_and_rekeyed_for_each_instance(self) -> None:
        html = (MOTION_ROOT / 'compositions/module-pipeline.html').read_text()
        source = parse_source_comp('module-pipeline', html)
        self.assertTrue(source.uses_motion_tokens)
        for instance in ('gfx-04-module-pipeline', 'gfx-51-module-pipeline'):
            result = build_instance(source, InstancePlan(instance,
                {'headlineLines': 'The actual plan', 'nodes': '01~PROMPT|02~OUTPUT'}, 5))
            self.assertNotIn('src="/module-pipeline.js"', result.html)
            self.assertIn('nplRenderer.boot();', result.html)
            self.assertNotIn('__timelines["module-pipeline"]', result.html)
            self.assertEqual(result.html.count('__timelines["' + instance + '"]'), 2)
            self.assertIn('src="../assets/vendor/motion-tokens.js"', result.html)

    def test_plain_inline_scripts_remain_byte_identical(self) -> None:
        original = '<script>const value = "unchanged";</script>'
        self.assertEqual(inline_local_body_scripts(original), original)

    def test_scoped_catalog_keeps_legacy_default_and_records_exact_rebuild(self) -> None:
        """Only a declared new transform can change a saved instance's page styles."""
        original = (MOTION_ROOT / 'compositions/section-takeover.html').read_text()
        legacy = parse_source_comp('section-takeover', original)
        scoped = parse_source_comp('section-takeover', original, scope_styles=True)
        self.assertIn('document.documentElement.style.setProperty', legacy.body)
        self.assertNotIn('document.documentElement.style.setProperty', scoped.body)
        self.assertIn('document.getElementById("st-root").style.setProperty', scoped.body)
        entry = {'kind':'section-takeover','instanceId':'gfx-09-section-takeover',
            'outStart':0,'outEnd':6,'styleScope':STYLE_SCOPE,'durationBinding':'mounted-host-v1'}
        expected = build_instance(scoped, InstancePlan(entry['instanceId'],{},6)).html
        self.assertEqual(_rebuild_instance(entry, {'spec':{}}), expected)
        entry['styleScope'] = 'unknown'
        with self.assertRaisesRegex(StudioProjectError, 'style scope'):
            _rebuild_instance(entry, {'spec':{}})

    def test_style_parser_cache_precedes_instance_rekey_and_uses_empty_stdin(self) -> None:
        """Repeating one catalog body does not add a process per timeline card."""
        bind_instance_styles.cache_clear()
        body = '<script>document.documentElement.style.setProperty("--accent", "blue");</script>'
        from studio import comp_dependencies
        with patch.object(comp_dependencies, 'run_text', wraps=comp_dependencies.run_text) as run:
            first = bind_instance_styles(body, 'test-root')
            self.assertEqual(bind_instance_styles(body, 'test-root'), first)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0].stdin_text, '')

    def test_duration_binding_covers_inline_and_external_catalog_code(self) -> None:
        for kind in ('statement-card', 'avatar-bio-card', 'module-pipeline'):
            source = parse_source_comp(kind, (MOTION_ROOT / 'compositions' / (kind + '.html')).read_text())
            built = build_instance(source, InstancePlan('gfx-20-' + kind, {}, 7))
            self.assertIn('root.closest("[data-composition-id]").dataset.duration', built.html)
            self.assertNotIn('root.dataset.duration', built.html)
            self.assertIn('data-duration="7"', built.html)
        literal = '<div title="root.dataset.duration"></div>'
        self.assertEqual(bind_mounted_duration(literal), literal)

    @unittest.skipUnless(shutil.which('node'), 'installed node is required')
    def test_duration_read_survives_mount_and_tracks_native_host_edits(self) -> None:
        script = bind_mounted_duration('<script>parseFloat(root.dataset.duration) || 4</script>')
        expression = script.removeprefix('<script>').removesuffix('</script>')
        # SDK mount removes inner timing; it must not fall back to 4 or to a
        # copied initial value. The standalone root still owns its duration.
        javascript = '''
const expression = JSON.parse(process.argv[1]);
const host = {dataset: {duration: '7'}};
const root = {dataset: {}, closest: selector => {
  if (selector !== '[data-composition-id]') throw Error('wrong root contract');
  return host;
}};
const mounted = eval(expression);
host.dataset.duration = '8.5';
const edited = eval(expression);
root.dataset.duration = '2.75'; root.closest = () => root;
process.stdout.write(JSON.stringify([mounted, edited, eval(expression)]));
'''
        result = subprocess.run([shutil.which('node'), '-e', javascript, json.dumps(expression)],
            check=True, capture_output=True, text=True, timeout=10)
        self.assertEqual(json.loads(result.stdout), [7, 8.5, 2.75])

    def test_remote_traversal_missing_and_module_scripts_fail_closed(self) -> None:
        snippets = ['<script src="https://example.invalid/x.js"></script>',
            '<script src="/../secret.js"></script>', '<script src="/missing-file.js"></script>',
            '<script src="/module-pipeline.js" async></script>',
            '<script src="/module-pipeline.js" src="/other.js"></script>',
            '<script type="module" src="/module-pipeline.js"></script>']
        for snippet in snippets:
            with self.subTest(snippet=snippet), self.assertRaises(StudioProjectError):
                inline_local_body_scripts(snippet)

    def test_source_changes_change_instances_and_aliases_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            script = root / 'local.js'
            script.write_text('const value = 1;')
            with patch('studio.comp_dependencies.MOTION_ROOT', root):
                first = inline_local_body_scripts('<script src="/local.js"></script>')
                script.write_text('const value = 2;')
                second = inline_local_body_scripts('<script src="/local.js"></script>')
                self.assertNotEqual(first, second)
                script.rename(root / 'held.js')
                script.symlink_to(root / 'held.js')
                self.assertRaises(StudioProjectError, inline_local_body_scripts, '<script src="/local.js"></script>')


if __name__ == '__main__':
    unittest.main(verbosity=2)

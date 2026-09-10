"""Native Inspector copy is explicit data; neighboring code never rides along."""
from __future__ import annotations

import html
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]
                       / "src/app/api/producer/studio/import"))
from native_copy import prove_composition_copy
from studio.sync_files import _rebuild_instance
from studio.comp_transform import native_text_assignment
from studio import StudioProjectError


def original() -> str:
    """Use the real registered template and current Studio instance generator."""
    entry = {"kind": "text-element", "instanceId": "gfx-01-text-element",
             "outStart": 1, "outEnd": 3.5}
    return _rebuild_instance(entry, {"spec": {
        "text": "Review the system", "fontSize": 64}})


def serialized(source: str) -> str:
    """Exactly the declaration quote/entity rewrite observed in native Studio."""
    return re.sub(r"data-composition-variables='([^']*)'", lambda match:
                  'data-composition-variables="' + html.escape(match[1], quote=True) + '"', source)


def native_text(source: str, text: str) -> str:
    """Change only the named leaf, matching the native Inspector's saved output."""
    changed, count = re.subn(r'(<div id="te-text"[^>]*>).*?(</div>)',
                            lambda match: match[1] + text + match[2], source, count=1, flags=re.DOTALL)
    if count != 1:
        raise AssertionError("Expected the current plain-text template anatomy")
    return serialized(changed)


class StudioNativeCopyTests(unittest.TestCase):
    def test_native_dom_copy_maps_only_to_declared_text(self) -> None:
        source = original()
        for text in ("Review timing clearly", "Use &lt;safe&gt; &amp; clear copy", "Second edit"):
            with self.subTest(text=text):
                self.assertEqual(prove_composition_copy(
                    source, native_text(source, text), {}, "text-element"),
                    {"text": html.unescape(text)})

    def test_native_undo_and_equivalent_serialization_have_no_change(self) -> None:
        source = original()
        self.assertEqual(prove_composition_copy(source, serialized(source), {}, "text-element"), {})
        self.assertEqual(prove_composition_copy(source, source, {}, "text-element"), {})

    def test_restoring_runtime_original_copy_is_not_a_new_semantic_value(self) -> None:
        source = original()
        native = prove_composition_copy(source, native_text(source, "Review the system"), {}, "text-element")
        self.assertEqual({"text": "Review the system", **native}, {"text": "Review the system"})

    def test_code_geometry_structure_and_other_defaults_never_hitchhike(self) -> None:
        source = original()
        copied = native_text(source, "Checked")
        mutations = [
            copied.replace('id="te-text"', 'id="te-text" style="color: red"'),
            copied.replace('data-duration="60"', 'data-duration="90"'),
            copied.replace('opacity: 0, y: 24', 'opacity: 0, y: 48'),
            copied.replace('text: "Your text here"', 'text: "Your  text here"'),
            copied.replace('id="te-text"', 'id="te-text" id="other"'),
            copied.replace('</template>', '<div id="te-text">Extra</div></template>'),
            copied.replace('&quot;default&quot;: 64,', '&quot;default&quot;: 128,'),
        ]
        for changed in mutations:
            with self.subTest(changed=changed != copied), self.assertRaises(ValueError):
                self.assertNotEqual(changed, copied)
                prove_composition_copy(source, changed, {}, "text-element")

    def test_markup_comments_self_closing_and_duplicate_leaves_are_blocked(self) -> None:
        source = original()
        for text in ('<b>Changed</b>', '<script>alert(1)</script>', '<!--not copy-->Text', '<br>'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                prove_composition_copy(source, native_text(source, text), {}, "text-element")
        self_closed = re.sub(r'(<div id="te-text"[^>]*>).*?</div>',
                             lambda match: match[1][:-1] + '/>', source)
        self.assertNotEqual(self_closed, source)
        with self.assertRaises(ValueError):
            prove_composition_copy(source, self_closed, {}, "text-element")

    def test_host_and_native_disagreement_requires_resolution(self) -> None:
        source = original()
        with self.assertRaisesRegex(ValueError, "conflict"):
            prove_composition_copy(source, native_text(source, "Native"), {"text": "Host"}, "text-element")
        self.assertEqual(prove_composition_copy(source, native_text(source, "Same"),
                         {"text": "Same"}, "text-element"), {"text": "Same"})

    def test_unregistered_source_assignment_and_other_kinds_have_no_reverse_mapping(self) -> None:
        source = original()
        with self.assertRaises(ValueError):
            prove_composition_copy(source, native_text(source, "Changed"), {}, "other-kind")
        changed_source = source.replace('String(vars.text)', 'String(vars.other)')
        with self.assertRaisesRegex(ValueError, "unproved"):
                prove_composition_copy(changed_source, native_text(changed_source, "Changed"), {}, "text-element")

    def test_cold_preview_binding_preserves_native_copy_and_unedited_variables(self) -> None:
        seed = 'Review <safe> & "clear" copy \u2028 </script>'
        assignment = native_text_assignment(seed)
        cases = [(seed, "Host edit", "Host edit"), ("Native edit", seed, "Native edit"),
                 ("", seed, ""), (seed, seed, seed)]
        script = "const cases = " + json.dumps(cases) + "; const output = cases.map(([text, value]) => {"
        script += "const node = {textContent: text}; const document = {getElementById: () => node};"
        script += "const vars = {text: value}; " + assignment + " return el.textContent;});"
        script += "process.stdout.write(JSON.stringify(output));"
        result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True, timeout=10)
        self.assertEqual(json.loads(result.stdout), [case[2] for case in cases])
        self.assertNotIn("</script>", assignment)

    def test_generated_leaf_contains_the_literal_seed_and_blank_native_edit(self) -> None:
        source = original()
        self.assertIn('>Review the system</div>', source)
        self.assertEqual(prove_composition_copy(source, native_text(source, ""), {}, "text-element"), {"text": ""})

    def test_carriage_returns_are_entity_bound_and_nul_is_explicitly_unsupported(self) -> None:
        entry = {"kind": "text-element", "instanceId": "gfx-01-text-element",
                 "outStart": 1, "outEnd": 3.5}
        seed = "First\r\nSecond\rThird"
        source = _rebuild_instance(entry, {"spec": {"text": seed}})
        self.assertIn("First&#13;\nSecond&#13;Third</div>", source)
        self.assertEqual(prove_composition_copy(source, source, {}, "text-element"), {})
        with self.assertRaisesRegex(StudioProjectError, "NUL"):
            _rebuild_instance(entry, {"spec": {"text": "No\x00guess"}})
        with self.assertRaisesRegex(ValueError, "NUL"):
            prove_composition_copy(source, native_text(source, "No\x00guess"), {}, "text-element")

    def test_declaration_panel_default_only_matches_exact_supported_pair(self) -> None:
        source = original()
        raw = re.search(r"data-composition-variables='([^']*)'", source)[1]
        rows = json.loads(raw)
        rows[0]["default"] = "Changed"
        changed = source.replace(raw, json.dumps(rows))
        self.assertEqual(prove_composition_copy(source, changed, {"text": "Changed"}, "text-element"), {})
        with self.assertRaises(ValueError):
            prove_composition_copy(source, changed, {}, "text-element")


if __name__ == "__main__":
    unittest.main()

"""Advisory declaration comparisons reuse the strict parser; no SDK or I/O."""
from __future__ import annotations

import html
import json
import unittest

from studio.declaration_sync import declaration_projection, require_paired_declarations
from studio.sync_files import _instance_change_note


def _document(value: object, double: bool = False) -> str:
    """Model exact old/new attribute spellings with unchanged script/text bytes."""
    rows = [{"id": "text", "type": "string", "default": value}]
    raw = json.dumps(rows)
    attr = f"'{raw}'" if not double else '"' + html.escape(raw, quote=True) + '"'
    return ('<!doctype html>\n<!-- TEST data-composition-variables=\'[]\' -->\n'
            f'<html lang="en" data-composition-variables={attr}><body>'
            '<script>const literal = "data-composition-variables";</script>'
            '<div data-hf-id="TEST-one">Original copy</div></body></html>')


class StudioDeclarationNoteTests(unittest.TestCase):
    """Only the declaration changes category; this does not authorize syncing."""

    def test_v1_and_v2_defaults_have_the_same_advisory_and_gate(self) -> None:
        """Both saved spellings report their actual default edit and reject it."""
        for double in (False, True):
            before, after = _document("old", double), _document("new", double)
            self.assertIn("declared-variable defaults", _instance_change_note("TEST.html", after, before))
            self.assertRaisesRegex(ValueError, "unmatched declared default",
                                   require_paired_declarations, before, after, {"text": "old"})
            require_paired_declarations(before, after, {"text": "new"})

    def test_quote_entity_rewrite_is_formatting_only(self) -> None:
        """Equivalent decoded rows compare without changing the source document."""
        before, after = _document("A & B"), _document("A & B", True)
        self.assertNotEqual(before, after)
        self.assertEqual(declaration_projection(before), declaration_projection(after))
        self.assertIn("formatting-only", _instance_change_note("TEST.html", after, before))

    def test_script_text_ids_other_attributes_and_comments_stay_structural(self) -> None:
        """No generic HTML normalizer can erase changes outside declarations."""
        original = _document("old", True)
        replacements = (("Original copy", "Different copy"), ("TEST-one", "TEST-two"),
                        ('lang="en"', 'lang="fr"'), ("const literal", "let literal"),
                        ("<!-- TEST", "<!-- Changed TEST"))
        for old, new in replacements:
            changed = original.replace(old, new, 1)
            self.assertNotEqual(changed, original)
            self.assertIn("structurally edited", _instance_change_note("TEST.html", changed, original))

    def test_duplicate_retargeted_missing_and_nonfinite_declarations_refuse(self) -> None:
        """Advisory comparison cannot bypass the paired gate's parser failures."""
        original = _document("old", True)
        cases = (original.replace('<html lang="en"', '<html data-composition-variables="[]" lang="en"'),
                 original.replace("<html ", "<div "), original.replace("data-composition-variables=", "data-other="),
                 _document(float("nan"), True))
        for changed in cases:
            self.assertRaises(ValueError, declaration_projection, changed)

    def test_boolean_is_not_number_and_no_rows_are_shared(self) -> None:
        """Canonical numeric formatting does not erase JSON type distinctions."""
        self.assertIn("declared-variable defaults", _instance_change_note("TEST.html", _document(True), _document(1)))
        original = _document("old", True)
        first = declaration_projection(original)
        first[1][0]["default"] = "changed"
        self.assertEqual(declaration_projection(original)[1][0]["default"], "old")

    def test_root_position_handles_crlf_and_other_line_characters(self) -> None:
        """HTMLParser line offsets count LF, not every Unicode line separator."""
        before = _document("old").replace("\n", "\r\n\u2028\v")
        after = before.replace('"default": "old"', '"default": "new"')
        self.assertIn("declared-variable defaults", _instance_change_note("TEST.html", after, before))


if __name__ == "__main__":
    unittest.main()

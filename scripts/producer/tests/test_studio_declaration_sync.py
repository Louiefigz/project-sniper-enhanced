"""Real Studio sync files with an inert TEST base; no renderer or server starts."""
from __future__ import annotations

import copy
import html
import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from studio.comp_transform import attr_json
from studio.project_writer import ReviewBase
from studio.studio_project import GenerateRequest, generate_project
from studio.sync_diff import compute_report, load_state
from studio.view_manifest import FINGERPRINT_NAME, MANIFEST_NAME
from test_studio_sync import _patch_slot_attr, _run_main, _sync_plan


class StudioDeclarationSyncTests(unittest.TestCase):
    """A saved panel edit cannot be reported as synced while the plan loses it."""

    def setUp(self) -> None:
        """Generate actual project files while explicitly substituting only probing."""
        temporary = tempfile.TemporaryDirectory(prefix="sniper-declaration-sync-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.plan = self.root / "edit_plan.json"
        self.plan.write_text(json.dumps(_sync_plan()), encoding="utf8")
        base = self.root / "base_final.mp4"
        base.write_bytes(b"TEST inert base; never decoded")
        (self.root / "asset_manifest.json").write_text(json.dumps({"sources": [
            {"id": "raw-1", "path": str(base), "duration": 20.0}]}), encoding="utf8")
        self.studio = self.root / "studio"
        probe = ReviewBase(1920, 1080, 12.0, 30.0, "", False)
        baseline_probe = mock.patch("studio.index_semantics.probe_media", return_value=SimpleNamespace(
            width=1920, height=1080, duration=12.0, fps=30.0, rotation=0, audio_present=False))
        baseline_probe.start()
        self.addCleanup(baseline_probe.stop)
        with mock.patch("studio.studio_project._probe_base", return_value=probe):
            generate_project(GenerateRequest(str(self.plan), str(base), str(self.studio)))
        self.instance = self.studio / "compositions/gfx-02-text-element-wide.html"
        self.original = self.instance.read_text(encoding="utf8")
        match = re.search(r'''data-composition-variables=(["'])(.*?)\1''', self.original, re.DOTALL)
        self.assertIsNotNone(match)
        self.original_attribute = match.group(0)
        self.attribute = html.unescape(match.group(2))
        self.rows = json.loads(self.attribute)

    def _edit(self, rows: list, double_quote: bool = False) -> None:
        """Change the declarations only, optionally using native entity serialization."""
        value = attr_json(rows)
        replacement = f"data-composition-variables='{value}'"
        if double_quote:
            replacement = 'data-composition-variables="' + html.escape(json.dumps(rows), quote=True) + '"'
        self.instance.write_text(self.original.replace(
            self.original_attribute, replacement, 1), encoding="utf8")

    def _font(self, value: object) -> list:
        """Return independently changed declaration rows without mutating the fixture."""
        rows = copy.deepcopy(self.rows)
        next(row for row in rows if row["id"] == "fontSize")["default"] = value
        return rows

    def _host(self, value: object) -> None:
        """Use the existing tested host-slot mutation fixture."""
        _patch_slot_attr(str(self.studio / "index.html"), "gfx-02", "data-variable-values",
                         json.dumps({"fontSize": value, "text": "Callout copy"}))

    def _refused_unchanged(self) -> None:
        """Refusal must preserve the plan, baseline and user's exact pending edit."""
        paths = [self.plan, self.studio / MANIFEST_NAME, self.studio / FINGERPRINT_NAME,
                 self.studio / "index.html", self.instance]
        before = {path: path.read_bytes() for path in paths}
        code, output = _run_main([str(self.studio), "--apply"])
        self.assertEqual(code, 2, output)
        self.assertEqual(json.loads(output)["status"], "refused")
        self.assertEqual({path: path.read_bytes() for path in paths}, before)
        self.assertFalse((self.root / "plan-history").exists())
        self.assertTrue(compute_report(load_state(str(self.studio))).blockers)

    def test_default_only_edit_cannot_be_silently_rebaselined(self) -> None:
        """A font changed inside the composition is not yet a host-plan edit."""
        self._edit(self._font(96))
        self._refused_unchanged()

    def test_conflicting_host_and_panel_values_refuse_without_writes(self) -> None:
        """Do not discard one of two incompatible saved user choices."""
        self._host(80)
        self._edit(self._font(96))
        self._refused_unchanged()

    def test_matching_host_default_edit_reaches_existing_apply(self) -> None:
        """A paired value follows ordinary template/lint/history publication."""
        self._host(96)
        self._edit(self._font(96), double_quote=True)
        code, output = _run_main([str(self.studio), "--apply"])
        self.assertEqual(code, 0, output)
        plan = json.loads(self.plan.read_text(encoding="utf8"))
        self.assertEqual(plan["graphicsTrack"][1]["spec"]["fontSize"], 96)
        self.assertEqual(plan["planVersion"], 2)
        self.assertEqual(len(list((self.root / "plan-history").glob("*.json"))), 1)
        self.assertTrue(compute_report(load_state(str(self.studio))).clean)

    def test_quote_entity_and_integral_number_rewrite_is_not_a_new_value(self) -> None:
        """Equivalent declarations may be rebaselined without changing the plan."""
        self._edit(self._font(72.0), double_quote=True)
        before = self.plan.read_bytes()
        code, output = _run_main([str(self.studio), "--apply"])
        self.assertEqual(code, 0, output)
        self.assertEqual(self.plan.read_bytes(), before)
        self.assertFalse((self.root / "plan-history").exists())
        self.assertTrue(compute_report(load_state(str(self.studio))).clean)

    def test_unmatched_default_with_css_save_is_still_blocked(self) -> None:
        """The native save primitive's additional CSS cannot hide a changed default."""
        self._edit(self._font(96), double_quote=True)
        self.instance.write_text(self.instance.read_text(encoding="utf8").replace(
            "<body>", '<body style="--fontSize:96px;">'), encoding="utf8")
        self._refused_unchanged()

    def test_changed_declaration_type_does_not_hitchhike_with_host(self) -> None:
        """Matching numeric values do not authorize changed declared metadata."""
        self._host(96)
        rows = self._font(96)
        next(row for row in rows if row["id"] == "fontSize")["type"] = "string"
        self._edit(rows)
        self._refused_unchanged()

    def test_boolean_is_not_a_matching_numeric_host_value(self) -> None:
        """Python's True == 1 must not make two saved choices equivalent."""
        self._host(1)
        self._edit(self._font(True))
        self._refused_unchanged()

    def test_duplicate_declaration_ids_are_not_collapsed(self) -> None:
        """A map conversion cannot choose between duplicated saved declarations."""
        self._edit([*self.rows, self.rows[0]])
        self._refused_unchanged()

    def test_duplicate_json_keys_are_not_collapsed(self) -> None:
        """Keep duplicate defaults visible instead of selecting the last value."""
        changed = self.attribute.replace('"default": 72', '"default": 96, "default": 72')
        edited = self.original.replace(self.original_attribute, f"data-composition-variables='{changed}'", 1)
        self.assertNotEqual(edited, self.original)
        self.instance.write_text(edited, encoding="utf8")
        self._refused_unchanged()

    def test_duplicate_attribute_is_not_serializer_freedom(self) -> None:
        """A second declarations attribute cannot conceal the first saved edit."""
        self.instance.write_text(self.original.replace(
            '<html lang="en"', '<html data-composition-variables="[]" lang="en"'), encoding="utf8")
        self._refused_unchanged()

    def test_unavailable_original_baseline_refuses_paired_values(self) -> None:
        """Today's generated bytes are not necessarily the original review baseline."""
        self._host(96)
        self._edit(self._font(96))
        with mock.patch("studio.sync_files._rebuild_instance", return_value=self.original + "\n"):
            self._refused_unchanged()


if __name__ == "__main__":
    unittest.main()

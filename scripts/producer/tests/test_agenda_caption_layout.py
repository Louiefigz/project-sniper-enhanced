"""Native agenda intent/structure tests, not rendered layout or creative approval."""
from __future__ import annotations

from copy import deepcopy
from html.parser import HTMLParser
from pathlib import Path
import re
import unittest

from graphics.template_contract import declared_variables, planned_copy, validate_entry
from graphics.template_visual_contract import visual_entry_errors

ROOT = Path(__file__).resolve().parents[3]
HTML = (ROOT / "templates/motion/compositions/agenda-slide.html").read_text()
CSS = (ROOT / "templates/motion/agenda-caption-layout.css").read_text()


def agenda(slots: tuple = (1, 2, 3)) -> dict:
    """Explicit TEST copy, with no demo-content fallback or source claim."""
    spec = {key: row["default"] for key, row in declared_variables(HTML).items()}
    spec.update(layout="caption-safe-upper-v1", eyebrow="TEST sequence", title="A complete loop")
    for index in range(1, 6):
        spec[f"num{index}"] = str(index) if index in slots else ""
        spec[f"title{index}"] = f"TEST step {index}" if index in slots else ""
        spec[f"sub{index}"] = "Retain every requested word" if index in slots else ""
    return {"id": "TEST-agenda", "kind": "agenda-slide", "anchor": "own-screen",
            "outStart": 0, "outEnd": 5, "spec": spec}


class Roles(HTMLParser):
    """Read declared node roles, not computed DOM or animation geometry."""

    def __init__(self) -> None:
        super().__init__()
        self.roles: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple]) -> None:
        role = dict(attrs).get("data-sniper-protected-role")
        if role is not None:
            self.roles.append(role)


class AgendaCaptionLayoutTests(unittest.TestCase):
    """A variant is explicitly selected and never equivalent to a safety proof."""

    def test_one_to_three_present_steps_retain_exact_copy_and_input(self) -> None:
        for slots in ((1,), (2, 4), (1, 2, 3), (1, 3, 5)):
            value = agenda(slots)
            before = deepcopy(value)
            validate_entry(value, HTML)
            self.assertEqual(value, before)
            for index in slots:
                self.assertIn(value["spec"][f"title{index}"], planned_copy(value, HTML))
                self.assertIn(value["spec"][f"sub{index}"], planned_copy(value, HTML))

    def test_empty_or_over_capacity_variant_rejects_without_dropping_rows(self) -> None:
        for slots in ((), (1, 2, 3, 4), (1, 2, 3, 4, 5)):
            value = agenda(slots)
            before = deepcopy(value)
            with self.assertRaisesRegex(ValueError, "one to three"):
                validate_entry(value, HTML)
            self.assertEqual(value, before)

    def test_default_full_canvas_keeps_original_five_row_eligibility(self) -> None:
        value = agenda((1, 2, 3, 4, 5))
        del value["spec"]["layout"]
        validate_entry(value, HTML)
        value["spec"]["layout"] = "full-canvas"
        validate_entry(value, HTML)

    def test_only_native_own_screen_can_select_upper_split(self) -> None:
        value = agenda()
        value["anchor"] = "free-band"
        with self.assertRaisesRegex(ValueError, "native own-screen"):
            validate_entry(value, HTML)

    def test_layout_is_closed_not_copy_and_does_not_leak_into_visible_strings(self) -> None:
        value = agenda()
        row = declared_variables(HTML)["layout"]
        self.assertEqual(row["type"], "enum")
        self.assertEqual(row["default"], "full-canvas")
        self.assertNotIn("caption-safe-upper-v1", planned_copy(value, HTML))
        for invalid in ("caption-safe", "", None, True, {}):
            value["spec"]["layout"] = invalid
            with self.assertRaises(ValueError):
                validate_entry(value, HTML)

    def test_other_kinds_do_not_inherit_agenda_capacity_or_layout_policy(self) -> None:
        value = agenda((1, 2, 3, 4, 5))
        value["kind"] = "TEST-other-kind"
        self.assertEqual(visual_entry_errors(value), [])

    def test_all_potential_content_roles_are_distinct_and_declared(self) -> None:
        parser = Roles()
        parser.feed(HTML)
        expected = {"eyebrow", "title", "title-accent"}
        for index in range(1, 6):
            expected.update(f"step-{index}-{part}" for part in ("marker", "title", "subtitle"))
        self.assertEqual(len(parser.roles), len(expected))
        self.assertEqual(set(parser.roles), expected)

    def test_variant_reflows_without_font_scale_or_copy_suppression_rules(self) -> None:
        rules = CSS[CSS.index("#ag-root"):]
        for forbidden in ("font-size", "transform:", "text-overflow", "line-clamp", "display: none", "overflow: hidden"):
            self.assertNotIn(forbidden, rules)
        self.assertIn("grid-template-columns: 620px minmax(0, 1fr)", rules)
        self.assertIn("white-space: normal", rules)
        self.assertIn('/agenda-caption-layout.css', HTML)

    def test_only_explicit_upper_title_eyebrow_and_row_title_get_line_room(self) -> None:
        """Inert selector regression, not proof that font overflow is resolved."""
        rules = re.sub(r"/\*.*?\*/", "", CSS, flags=re.DOTALL)
        selected = [(selector.strip(), body.strip())
                    for selector, body in re.findall(r"([^{}]+)\{([^{}]+)\}", rules)
                    if "line-height" in body]
        self.assertEqual(len(selected), 1)
        selector, body = selected[0]
        prefix = '#ag-root[data-sniper-layout="caption-safe-upper-v1"] '
        self.assertEqual([value.strip() for value in selector.split(",")],
                         [prefix + name for name in ("#ag-title", "#ag-eyebrow", ".ag-title-row")])
        self.assertEqual(body, "line-height: 1.25;")
        for size, height in ((132, "0.98"), (34, "1"), (52, "1.02")):
            self.assertIn(f"font-size: {size}px; line-height: {height};", HTML)


if __name__ == "__main__":
    unittest.main()

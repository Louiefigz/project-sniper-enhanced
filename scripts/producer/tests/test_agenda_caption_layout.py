"""The deleted agenda design cannot return through its former layout options."""
from pathlib import Path
import unittest
from graphics.graphics_render import comp_path
from graphics.template_contract import entry_errors


class AgendaRetirementTests(unittest.TestCase):
    """Retirement replaces the old design's layout acceptance contract."""

    def test_agenda_file_is_absent_and_all_old_variants_refuse(self) -> None:
        root = Path(__file__).resolve().parents[3]
        self.assertFalse((root / "templates/motion/compositions/agenda-slide.html").exists())
        with self.assertRaisesRegex(ValueError, "retired"):
            comp_path("agenda-slide")
        for layout in ("full-canvas", "caption-safe-upper-v1"):
            entry = {"kind": "agenda-slide", "outStart": 0, "outEnd": 5,
                     "spec": {"layout": layout, "title": "TEST former agenda"}}
            self.assertTrue(any("retired" in error for error in entry_errors(entry)))


if __name__ == "__main__":
    unittest.main()

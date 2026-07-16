"""Stable graphic ids — lint uniqueness, refit preservation, fingerprint invariance.

The editor addresses graphics by a code-stamped ``id`` (never array index), so:
  * plan_lint must ERROR on a duplicate id (two blocks masquerading as one),
    tolerate a missing id (brain-authored / legacy plans carry none), and reject
    a non-string id;
  * plan_refit must PRESERVE the id through a cutTrack remap (verified, not
    assumed — refit only rewrites window times);
  * graphics_fingerprint must IGNORE the id (it has no effect on the pixels, so
    stamping one must never invalidate a current composite).
"""
import unittest

from _common import *  # noqa: F401,F403 — gives pl, good_plan, MANIFEST, unittest

import fingerprints as fpr
from edit.plan_refit import refit_plan


def _graphic(gid=None, start=5.0, end=9.0, kind="stat-card"):
    g = {"outStart": start, "outEnd": end, "kind": kind,
         "anchor": "free-band", "spec": {"value": "42%"}, "reason": "x"}
    if gid is not None:
        g["id"] = gid
    return g


class GraphicIdLintTests(unittest.TestCase):
    """_check_graphic_ids: uniqueness + type, presence optional."""

    def _errors(self, *graphics) -> list[str]:
        rep = pl.Report()
        pl._check_graphic_ids({"graphicsTrack": list(graphics)}, rep)
        return rep.errors

    def test_unique_ids_pass_clean(self) -> None:
        self.assertEqual(self._errors(_graphic("g-11112222"),
                                      _graphic("g-33334444")), [])

    def test_duplicate_id_errors(self) -> None:
        errors = self._errors(_graphic("g-aaaabbbb"), _graphic("g-aaaabbbb"))
        self.assertTrue(any("duplicate graphic id" in e for e in errors), errors)

    def test_missing_id_is_allowed(self) -> None:
        # Back-compat: brain-authored plans carry no ids; only present ids are checked.
        self.assertEqual(self._errors(_graphic(None), _graphic(None)), [])

    def test_mixed_present_and_absent_ids(self) -> None:
        self.assertEqual(self._errors(_graphic("g-11112222"), _graphic(None)), [])

    def test_non_string_id_errors(self) -> None:
        errors = self._errors(_graphic(7))  # type: ignore[arg-type]
        self.assertTrue(any("must be a non-empty string" in e for e in errors), errors)

    def test_empty_string_id_errors(self) -> None:
        errors = self._errors(_graphic(""))
        self.assertTrue(any("must be a non-empty string" in e for e in errors), errors)

    def test_duplicate_id_fires_through_full_lint(self) -> None:
        # Wiring: the check runs inside pl.lint (before the cut early-return).
        plan = good_plan()
        plan["graphicsTrack"] = [_graphic("g-dupdupdu", 5.0, 8.0),
                                 _graphic("g-dupdupdu", 10.0, 12.0)]
        errors = pl.lint(plan, MANIFEST).errors
        self.assertTrue(any("duplicate graphic id" in e for e in errors), errors)


class RefitPreservesIdTests(unittest.TestCase):
    """A cutTrack remap must carry the id along with the window."""

    def _plan(self, *graphics) -> dict:
        return {"cutTrack": [{"sourceId": "raw", "start": 10.0, "end": 50.0}],
                "target": {"mode": "longform"}, "graphicsTrack": list(graphics)}

    def test_id_survives_a_window_shift(self) -> None:
        old = self._plan(_graphic("g-keepthis", 25.0, 30.0))
        new = {"cutTrack": [{"sourceId": "raw", "start": 10.0, "end": 25.0},
                            {"sourceId": "raw", "start": 30.0, "end": 50.0}],
               "target": {"mode": "longform"},
               "graphicsTrack": [_graphic("g-keepthis", 25.0, 30.0)]}
        plan, _ = refit_plan(old, new)
        entry = plan["graphicsTrack"][0]
        self.assertEqual(entry["id"], "g-keepthis")          # id preserved
        self.assertAlmostEqual(entry["outStart"], 20.0, places=2)  # window remapped

    def test_id_survives_an_untouched_window(self) -> None:
        old = self._plan(_graphic("g-early777", 2.0, 6.0))
        new = self._plan(_graphic("g-early777", 2.0, 6.0))
        plan, _ = refit_plan(old, new)
        self.assertEqual(plan["graphicsTrack"][0]["id"], "g-early777")


class GraphicsFingerprintIgnoresIdTests(unittest.TestCase):
    """The id is render-irrelevant — it must not shift graphics_fingerprint."""

    def test_stamping_an_id_does_not_change_the_fingerprint(self) -> None:
        idless = {"graphicsTrack": [_graphic(None, 5.0, 9.0)]}
        stamped = {"graphicsTrack": [_graphic("g-abcd1234", 5.0, 9.0)]}
        self.assertEqual(fpr.graphics_fingerprint(idless),
                         fpr.graphics_fingerprint(stamped))

    def test_different_ids_same_content_hash_equal(self) -> None:
        a = {"graphicsTrack": [_graphic("g-11112222", 5.0, 9.0)]}
        b = {"graphicsTrack": [_graphic("g-99998888", 5.0, 9.0)]}
        self.assertEqual(fpr.graphics_fingerprint(a),
                         fpr.graphics_fingerprint(b))

    def test_a_real_content_change_still_flips_the_fingerprint(self) -> None:
        a = {"graphicsTrack": [_graphic("g-11112222", 5.0, 9.0)]}
        b = {"graphicsTrack": [_graphic("g-11112222", 5.0, 12.0)]}  # window changed
        self.assertNotEqual(fpr.graphics_fingerprint(a),
                            fpr.graphics_fingerprint(b))


if __name__ == "__main__":
    unittest.main(verbosity=2)

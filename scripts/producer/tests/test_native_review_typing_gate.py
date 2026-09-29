"""Typed review evidence at the export boundary: refusals before any budget charge, and canonical paths.

TEST structure only: nothing here was viewed or heard, and no budget authority is touched (the reservation is
patched to fail if it were ever reached).
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import json
import os
import sys
import tempfile
import unittest
from argparse import Namespace
from fractions import Fraction
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audio.mastering_profile import NATIVE_SHORT_MASTERING_PROFILE  # noqa: E402
from role_packet_media import windows  # noqa: E402
from studio import native_short_export as export  # noqa: E402
from studio.native_motion_review import require_typed_short_reviews  # noqa: E402


def write(path: Path, value: dict) -> Path:
    """Write one TEST JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


class ReviewTypingGateTests(unittest.TestCase):
    """Untyped or picture-only Short motion reviews never reach the budget reservation."""

    def setUp(self) -> None:
        """A canonical private root with a TEST project folder."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp'))).resolve()
        self.project = self.root / 'project'
        self.project.mkdir()

    def bundle(self, name: str, inspection: dict | None) -> Path:
        """A TEST bundle with one row, typed or not."""
        row = {'reviewer': {'sessionId': 'TEST-critic'}, 'review': {'verdict': 'pass', 'materialIssues': []}}
        return write(self.root / name, {'schemaVersion': 1, 'reviews': [{**row, **({'inspection': inspection} if inspection else {})}]})

    def options(self, reviews: Path) -> Namespace:
        """A complete exporter namespace naming these reviews."""
        return Namespace(project=self.project, output=self.root / 'final-v1', preview_reviews=reviews, review_draft=False,
                         promote_draft=None, draft_findings=None, audio_donor=None, picture_donor=None, preview_only=False,
                         preview_from=None, cache=None, cached_native_batches=False, acquire_source_cache=False,
                         reference_map=None, audio_profile=NATIVE_SHORT_MASTERING_PROFILE.identity, verify_from=None,
                         resume_from=None, render_only=False)

    def test_untyped_and_picture_only_reviews_are_refused_before_the_reservation(self) -> None:
        """A pre-B2 bundle, or one approving picture only, fails option validation; the reservation never runs."""
        cases = {'untyped': (None, 'carry no typed inspection'),
                 'picture': ({'schemaVersion': 1, 'entries': [], 'approves': ['picture']}, 'no row approves motion')}
        for name, (inspection, message) in cases.items():
            reviews = self.bundle(f'{name}.json', inspection)
            with self.subTest(name), mock.patch.object(export, 'reserve_for_args', side_effect=AssertionError('charged')), \
                    self.assertRaisesRegex(ValueError, message):
                export.execute(self.options(reviews))
        promote = self.options(self.bundle('promote.json', None))
        promote.promote_draft = self.root / 'draft-v1'
        with mock.patch.object(export, 'reserve_for_args', side_effect=AssertionError('charged')), \
                self.assertRaisesRegex(ValueError, 'Refused before any budget reservation'):
            export.execute(promote)

    def test_a_typed_motion_approval_passes_the_cheap_check(self) -> None:
        """The cheap check reads structure only; the TS reader still decides full admission after reservation."""
        typed = {'schemaVersion': 1, 'entries': [], 'approves': ['picture', 'motion']}
        require_typed_short_reviews(self.bundle('typed.json', typed), self.project)

    def test_a_canary_fixture_declaration_never_admits_a_batch_budgeted_project(self) -> None:
        """Probe p14: a TEST route-canary row is refused before reservation once a production batch binds the project."""
        fixture = {'schemaVersion': 1, 'entries': [], 'approves': ['picture', 'motion'], 'fixture': {
            'scope': 'TEST-native-route-canary-fixture', 'manifest': {'path': '/TEST/FIXTURE.json', 'sha256': 'a' * 64},
            'project': str(self.project)}}
        bundle = self.bundle('fixture.json', fixture)
        with mock.patch('studio.native_budget_registry.resolve_binding', return_value=None):
            require_typed_short_reviews(bundle, self.project)
        with mock.patch('studio.native_budget_registry.resolve_binding', return_value={'batchId': 'batch-test', 'clipId': 'Q1'}), \
                self.assertRaisesRegex(ValueError, 'route-canary TEST fixture declarations, and a production batch budgets'):
            require_typed_short_reviews(bundle, self.project)

    def test_an_export_through_a_symlinked_attempt_parent_is_refused_at_prepare(self) -> None:
        """Every recorded attempt path is real: an aliased output parent never reaches preview or export."""
        (self.root / 'real').mkdir()
        os.symlink(self.root / 'real', self.root / 'alias')
        args = self.options(None)
        args.output = self.root / 'alias' / 'preview-v1'
        with self.assertRaisesRegex(RuntimeError, 'must be canonical'):
            export.validate_options(args, self.project, args.output.absolute())

    def test_motion_packet_windows_name_the_real_clip_path(self) -> None:
        """Windows recorded through an alias are reported at the same real path the packet freezes."""
        clip = self.root / 'real' / 'window-0' / 'core.mp4'
        clip.parent.mkdir(parents=True)
        clip.write_bytes(b'TEST clip bytes')
        os.symlink(self.root / 'real', self.root / 'alias')
        value = {'clips': [{'startFrame': 0, 'endFrameExclusive': 30, 'path': str(self.root / 'alias/window-0/core.mp4'),
                            'sha256': 'a' * 64}]}
        self.assertEqual(windows(value, Fraction(30))[0]['path'], str(clip))


if __name__ == '__main__':
    unittest.main()

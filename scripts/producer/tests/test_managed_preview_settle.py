"""M1 (P0 Step 5.1): opening a view while another project's view is registered goes through the state API.

``managed_preview_launch.require_capacity`` (moved from managed_preview at M-056) settles every other
registered view with ``managed_preview_state.
settle_launch``; before M-025 src's state module (the add8f82c file) lacked it, so any open beside another view
raised AttributeError. TEST folders and a private registry only; no process is started or signalled.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import native_work_lease as work
from studio import managed_preview_launch as launching
from studio import managed_preview_registry as registry


class OtherViewTests(unittest.TestCase):
    """The capacity check reaches every other view's settlement without an AttributeError."""

    def test_open_with_another_view_registered_settles_without_attribute_error(self) -> None:
        """A stopped view of another project is settled (unchanged) and counts as no active view."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        mine, other = root / 'draft-mine', root / 'draft-other'
        for project in (mine, other):
            project.mkdir()
        self.enterContext(mock.patch.object(work, 'state_root', return_value=root / 'registry'))
        entry = {'schemaVersion': 2, 'state': 'stopped', 'project': str(other)}
        with registry.transaction(registry.monotonic_until(5.0)) as reg:
            registry.write_entry(reg, entry)
            launching.require_capacity(reg, str(mine))
            self.assertEqual(registry.read_entry(reg, str(other)), entry)


if __name__ == '__main__':
    unittest.main()

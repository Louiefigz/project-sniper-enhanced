"""M3 (P0 Step 5.3, D1 item 7): ``output-authorized`` carries its approval, so the chained reader reads it back.

An own-clock Short authorized through ``api.authorize_output`` in a run holding a Long: ``approvals.read_approval``
returns its approved title and script (before M-026 the event lacked ``approval`` and the reader refused the
authority as corrupt). TEST records in a private root only.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import json
import unittest

from test_production_formats import FormatCase
from studio.production.approvals import read_approval


class OutputApprovalTests(FormatCase):
    """The approval an own-clock Short was authorized with is the one the authority reads back."""

    def test_an_own_clock_short_approval_reads_back(self) -> None:
        """The event names the first approval's identity; the reader returns it as current."""
        self.authorize('L')
        self.clock.advance(1800)
        self.authorize('N', 'short')
        bound = self.record()['clips']['N']['approvals'][0]
        found = read_approval(self.root, 'batch-auth', 'N')
        self.assertEqual(found['current']['identity'], bound['identity'])
        trail = (self.root / 'batches/batch-auth/events.jsonl').read_text().splitlines()
        events = [row for row in map(json.loads, trail) if row.get('event') == 'output-authorized'
                  and row['clipId'] == 'N']
        self.assertEqual([row['approval'] for row in events], [bound['identity']])


if __name__ == '__main__':
    unittest.main()

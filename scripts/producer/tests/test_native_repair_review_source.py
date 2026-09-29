"""Independent combined repair/integration source selection with actual registered requests."""
from __future__ import annotations

import copy
import unittest
from pathlib import Path

import test_production_scoped_repair as fixtures
from cut_preview_io import write_new
from studio.native_export_history import register_attempt
from studio.native_runtime import digest
from studio.production.section_review_reuse import original_assignment


class RepairReviewSourceTests(unittest.TestCase):
    """Retain original unchanged interiors while finding the new B scope's current review source."""

    def test_changed_b_uses_its_registered_scope_while_a_uses_full_parent(self) -> None:
        """A combined request must not hide B's new author behind the old repair parent."""
        fixture = fixtures.ScopedRepairTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        parent = fixture.initial()
        fixture.repair(parent)
        h = fixture.h
        current = h.request
        row = h.context['assignments'][1]
        scoped = copy.deepcopy(current)
        scoped['output'] = str(h.budget.base / 'new-b-scoped')
        scoped['sectionAttemptSequence'] = 2
        scoped['sectionScope'] = {'schemaVersion': 1, **{key: row[key] for key in
            ('sectionId', 'generation', 'inputIdentity', 'frameRange')},
            'sharedPlan': h.context['sharedPlan'], 'snapshotProject': scoped['project'],
            'snapshotPinsHash': 'f' * 64}
        output = Path(scoped['output'])
        output.mkdir()
        file = output / 'export-request.json'
        write_new(file, scoped)
        register_attempt(scoped)
        request = copy.deepcopy(current)
        request['pins'][str(file)] = digest(file)
        request['sectionIntegrations'] = [{'sectionId': 'B', 'originalAttempt': str(output),
                                          'originalRequestSha256': digest(file)}]
        self.assertEqual(original_assignment(request, row), scoped)
        self.assertEqual(original_assignment(request, h.context['assignments'][0]), parent)
        changed = copy.deepcopy(request)
        changed['sectionIntegrations'][0]['originalRequestSha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'not pinned'):
            original_assignment(changed, row)


if __name__ == '__main__':
    unittest.main()

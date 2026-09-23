"""Bracketed live-memory reads tolerate exits without forgiving unknown live children."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from native_render_processes import MissingProcessFootprint, ResourceMeasurementError
from native_render_sampling import read_compact_snapshot
from test_native_render_resources import direct_sample, REQUEST, START, GIB


class CompactSamplingTests(unittest.TestCase):
    """Exercise the actual parser and identity reconciliation with captured raw schemas."""

    def sample(self, mutate=None):
        """Replace command execution only; no fake successful snapshot is returned."""
        raw = direct_sample()
        envelope = {'before': raw['ps'], 'after': raw['ps'], 'direct': json.loads(raw['direct'])}
        if mutate:
            mutate(envelope)
        with patch('native_render_sampling._read_command',
                   side_effect=[raw['sysctl'], raw['pressure'], json.dumps(envelope)]) as command:
            result = read_compact_snapshot(Path('/private/tmp'), REQUEST)
        self.assertEqual(len(command.call_args.args[0]), 2)
        self.assertEqual(json.loads(command.call_args.args[1])['root']['pid'], 100)
        return result

    def test_complete_live_tree_is_measured(self):
        """All observed live children contribute their inclusive physical footprint."""
        self.assertEqual(self.sample().owned_footprint_bytes, 3 * GIB)

    def test_confirmed_exit_is_not_a_missing_live_measurement(self):
        """A child gone from the second table is excluded; the root remains measured."""
        def exited(row):
            row['after'] = f'100 1 100 {START}\n500 1 500 {START}\n'
            row['direct']['processes'] = [p for p in row['direct']['processes'] if p['pid'] != 101]
        result = self.sample(exited)
        self.assertEqual(result.owned_pids, (100,))
        self.assertEqual(result.owned_footprint_bytes, 2 * GIB)

    def test_new_live_child_requires_fresh_measurement(self):
        """A newborn child never becomes a guessed zero footprint."""
        with self.assertRaises(MissingProcessFootprint):
            self.sample(lambda row: row.update(after=row['after'] + f'102 100 102 {START}\n'))

    def test_missing_still_live_child_fails(self):
        """A missing process row remains an error even when host memory looks healthy."""
        def missing(row):
            row['direct']['processes'] = [p for p in row['direct']['processes'] if p['pid'] != 101]
        with self.assertRaises(MissingProcessFootprint):
            self.sample(missing)

    def test_pid_reuse_is_never_charged_as_original_child(self):
        """Recycled identities cannot silently inherit the former process measurement."""
        with self.assertRaises(MissingProcessFootprint):
            self.sample(lambda row: row.update(after=row['after'].replace('101 '+START, '101 DIFFERENT')))

    def test_permission_failure_remains_terminal(self):
        """Permanent libproc failures do not enter the process-exit retry path."""
        def denied(row):
            row['direct']['processes'][0] = {'pid': 100, 'status': 'unavailable', 'result': -1, 'errno': 1}
        with self.assertRaises(ResourceMeasurementError):
            self.sample(denied)

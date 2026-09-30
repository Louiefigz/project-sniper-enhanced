"""M-132 (P4-12): a lineage superset is a different Long; the share of the union decides.

Two Long lineages are the same Long when they bind the same request, or when their recording sets share at least
half of their union. Holding all of the smaller set is no longer enough: {A} against {A,B,C,D,E} shares 1 of 5 and is
a different Long, so binding it to Long L's output is refused by name (E-LIN-1). {A,B,C} against {A,B,C,D} shares
3 of 4 and stays the same Long; a single-recording Long re-prepared under a new request shares 1 of 1. Lineages and
records are in memory; every digest is a TEST fixture.
"""
from __future__ import annotations

import hashlib
import unittest

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused
from studio.production.lineage import output_match, same_long
from studio.production.outputs import binding_refusal

DIFFERENT_LONG = 'This Long project was prepared from another request and other recordings than Long L'


def digest(name: str) -> str:
    """A TEST SHA-256."""
    return hashlib.sha256(f'TEST {name}'.encode()).hexdigest()


def lineage(request: str, *recordings: str) -> dict:
    """A TEST Long lineage: its request packet digest and its sorted unique recording digests."""
    return {'request': digest(request), 'sources': sorted({digest(name) for name in recordings})}


def run_holding(bound: dict) -> dict:
    """A run whose Long L (authorized for 600 s, no project row yet) is bound to ``bound``."""
    row = {'format': 'long', 'lineage': bound, 'outputSeconds': 600.0, 'derivedFrom': None}
    return {'clips': {'L': {'output': row, 'projects': []}}}


def project(value: dict) -> dict:
    """A new Long project folder (580 s canvas) whose prepared request gives lineage ``value``."""
    return {'format': 'long', 'key': 'TEST-long-folder', 'projectHash': digest('long content'), 'lineage': value,
            'outputSeconds': 580.0, 'selection': None}


class LongLineageTests(unittest.TestCase):
    """P4-12's cases through ``same_long``, ``output_match`` and ``binding_refusal``."""

    def assert_same(self, first: dict, second: dict, same: bool) -> None:
        """``same_long`` answers ``same`` in both orders."""
        self.assertEqual((same_long(first, second), same_long(second, first)), (same, same))

    def test_a_superset_lineage_is_a_different_long(self) -> None:
        """{A} against {A,B,C,D,E} (1 of 5) is another Long: no revision match, and binding is refused by name."""
        bound, superset = lineage('request-1', 'A'), lineage('request-2', 'A', 'B', 'C', 'D', 'E')
        self.assert_same(bound, superset, False)
        self.assert_same(lineage('request-1', 'A'), lineage('request-2', 'A', 'B', 'C'), False)            # 1 of 3
        self.assert_same(lineage('request-1', 'A', 'B'), lineage('request-2', 'A', 'B', 'C', 'D', 'E'), False)  # 2 of 5
        run = run_holding(bound)
        self.assertIsNone(output_match(run['clips']['L'], project(superset)))
        refusal = binding_refusal(run, 'L', project(superset))
        self.assertEqual(refusal, f'{DIFFERENT_LONG}; a different Long needs its own authorization')

    def test_adding_one_recording_stays_the_same_long(self) -> None:
        """{A,B,C} against {A,B,C,D} (3 of 4) is a revision of Long L and binds to it."""
        bound, grown = lineage('request-1', 'A', 'B', 'C'), lineage('request-2', 'A', 'B', 'C', 'D')
        self.assert_same(bound, grown, True)
        run = run_holding(bound)
        self.assertEqual(output_match(run['clips']['L'], project(grown)), 'revision')
        self.assertIsNone(binding_refusal(run, 'L', project(grown)))

    def test_a_reprepared_single_recording_long_stays_the_same_long(self) -> None:
        """One recording re-prepared under a new request (1 of 1) is the same Long."""
        self.assert_same(lineage('request-1', 'A'), lineage('request-2', 'A'), True)

    def test_same_request_always_same(self) -> None:
        """The same request packet is the same Long whatever recordings each side lists."""
        self.assert_same(lineage('request-1', 'A'), lineage('request-1', 'B', 'C', 'D', 'E'), True)

    def test_exactly_half_of_the_union_is_the_same_long(self) -> None:
        """The boundary: 1 of 2 and 2 of 4 are the same Long; 2 of 5 is not."""
        self.assert_same(lineage('request-1', 'A'), lineage('request-2', 'A', 'B'), True)
        self.assert_same(lineage('request-1', 'A', 'B'), lineage('request-2', 'A', 'B', 'C', 'D'), True)
        self.assert_same(lineage('request-1', 'A', 'B', 'C'), lineage('request-2', 'B', 'C', 'D', 'E'), False)  # 2 of 5


if __name__ == '__main__':
    unittest.main()

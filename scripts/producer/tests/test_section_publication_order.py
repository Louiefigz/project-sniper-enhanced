"""LA-04: every proof read happens before the last clock sample; only the write (or rename) follows it (M-060).

Ported from ``plan-sources/dr-03-07/probe_la04.py`` (P1 Step D1) with the same patches: a fake ``locked_batch``
session, a null ``attempt_reservation``, a fixed ``assembly_snapshot``, and ``revalidate_context`` replaced by the
saved context plus an injected delay, which stands for the slow cold proof read (plan rehash and ancestry). The
batch clock is the real ``advance_clock`` (with the real ``observe`` and ``checkpoint``); only its time sources are
injected (``continuous_now``, ``time.time`` and ``boot_id``), and the proof delay advances them instead of sleeping.
So no result depends on how fast the host runs, and no ``sysctl`` child is started for the boot identity.

The control also patches the two proofs that need real media or repair state (``require_checked_media`` and
``retained_current_sections``), so the real ``apply_family_outcome`` commits. The assembly test patches the media
steps of ``assemble_initial`` (``ordered_pieces``, ``check_coverage``, ``check_compatible``, ``check_bytes``,
``concat``, which creates the pending picture, and ``verify_assembly``). No authority store, media or child process.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import contextlib
import json
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cut_preview_io
from studio.native_budget_batches import BudgetRefused
from studio.native_runtime import digest
from studio.native_segments import assemble
from studio.production import section_publication as publication

GRANT_SECONDS = 1.5  # the original grant ends this long after the fixture's start sample
PROOF_DELAY = 2.5  # the injected slow proof read, longer than the remaining grant
CHECKED = 'native-long-checked-for-review'
START = 1000.0
EPOCH = 1_750_000_000.0  # the injected wall clock at the fixture's start sample
BOOT = '0a0a0a0a-0000-4000-8000-000000000060'  # the injected boot identity


class Session:
    """The fake locked batch session: it hands out the one record and logs each commit."""

    def __init__(self, fixture: PublicationFixture) -> None:
        """Bind the session to its fixture."""
        self.fixture = fixture

    def read(self) -> dict:
        """Return the fixture's in-memory record."""
        return self.fixture.record

    def commit(self, _record: dict, event: dict) -> None:
        """Log the committed event."""
        self.fixture.log.append(('commit', event))


class PublicationFixture:
    """One Long family output whose original grant ends GRANT_SECONDS after the start sample."""

    def __init__(self, root: Path) -> None:
        """Build the project, output, record and request of probe_la04 under ``root``."""
        self.log: list[tuple] = []
        self.now = 0.0  # injected seconds since the start sample; only the proof delay advances it
        self.project, self.output = root / 'project', root / 'out'
        self.project.mkdir()
        self.output.mkdir()
        (self.project / 'LONG-PROJECT.json').write_text('{}')
        plan_sha = digest(self.project / 'LONG-PROJECT.json')
        plan_ref = {'path': str(root / 'plan.json'), 'sha256': 'a' * 64}
        grant_end = START + GRANT_SECONDS
        attempt = {'id': 'fam1', 'route': 'final', 'status': 'running', 'admittedElapsed': 900.0,
                   'grantedSeconds': grant_end - 900.0}
        row = {'id': 'inv1', 'sectionId': None, 'status': 'running', 'project': str(self.project),
               'output': str(self.output), 'requestSha256': None, 'planSha256': plan_sha, 'scopeSha256': None}
        family = {'id': 'fam1', 'plan': plan_ref, 'state': 'finalizing', 'invocations': [row], 'assignments': []}
        output = {'format': 'long', 'deadlineElapsed': grant_end + 1620.0, 'preparationElapsed': 500.0,
                  'outputSeconds': 600}
        clip = {'state': 'active', 'attempts': [attempt], 'sectionFamilies': [family], 'deliveries': [],
                'output': output}
        self.record = {'batchId': 'b1', 'status': 'active', 'startEpoch': EPOCH - START,
                       'clock': {'boot': BOOT, 'continuous': 0.0, 'epoch': EPOCH, 'elapsed': START},
                       'production': {'authorization': {'setup': 'complete'}, 'tasks': {}},
                       'clips': {'c1': clip}, 'holds': [], 'deadlines': {}}
        self.request = self._request(root, plan_ref, plan_sha)
        (self.output / 'export-request.json').write_text(json.dumps(self.request))
        (self.output / 'revision-picture.json').write_text(json.dumps({'sectionSnapshot': {'s': 1}}))

    def _request(self, root: Path, plan_ref: dict, plan_sha: str) -> dict:
        """The exact family request the worker published."""
        authority = {'authority': str(root / 'auth'), 'batchId': 'b1', 'clipId': 'c1'}
        return {'project': str(self.project), 'output': str(self.output),
                'revision': {'mode': 'initial-long', 'grid': {'gops': [[0, 10]], 'timescale': 90000},
                             'renderWindows': []},
                'productionBudget': {**authority, 'familyId': 'fam1', 'attemptId': 'fam1', 'route': 'final',
                                     'familyInvocation': 'inv1'},
                'sectionProduction': {**authority, 'plan': plan_ref, 'assignments': []},
                'pins': {str(self.project / 'LONG-PROJECT.json'): plan_sha}, 'sectionScope': None}

    @contextlib.contextmanager
    def patched(self, delay: float) -> Iterator[None]:
        """Apply probe_la04's patches, with ``delay`` seconds of proof reading."""
        real_sample, real_write = publication.advance_clock, cut_preview_io.write_new

        def sample(record: dict) -> float:
            """Trace the real clock sample."""
            value = real_sample(record)
            self.log.append(('clock-sample', value))
            return value

        def slow_context(request: dict) -> dict:
            """Stand for the cold plan read and ancestry proof."""
            self.now += delay
            self.log.append(('proof-read-done',))
            return request['sectionProduction']

        def write(path: Path, value: dict) -> None:
            """Trace the real exclusive write."""
            real_write(path, value)
            self.log.append(('write', Path(path).name, value.get('status')))

        with contextlib.ExitStack() as stack:
            for target, value in (
                    ('studio.production.section_publication.locked_batch', lambda _root, _batch: self.session()),
                    ('studio.production.section_publication.attempt_reservation',
                     lambda _request: contextlib.nullcontext()),
                    ('studio.production.section_publication.advance_clock', sample),
                    ('studio.native_segments.reviews.assembly_snapshot', lambda _request, _record=None: {'s': 1}),
                    ('studio.production.section_plan.revalidate_context', slow_context),
                    ('studio.production.section_plan.require_context', lambda _record, _context: None),
                    ('cut_preview_io.write_new', write),
                    ('studio.native_budget_clock.continuous_now', lambda: self.now),
                    ('studio.native_budget_clock.boot_id', lambda: BOOT),
                    ('studio.native_budget_clock.time', SimpleNamespace(time=lambda: EPOCH + self.now))):
                stack.enter_context(mock.patch(target, value))
            yield

    @contextlib.contextmanager
    def session(self) -> Iterator[Session]:
        """The fake held batch lock."""
        yield Session(self)

    def names(self) -> list[str]:
        """The timeline's event names in order."""
        return [row[0] for row in self.log]


class PublicationOrderTests(unittest.TestCase):
    """The last clock sample follows every proof read, in both publication paths."""

    def setUp(self) -> None:
        """A private folder per test."""
        folder = tempfile.TemporaryDirectory(prefix='la04-')
        self.addCleanup(folder.cleanup)
        self.fixture = PublicationFixture(Path(folder.name).resolve())  # cut_preview_io needs canonical paths

    def assert_proofs_before_last_sample(self, publication_event: str | None) -> None:
        """Before ``publication_event`` (or in the whole log) no proof read follows the last clock sample.

        With an event named, that event comes immediately after the last sample: only the write follows it.
        Only ``section_publication.advance_clock`` is traced. After the write, ``apply_family_outcome`` samples
        again through ``native_budget_binding.advance_clock`` (untraced) before its own grant check, so the
        control's log shows proof reads after the last traced sample; they follow the write and are out of scope.
        """
        names = self.fixture.names()
        names = names[:names.index(publication_event)] if publication_event else names
        last = len(names) - 1 - names[::-1].index('clock-sample')
        self.assertIn('proof-read-done', names[:last], self.fixture.log)
        self.assertNotIn('proof-read-done', names[last:], self.fixture.log)
        if publication_event:
            self.assertEqual(last, len(names) - 1, self.fixture.log)

    def test_expiry_during_proof_reads_writes_no_checked_delivery(self) -> None:
        """A grant that ends during the proof reads leaves a failed delivery and never a checked receipt."""
        result = {'status': CHECKED, 'output': str(self.fixture.output / 'final.mp4'), 'sha256': 'b' * 64}
        with self.fixture.patched(PROOF_DELAY):
            publication.publish_delivery(self.fixture.request, result)
        saved = json.loads((self.fixture.output / 'delivery.json').read_text())
        self.assertEqual(saved['status'], 'failed', self.fixture.log)
        self.assertEqual(saved['failureCategory'], 'section-publication-stale')
        self.assertIn('original grant ended', saved['error'])
        self.assertNotIn(('write', 'delivery.json', CHECKED), self.fixture.log)
        self.assertNotIn('commit', self.fixture.names())
        self.assert_proofs_before_last_sample('write')

    def test_fast_proofs_publish_and_commit(self) -> None:
        """Control: with fast proofs the checked delivery is written and its family outcome committed."""
        result = {'status': CHECKED, 'output': str(self.fixture.output / 'final.mp4'), 'sha256': 'b' * 64}
        with self.fixture.patched(0.0), \
                mock.patch('studio.native_budget_family_delivery.require_checked_media'), \
                mock.patch('studio.native_budget_family_repair.retained_current_sections', return_value=set()):
            publication.publish_delivery(self.fixture.request, result)
        saved = json.loads((self.fixture.output / 'delivery.json').read_text())
        self.assertEqual(saved['status'], CHECKED, result)
        self.assertEqual(result['status'], CHECKED)
        commits = [row[1] for row in self.fixture.log if row[0] == 'commit']
        self.assertEqual([(row['kind'], row['status'], row['resultStatus']) for row in commits],
                         [('section-family-invocation', 'succeeded', CHECKED)])
        self.assertLess(self.fixture.names().index('write'), self.fixture.names().index('commit'))
        self.assert_proofs_before_last_sample('write')

    def test_assemble_initial_does_not_rename_after_expiry(self) -> None:
        """The same expiry refuses the picture rename; the pending picture is kept for the caller."""
        pending, picture = self.fixture.output / 'picture.pending.mp4', self.fixture.output / 'picture.mp4'
        with self.fixture.patched(PROOF_DELAY), media_steps(pending):
            with self.assertRaises(BudgetRefused) as caught:
                assemble.assemble_initial(self.fixture.request, self.fixture.output, None)
        self.assertFalse(picture.exists(), self.fixture.log)
        self.assertTrue(pending.exists())
        self.assertIn('original grant ended', str(caught.exception))
        self.assert_proofs_before_last_sample(None)


@contextlib.contextmanager
def media_steps(pending: Path) -> Iterator[None]:
    """Replace assemble_initial's media steps; ``concat`` creates the pending picture."""
    def concat(_pieces: list, output: Path, _tools: object, _timescale: int) -> None:
        """Write the pending picture the rename would publish."""
        output.write_bytes(b'picture')

    with contextlib.ExitStack() as stack:
        for name, value in (('ordered_pieces', lambda _request, _delivered: [{'stream': {}, 'frames': 10}]),
                            ('check_coverage', lambda _pieces, _end: None),
                            ('check_compatible', lambda _pieces, _reference: None),
                            ('check_bytes', lambda _pieces: None), ('concat', concat),
                            ('verify_assembly', lambda _path, _pieces, _tools, _reference: {})):
            stack.enter_context(mock.patch.object(assemble, name, value))
        yield


if __name__ == '__main__':
    unittest.main()

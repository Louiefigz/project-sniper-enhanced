"""Visible hand-off confirmation and its read-only re-verification (``verify_confirmation``).

``confirm`` sets ``visibleHandoffAt`` only for the served review page's own playback report after views-ready,
a full re-check and the attestation; ``verify_confirmation`` re-runs every check on an existing confirmation for
the batch authority, writes nothing, and refuses a hand-written record. Fixture: ``_handoff_fixture.HandoffFixture``
(fake Studio, real review player, TEST authority reader).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from _handoff_fixture import HandoffFixture
from studio import native_handoff as handoff
from studio import native_handoff_confirm as confirmation
from studio.native_handoff_confirm import Confirmation, confirm
from studio.native_handoff_record import utc
from studio.native_handoff_verify import ConfirmationRefused
from studio.native_runtime import digest
from studio.review_player_inventory import Attempt


class VisibleConfirmationTests(HandoffFixture, unittest.TestCase):
    """Only the served page's own playback report plus the attestation, after a full re-check, sets visibleHandoffAt."""

    def pages(self, record: dict) -> tuple[str, str, str, str]:
        """The exact verified URLs, a browser name and the attesting coordinator."""
        return record['reviewPlayer']['url'], record['studio']['url'], 'TEST Chrome', 'TEST coordinator session'

    def views_ready(self) -> dict:
        """A views-ready hand-off whose served review page then reported playing the MP4."""
        record = handoff.hand_off(self.request())
        self.assertEqual(self.page_playback(self.player_url, record['reviewPlayer']['route']), 204)
        return record

    def confirmed(self, record: dict, name: str = 'visible.json') -> dict:
        """Run the confirmation for this record."""
        return confirm(Confirmation(self.root / 'handoff.json', self.root / name, self.pages(record), 10.0))

    def test_confirmation_needs_the_pages_own_playback_report_and_a_full_recheck(self) -> None:
        """Operator item #4 / probe p11: a curl or browser-looking GET of the MP4 is 'media requested' only; the
        served page's own 'playing' report (a token from a page load after views-ready) sets visibleHandoffAt."""
        record = handoff.hand_off(self.request())
        for agent in ('curl/8.7.1', 'Mozilla/5.0 TEST browser'):
            self.assertEqual(self.browser_load(self.player_url, record['reviewPlayer']['route'], agent=agent), 206)
        missing = self.confirmed(record, 'missing.json')
        self.assertEqual([row['code'] for row in missing['failures']], ['REVIEW_PAGE_PLAYBACK_NOT_OBSERVED'])
        self.assertEqual([row['userAgent'] for row in missing['observed']['mediaRequested']],
                         ['curl/8.7.1', 'Mozilla/5.0 TEST browser'])
        self.assertEqual(self.page_playback(self.player_url, record['reviewPlayer']['route']), 204)
        identity_checks = self.studio.requests.count('/__hyperframes_config')
        result = self.confirmed(record)
        self.assertEqual((result['status'], result['visibleHandoffAt']), ('visible-handoff', result['confirmedAt']))
        self.assertEqual(result['observed']['reviewPagePlayback'][0]['event'], 'playing')
        self.assertIn('review page and the Studio page were opened', result['attestation']['claims'])
        self.assertIn('can be imitated by a local program', result['attestation']['notClaimed'])
        self.assertEqual(result['attestation']['attestedBy'], 'TEST coordinator session')
        self.assertEqual(self.studio.requests.count('/__hyperframes_config'), identity_checks + 1)  # served again

    def files(self) -> dict[str, tuple[int, str]]:
        """Every file under the TEST roots (records, registry, authority, attempt and project): size and SHA-256."""
        roots = (self.root, Path(self.export), Path(self.project))
        return {str(file): (file.stat().st_size, digest(file)) for root in roots for file in sorted(root.rglob('*'))
                if file.is_file() and not file.is_symlink()}

    def hand_written(self, record: dict, playback: list[dict]) -> Path:
        """A confirmation written by hand in confirm's shape, claiming ``playback`` the review player never saw."""
        at, handoff_file = utc(), self.root / 'handoff.json'
        value = {'schemaVersion': 1, 'kind': 'native-visible-handoff-confirmation',
                 'handoff': {'path': str(handoff_file.resolve()), 'sha256': digest(handoff_file)},
                 'owner': record['owner'], 'viewToken': record['viewToken'],
                 'attestation': confirmation.attestation_for(record, self.pages(record)),
                 'observed': {'reviewPagePlayback': playback, 'mediaRequested': [], 'meaning': confirmation.PLAYBACK_MEANING},
                 'status': 'visible-handoff', 'failures': [], 'confirmedAt': at, 'visibleHandoffAt': at}
        file = self.root / 'HAND-confirmation.json'
        file.write_text(json.dumps(value))
        return file

    def test_verify_confirmation_rechecks_read_only_and_refuses_a_hand_written_confirmation(self) -> None:
        """A3's seam: a hand-written confirmation without the page's own playback is refused by name, before and after
        real playback; the real confirmation verifies, returns the stable summary and writes nothing."""
        record = handoff.hand_off(self.request())
        forged = [{'time': utc(), 'token': 'TEST-forged', 'event': 'playing', 'route': record['reviewPlayer']['route'],
                   'currentTime': 0.04, 'userAgent': 'TEST'}]
        hand = self.hand_written(record, forged)
        with self.assertRaises(ConfirmationRefused) as unplayed:
            confirmation.verify_confirmation(hand)
        self.assertEqual(unplayed.exception.code, 'REVIEW_PAGE_PLAYBACK_NOT_OBSERVED')
        self.assertEqual(self.page_playback(self.player_url, record['reviewPlayer']['route']), 204)
        with self.assertRaises(ConfirmationRefused) as invented:
            confirmation.verify_confirmation(hand)
        self.assertEqual(invented.exception.code, 'RECORDED_PLAYBACK_NOT_OBSERVED')
        result = self.confirmed(record)
        before = self.files()
        summary = confirmation.verify_confirmation(self.root / 'visible.json')
        self.assertEqual(self.files(), before)  # read only: no record, registry or project file changed
        self.assertEqual((summary['level'], summary['record']['sha256'], summary['mp4'], summary['visibleHandoffAt']),
                         ('visible-handoff', digest(self.root / 'visible.json'),
                          {key: record['output']['mp4'][key] for key in ('path', 'sha256')}, result['visibleHandoffAt']))
        self.assertEqual((summary['viewsVerifiedAt'], summary['handoff']['path'], summary['delivery']['path']),
                         (record['timestamps']['viewsVerifiedAt'], str((self.root / 'handoff.json').resolve()),
                          str(Path(record['attempt']) / 'delivery.json')))
        (self.root / 'handoff.json').write_text(json.dumps({**record, 'viewToken': 'TEST-other'}))
        with self.assertRaises(ConfirmationRefused) as changed:
            confirmation.verify_confirmation(self.root / 'visible.json')
        self.assertEqual(changed.exception.code, 'HANDOFF_RECORD_CHANGED')

    def test_a_failing_review_player_check_keeps_the_handoff_invisible(self) -> None:
        """Verifier scenario (review-handoff b3-probe): the player recheck runs and its failure is named."""
        record = self.views_ready()
        stopped = {'url': record['reviewPlayer']['url'], 'verified': False, 'reason': 'TEST review player is gone'}
        with mock.patch.object(confirmation.checks, 'player_row', return_value=stopped) as player:
            result = self.confirmed(record)
        self.assertEqual(player.call_count, 1)
        self.assertEqual((result['status'], result['visibleHandoffAt']), ('handoff-incomplete', None))
        self.assertEqual([row['code'] for row in result['failures']], ['REVIEW_PLAYER_NOT_VERIFIED_AT_CONFIRM'])

    def test_a_stopped_restarted_or_relabeled_player_is_not_the_verified_player(self) -> None:
        """Real player: stopped, then restarted on the same port (a new server), then a stale label."""
        record = self.views_ready()
        self.stop_player(self.players[self.player_url])
        stopped = self.confirmed(record, 'stopped.json')
        self.assertIn('no longer serves', stopped['failures'][0]['message'])
        self.serve_player([Attempt('Q1', 'TEST Q1', self.export)], port=record['reviewPlayer']['server']['port'])
        restarted = self.confirmed(record, 'restarted.json')
        self.assertIn('is not the server and row the hand-off verified', restarted['failures'][0]['message'])
        relabeled = {**record['reviewPlayer'], 'kind': 'unverified', 'label': 'TEST stale label'}
        with mock.patch.object(confirmation.checks, 'player_row', return_value=relabeled):
            stale = self.confirmed(record, 'stale.json')
        for result in (stopped, restarted, stale):
            self.assertEqual((result['status'], result['visibleHandoffAt']), ('handoff-incomplete', None))
            self.assertEqual([row['code'] for row in result['failures']], ['REVIEW_PLAYER_NOT_VERIFIED_AT_CONFIRM'])

    def test_studio_changes_after_views_ready_are_named(self) -> None:
        """A reused PID, a Studio no longer serving, or a project stamped later keeps the hand-off invisible."""
        record = self.views_ready()
        index = self.project / 'index.html'
        index.write_text(index.read_text().replace('<p>', '<p data-hf-id="hf-p-0">', 1))
        self.assertIn('PROJECT_CHANGED_SINCE_VIEWS_READY', [row['code'] for row in self.confirmed(record, 'a.json')['failures']])
        self.studio.claimed_dir = str(self.projects[1])
        self.assertIn('STUDIO_NOT_SERVED_AT_CONFIRM', [row['code'] for row in self.confirmed(record, 'b.json')['failures']])
        self.identities[self.studio.pid]['started'] = 'Wed Sep  9 12:00:00 2026'
        self.assertEqual([row['code'] for row in self.confirmed(record, 'c.json')['failures']][0],
                         'STUDIO_VIEW_CHANGED_SINCE_VIEWS_READY')

    def test_only_a_clean_views_ready_record_with_its_urls_can_be_confirmed(self) -> None:
        """Wrong pages, an incomplete record, a forged failures list or a blank attester are refused."""
        record = self.views_ready()
        review, _studio, browser, who = self.pages(record)
        with self.assertRaisesRegex(ValueError, 'attested pages'):
            confirm(Confirmation(self.root / 'handoff.json', self.root / 'v.json', (review, 'http://localhost:1/', browser, who)))
        with self.assertRaisesRegex(ValueError, 'attested-by'):
            confirm(Confirmation(self.root / 'handoff.json', self.root / 'v.json', (*self.pages(record)[:3], ' ')))
        forged = self.root / 'forged.json'
        forged.write_text(json.dumps({**record, 'failures': [{'code': 'TEST', 'message': 'TEST'}]}))
        with self.assertRaisesRegex(ValueError, 'no failures'):
            confirm(Confirmation(forged, self.root / 'v.json', self.pages(record)))
        self.assertFalse((self.root / 'v.json').exists())


if __name__ == '__main__':
    unittest.main()

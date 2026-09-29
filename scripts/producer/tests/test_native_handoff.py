"""Hand-off records: exact MP4, matching project identity, served Studio and named failures.

Fixture: ``_handoff_fixture.HandoffFixture`` (real checked TEST export and receipt reader, real
registry with inert identities, loopback fake Studio, real review player, TEST authority reader).
Nothing real is started or signalled; the SIGTERM test signals only this test process, while its
handler is installed.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import signal
import sys
import unittest
from unittest import mock

from _handoff_fixture import OWNER, HandoffFixture
from studio import managed_preview as managed
from studio import managed_preview_state as state
from studio import native_handoff as handoff
from studio import native_handoff_evidence as evidence
from studio import native_handoff_open as opening
from studio.native_runtime import digest, sniper_lock
from studio.review_player_inventory import CHECKED_LABEL, Attempt
from studio.studio_server import StudioServerError
from test_review_player import make_attempt


def run_main(argv: list[str]) -> tuple[int, dict]:
    """Run the CLI with ``argv``; return its exit code and printed JSON."""
    with mock.patch.object(sys, 'argv', ['native_handoff.py', *argv]), \
            contextlib.redirect_stdout(io.StringIO()) as printed:
        code = handoff.main()
    return code, json.loads(printed.getvalue())


class HandoffRecordTests(HandoffFixture, unittest.TestCase):
    """What a hand-off binds, and each condition that must fail visibly."""

    def test_views_ready_binds_exact_mp4_matching_project_studio_and_player(self) -> None:
        """Every server-side check held: views-ready, an intent file first, and no visible hand-off claimed."""
        record = handoff.hand_off(self.request())
        self.assertEqual((record['status'], record['failures']), ('views-ready', []))
        self.assertEqual(json.loads((self.root / 'handoff.json').read_text()), record)
        intent = json.loads((self.root / 'handoff.json.intent.json').read_text())
        self.assertEqual((intent['kind'], intent['viewToken']), ('native-visible-handoff-intent', record['viewToken']))
        output, project, studio = record['output'], record['project'], record['studio']
        self.assertEqual(output['mp4']['sha256'], digest(self.export / 'review.mp4'))
        self.assertEqual((output['reviewState'], output['label']), ('checked', CHECKED_LABEL))
        self.assertEqual(project['identityBeforeOpen'], project['identityAfterLoad'])
        self.assertEqual((studio['ownership'], studio['viewOwner'], studio['live']), ('launched-by-this-handoff', OWNER, True))
        self.assertTrue(studio['served']['verified'] and studio['cleanup']['launchedByThisHandoff'])
        self.assertEqual((studio['pid'], studio['media']['path']), (self.studio.pid, str(self.export / 'review.mp4')))
        self.assertIn(f'/api/projects/{self.project.name}/preview/comp/compositions/caption.html', self.studio.requests)
        self.assertEqual(record['reviewPlayer']['server']['pid'], os.getpid())
        self.assertEqual(record['content']['operatorApproval']['status'], 'not-supplied')
        self.assertIsNotNone(record['timestamps']['viewsVerifiedAt'])
        self.assertIsNone(record['timestamps']['visibleHandoffAt'])

    def test_studio_rewriting_the_delivered_project_is_a_visible_failure(self) -> None:
        """Fault batch Q5: Studio stamps ids on load and the receipts stop re-verifying; exit 2."""
        self.studio.rewrites = {'index.html'}
        code, record = run_main(['open', str(self.export), '--owner', OWNER, '--record', str(self.root / 'q5.json'),
                                 '--review-player', self.player_url, '--load-seconds', '10', '--wait-seconds', '10'])
        self.assertEqual(code, handoff.INCOMPLETE_EXIT)
        self.assertEqual(record, json.loads((self.root / 'q5.json').read_text()))
        self.assertEqual(self.codes(record), ['MP4_RECEIPTS_NOT_REVERIFIED_AFTER_LOAD', 'STUDIO_CHANGED_PROJECT'])
        self.assertIn('current authored project differs from supervised sources',
                      record['output']['receipts']['afterLoad']['reason'])
        self.assertEqual(record['reviewPlayer']['label'], record['output']['label'])

    def test_an_unpinned_composition_stamped_on_load_is_a_studio_change(self) -> None:
        """Studio stamps any composition it previews; one the delivery did not pin is still named."""
        extra = self.project / 'compositions/extra.html'
        extra.parent.mkdir()
        extra.write_text('<template><div data-composition-id="extra"><p>TEST extra</p></div></template>')
        self.studio.compositions = ['index.html', 'compositions/extra.html']
        self.studio.rewrites = {'compositions/extra.html'}
        record = handoff.hand_off(self.request())
        self.assertEqual((self.codes(record), record['project']['changedWhileServed']),
                         (['STUDIO_CHANGED_PROJECT'], ['compositions/extra.html']))

    def test_linked_files_and_folders_are_named_not_hashed_or_walked_through(self) -> None:
        """A symlink with the delivered bytes, or a linked folder, is not the delivered project."""
        pinned = self.project / 'hyperframes.json'
        copy = self.root / 'hyperframes-copy.json'
        copy.write_bytes(pinned.read_bytes())
        pinned.unlink()
        pinned.symlink_to(copy)
        (self.root / 'elsewhere').mkdir()
        (self.root / 'elsewhere/hidden.html').write_text('<p>TEST behind a link</p>')
        (self.project / 'linked').symlink_to(self.root / 'elsewhere')
        record = handoff.hand_off(self.request())
        self.assertIn('PROJECT_DIFFERS_FROM_DELIVERY', self.codes(record))
        files = record['project']['identityBeforeOpen']['files']
        self.assertEqual((files['hyperframes.json'], files['linked']), (evidence.NOT_REGULAR, evidence.LINKED_FOLDER))
        self.assertNotIn('linked/hidden.html', files)
        self.assertEqual(record['project']['differsFromDelivery'], ['hyperframes.json', 'linked'])

    def test_a_server_serving_another_project_is_not_the_matching_studio(self) -> None:
        """A live URL is not the hand-off: the answering process must serve this exact project."""
        self.studio.claimed_dir = str(self.projects[1])
        with mock.patch.object(state.os, 'kill') as stop:
            record = handoff.hand_off(self.request())
        stop.assert_not_called()
        self.assertEqual(self.codes(record), ['STUDIO_DID_NOT_SERVE_PROJECT'])

    def test_a_view_that_dies_or_loses_its_mp4_after_load_is_not_ready(self) -> None:
        """The record reads the view again: a dead process or a changed MP4 binding fails it."""
        self.studio.after_load = lambda: self.identities.pop(self.studio.pid)
        record = handoff.hand_off(self.request('dead.json'))
        self.assertEqual(self.codes(record), ['STUDIO_NOT_LIVE_AFTER_LOAD'])
        self.studio.after_load = lambda: (self.export / 'review.mp4').write_bytes(b'TEST replaced during load')
        record = handoff.hand_off(self.request('replaced.json'))
        self.assertIn('MP4_CHANGED_DURING_HANDOFF', self.codes(record))
        self.assertIn('the view is not bound to the current delivered MP4 bytes', [row['message'] for row in record['failures']])

    def test_review_player_must_serve_these_bytes_with_the_same_label(self) -> None:
        """No player, a player for other attempts, or a stale player label leaves the hand-off incomplete."""
        self.assertEqual(self.codes(handoff.hand_off(self.request('no.json', player=None))), ['REVIEW_PLAYER_NOT_VERIFIED'])
        other = make_attempt(self.root, 'Other', 'native-short-checked-for-review')
        record = handoff.hand_off(self.request('other.json', player=self.serve_player([Attempt('Other', 'T', other)])))
        self.assertIn('does not list this attempt', record['reviewPlayer']['reason'])
        stale = {'url': self.player_url, 'verified': True, 'reason': None, 'kind': 'draft', 'label': 'TEST stale'}
        with mock.patch.object(handoff.checks, 'player_row', return_value=stale):
            self.assertEqual(self.codes(handoff.hand_off(self.request('stale.json'))), ['REVIEW_PLAYER_LABEL_DIFFERS'])
        with self.assertRaisesRegex(ValueError, 'review player URL'):
            handoff.checks.player_port('http://example.test:8795/')

    def test_nothing_opens_for_changed_media_bad_findings_or_an_unsafe_record_path(self) -> None:
        """Refusals happen before any Studio view is launched or reused, and leave no record or intent."""
        (self.root / 'taken.json').write_text('{}')
        for fields, message in (({'record': self.root / 'taken.json'}, 'already exists'),
                                ({'record': self.project / 'h.json'}, 'outside')):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                handoff.hand_off(self.request(**fields))
        delivery = json.loads((self.export / 'delivery.json').read_text())
        (self.export / 'delivery.json').write_text(json.dumps({**delivery, 'openFindings': ['TEST not a finding']}))
        with self.assertRaisesRegex(ValueError, 'malformed open findings'):
            handoff.hand_off(self.request())
        (self.export / 'delivery.json').write_text(json.dumps(delivery))
        (self.export / 'review.mp4').write_bytes(b'TEST replaced after delivery')
        with self.assertRaisesRegex(ValueError, 'nothing deliverable to hand off: CHANGED'):
            handoff.hand_off(self.request())
        self.mocks[3].assert_not_called()
        self.assertEqual(sorted(path.name for path in self.root.glob('handoff.json*')), [])

    def test_open_failures_and_unreadable_view_state_still_write_a_record(self) -> None:
        """A busy lock or an unreadable view becomes a named row, never a missing record."""
        with mock.patch.object(managed, 'open_view', side_effect=sniper_lock.LockBusy('TEST maintenance lock held')):
            self.assertEqual(self.codes(handoff.hand_off(self.request('busy.json'))), ['STUDIO_NOT_OPENED'])
        with mock.patch.object(opening, 'view_state', side_effect=StudioServerError('TEST registry deadline')):
            self.assertEqual(self.codes(handoff.hand_off(self.request('unread.json'))), ['STUDIO_VIEW_STATE_UNREAD'])

    def test_an_interrupted_or_terminated_handoff_leaves_records_its_release_can_use(self) -> None:
        """KeyboardInterrupt or SIGTERM after the launch: the token is recorded and releases exactly that view."""
        with mock.patch.object(handoff.checks, 'studio_served', side_effect=KeyboardInterrupt), \
                self.assertRaises(KeyboardInterrupt):
            handoff.hand_off(self.request('cut.json'))
        cut = json.loads((self.root / 'cut.json').read_text())
        self.assertEqual((cut['status'], self.codes(cut)), ('handoff-interrupted', ['HANDOFF_INTERRUPTED']))
        with mock.patch.object(state.os, 'kill', side_effect=self.stop_signal) as stop:
            self.assertEqual(handoff.release([self.root / 'cut.json'], self.root / 'r1.json', 10.0)['status'], 'released')
        self.assertEqual(len(stop.call_args_list), 1)
        terminate = lambda *_args, **_kwargs: os.kill(os.getpid(), signal.SIGTERM)  # noqa: E731 (TEST signal)
        with mock.patch.object(handoff.checks, 'studio_served', side_effect=terminate), \
                self.assertRaises(handoff.HandoffTerminated):
            run_main(['open', str(self.export), '--owner', OWNER, '--record', str(self.root / 'term.json'),
                      '--review-player', self.player_url])
        term = json.loads((self.root / 'term.json').read_text())
        self.assertIn('SIGTERM', term['failures'][0]['message'])
        self.assertIs(signal.getsignal(signal.SIGTERM), signal.SIG_DFL)
        launched = self.studio.pid
        with mock.patch.object(state.os, 'kill', side_effect=self.stop_signal) as stop:
            handoff.release([self.root / 'term.json.intent.json'], self.root / 'r2.json', 10.0)
        self.assertEqual({call.args[0] for call in stop.call_args_list}, {launched})

    def test_capacity_refusal_is_recorded_and_stops_nothing(self) -> None:
        """A full registry is a named STUDIO_NOT_OPENED failure; every running view keeps running."""
        opened = [self.open(index) for index in range(managed.registry.MAX_MANAGED_PREVIEWS)]
        with mock.patch.object(state.os, 'kill') as stop:
            record = handoff.hand_off(self.request())
        stop.assert_not_called()
        self.assertEqual(self.codes(record), ['STUDIO_NOT_OPENED'])
        self.assertIn('limit of 6 views', record['failures'][0]['message'])
        self.assertTrue(all(view.pid in self.identities for view in opened))


if __name__ == '__main__':
    unittest.main()

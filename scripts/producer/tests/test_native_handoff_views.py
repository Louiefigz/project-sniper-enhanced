"""Hand-off ownership, holds, release and approved content.

Fixture: ``_handoff_fixture.HandoffFixture``. Views belong to the hand-off token that launched
them; reusers and the user hold them; nobody's view is stopped or replaced by another's hand-off.
Visible confirmation and its read-only verification: ``test_native_handoff_confirmation.py``.
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

from _handoff_fixture import OWNER, TITLE, WORDS, HandoffFixture
from studio import managed_preview as managed
from studio import managed_preview_registry as registry
from studio import managed_preview_state as state
from studio import native_handoff as handoff
from studio import review_player_inventory as inventory
from studio.native_runtime import digest
from studio.review_player_inventory import DRAFT_STATUS, Attempt
from test_review_player import FINDING


class HandoffOwnershipTests(HandoffFixture, unittest.TestCase):
    """Owned views are counted and released by token; nobody else's view is stopped or reused."""

    def test_unrelated_views_are_preserved_and_never_reused(self) -> None:
        """A user's view and another owner's view survive this hand-off and its release."""
        user = self.open(1)
        with mock.patch.object(managed, 'pick_free_port', return_value=3992):
            other, _launched = managed.open_view(str(self.projects[2]), registry.ViewOwner('batch-OTHER', 'c' * 32))
        with mock.patch.object(state.os, 'kill') as stop:
            record = handoff.hand_off(self.request())
        stop.assert_not_called()
        counted = handoff.owned.owned_views(OWNER)
        self.assertEqual(([row['project'] for row in counted['owned']], counted['otherActive']), ([str(self.project)], 2))
        with mock.patch.object(state.os, 'kill', side_effect=self.stop_signal) as stop:
            released = handoff.release([self.root / 'handoff.json'], self.root / 'release.json', 10.0)
        self.assertEqual({call.args[0] for call in stop.call_args_list}, {record['studio']['pid']})
        self.assertEqual((released['status'], released['otherActiveViewsUntouched']), ('released', 2))
        self.assertEqual(released['handoffs'][0]['sha256'], digest(self.root / 'handoff.json'))
        self.assertTrue(user.pid in self.identities and other.pid in self.identities)

    def test_a_stale_view_someone_else_launched_or_holds_is_refused_not_replaced(self) -> None:
        """The user's stale view, and the same tag's view another token still holds, are never stopped."""
        stock = self.launch('/stock/hyperframes/dist/cli.js', str(self.project), 3990, open_browser=False)
        managed.adopt_preview(str(self.project), stock)
        with mock.patch.object(state.os, 'kill') as stop:
            record = handoff.hand_off(self.request('user.json'))
        stop.assert_not_called()
        self.assertEqual(self.codes(record)[0], 'STUDIO_VIEW_OWNED_ELSEWHERE')
        with mock.patch.object(state.os, 'kill', side_effect=self.stop_signal):
            managed.stop_preview(str(self.project))
            first = handoff.hand_off(self.request('first.json'))
        self.mocks[6].return_value = self.checkout_runtime('checkout-a', 'TEST-identity-b')
        with mock.patch.object(state.os, 'kill') as stop:
            second = handoff.hand_off(self.request('second.json'))
        stop.assert_not_called()
        self.assertIn('STUDIO_VIEW_OWNED_ELSEWHERE', second['failures'][0]['message'])
        with mock.patch.object(state.os, 'kill', side_effect=self.stop_signal) as stop:
            handoff.release([self.root / 'first.json'], self.root / 'release.json', 10.0)
            third = handoff.hand_off(self.request('third.json'))
        self.assertEqual({call.args[0] for call in stop.call_args_list}, {first['studio']['pid']})
        self.assertEqual((third['status'], third['studio']['ownership']), ('views-ready', 'launched-by-this-handoff'))

    def test_a_view_another_handoff_or_the_user_holds_is_kept(self) -> None:
        """The launcher's release keeps a view a reuser or the user still holds; the last hand-off holder stops it."""
        first = handoff.hand_off(self.request('first.json'))
        second = handoff.hand_off(self.request('second.json', owner='batch-test:Q1-recheck'))
        self.assertEqual(second['studio']['ownership'], 'reused-and-held-by-this-handoff')
        with mock.patch.object(state.os, 'kill') as stop:
            kept = handoff.release([self.root / 'first.json'], self.root / 'release-1.json', 10.0)
        stop.assert_not_called()
        self.assertEqual([row['owner'] for row in kept['views'][0]['stillHeldBy']], ['batch-test:Q1-recheck'])
        managed.open_preview(str(self.project))  # the user opens the same view: a user hold
        with mock.patch.object(state.os, 'kill') as stop:
            held = handoff.release([self.root / 'second.json'], self.root / 'release-2.json', 10.0)
        stop.assert_not_called()
        self.assertEqual(held['views'][0]['stillHeldBy'][0]['user'], True)
        self.assertIn(first['studio']['pid'], self.identities)

    def test_lost_holds_are_capped_named_and_pruned_by_their_evidence(self) -> None:
        """A full hold list refuses with the recovery named; prune-holds drops only holds whose evidence is gone."""
        record = handoff.hand_off(self.request())
        lost = [{'owner': 'batch-LOST', 'token': f'{index:032x}', 'evidence': [str(self.root / f'gone-{index}.json')]}
                for index in range(registry.MAX_HOLDS - 1)]
        with registry.transaction(registry.monotonic_until(10)) as reg:
            entry = registry.read_entry(reg, str(self.project))
            registry.write_entry(reg, dict(entry, heldBy=[*entry['heldBy'], *lost]))
        refused = handoff.hand_off(self.request('full.json', owner='batch-test:Q1-recheck'))
        self.assertEqual(self.codes(refused), ['STUDIO_NOT_OPENED'])
        self.assertIn('prune-holds', refused['failures'][0]['message'])
        pruned = handoff.prune(self.project, self.root / 'prune.json', 10.0)
        self.assertEqual((len(pruned['dropped']), [row['token'] for row in pruned['kept']]),
                         (registry.MAX_HOLDS - 1, [record['viewToken']]))
        self.assertEqual(handoff.hand_off(self.request('after.json', owner='batch-test:Q1-recheck'))['status'], 'views-ready')

    def test_a_refused_open_changes_nothing_of_the_holders_record(self) -> None:
        """Operator item #5: a full hold list refuses an open with another MP4 before any write; the other holders'
        binding and holds stay byte-for-byte as they were (hand-off and unowned bundle opens alike)."""
        handoff.hand_off(self.request())
        lost = [{'owner': 'batch-LOST', 'token': f'{index:032x}', 'evidence': [str(self.root / f'gone-{index}.json')]}
                for index in range(registry.MAX_HOLDS - 1)]
        with registry.transaction(registry.monotonic_until(10)) as reg:
            entry = registry.read_entry(reg, str(self.project))
            registry.write_entry(reg, dict(entry, heldBy=[*entry['heldBy'], *lost]))
            before = registry.read_entry(reg, str(self.project))
        other = self.root / 'TEST-other-review.mp4'
        other.write_bytes(b'TEST other review bytes')
        for owner in (registry.ViewOwner('batch-test:Q1-recheck', 'e' * 32, (str(self.root / 'e.json'),)), None):
            with self.subTest(owner=owner), self.assertRaisesRegex(managed.StudioServerError, 'holds'):
                managed.open_view(str(self.project), owner, other, 10.0)
            with registry.transaction(registry.monotonic_until(10)) as reg:
                self.assertEqual(registry.read_entry(reg, str(self.project)), before)

    def test_a_46a7420_record_is_a_legacy_view_not_a_broken_registry(self) -> None:
        """An owner tag without a token reads as unowned legacy; no token release stops it."""
        legacy = self.open(1)
        with registry.transaction(registry.monotonic_until(10)) as reg:
            entry = registry.read_entry(reg, str(self.projects[1]))
            registry.write_entry(reg, dict(entry, owner=OWNER))
        record = handoff.hand_off(self.request())
        with mock.patch.object(state.os, 'kill', side_effect=self.stop_signal):
            released = handoff.release([self.root / 'handoff.json'], self.root / 'release.json', 10.0)
        self.assertEqual((record['status'], released['otherActiveViewsUntouched']), ('views-ready', 1))
        self.assertIn(legacy.pid, self.identities)

    def test_two_batches_with_the_same_tag_cannot_release_each_others_views(self) -> None:
        """Release is bound to each hand-off's token, not to its reusable tag."""
        draft = self.draft_short('Other')
        self.enterContext(mock.patch.dict(inventory.RECEIPT_READERS, {DRAFT_STATUS: lambda export: None}))
        mine = handoff.hand_off(self.request('mine.json'))
        with mock.patch.object(managed, 'pick_free_port', return_value=3993):
            theirs = handoff.hand_off(self.request('theirs.json', attempt=draft, player=None))
        with mock.patch.object(state.os, 'kill', side_effect=self.stop_signal) as stop:
            handoff.release([self.root / 'mine.json'], self.root / 'release.json', 10.0)
        self.assertEqual({call.args[0] for call in stop.call_args_list}, {mine['studio']['pid']})
        self.assertIn(theirs['studio']['pid'], self.identities)


class ApprovedContentTests(HandoffFixture, unittest.TestCase):
    """approved-content-production-2026-09-27: read from the batch authority, compared exactly, apart from review."""

    def setUp(self) -> None:
        """A TEST draft whose plan stages a title and kept words; its receipt reader is patched to pass."""
        super().setUp()
        self.draft = self.draft_short('Draft', openFindings=[FINDING], editorialReview='pending')
        self.enterContext(mock.patch.dict(inventory.RECEIPT_READERS, {DRAFT_STATUS: lambda export: None}))
        self.url = self.serve_player([Attempt('Draft', 'TEST draft', self.draft)])
        self.draft_project = self.root / 'Draft-project'

    def hand_off_draft(self, name: str = 'draft.json') -> dict:
        """One hand-off of the TEST draft."""
        return handoff.hand_off(self.request(name, attempt=self.draft, player=self.url))

    def test_the_authority_approval_is_carried_and_kept_apart_from_execution_review(self) -> None:
        """Exact title, source, ordered words and texts, clip and batch match; humanApproved speaks only for the render."""
        self.approve(self.draft_project)
        record = self.hand_off_draft()
        self.assertEqual((record['status'], record['failures']), ('views-ready', []))
        content = record['content']
        self.assertEqual([content[key] for key in ('title', 'sourceMatchesApproval', 'wordsMatchApproval',
                                                   'wordTextsMatchApproval', 'clipMatchesApproval')],
                         ['exact', True, True, True, True])
        self.assertEqual((content['operatorApproval']['status'], content['operatorApproval']['readFrom']),
                         ('supplied', 'studio.production.api.read_approval'))
        review = record['output']['executionReview']
        self.assertEqual((review['editorialReview'], review['humanApprovedRenderedOutput']), ('pending', False))
        self.assertEqual((record['output']['reviewState'], record['output']['openFindings']), ('draft', [FINDING]))

    def test_order_text_and_title_changes_are_reported_not_repaired(self) -> None:
        """Same words in another order, a same-timing word change and a different title each fail; nothing is edited."""
        before = (self.draft_project / 'SHORT-PROJECT.json').read_bytes()
        cases = {'order': {'wordRanges': [[20, 21], [10, 11]], 'wordTexts': ['say,', 'hey.', 'People', 'always']},
                 'text': {'wordTexts': ['People', 'always', 'say,', 'TEST-hey.']},
                 'title': {'title': 'TEST a different approved title'}}
        expected = {'order': 'wordsMatchApproval', 'text': 'wordTextsMatchApproval', 'title': 'titleMatchesApproval'}
        for name, fields in cases.items():
            self.approve(self.draft_project, **fields)
            record = self.hand_off_draft(f'{name}.json')
            with self.subTest(case=name):
                self.assertEqual(self.codes(record), ['APPROVED_CONTENT_DIFFERS_FROM_BUILD'])
                self.assertIn(expected[name], record['failures'][0]['message'])
                self.assertEqual(record['content']['sameWordsOtherOrder'], name == 'order')
        self.assertEqual((self.draft_project / 'SHORT-PROJECT.json').read_bytes(), before)

    def test_normalization_only_titles_and_built_in_title_cards_follow_the_shared_rules(self) -> None:
        """Whitespace-only title differences are reported, not material; a canvas.titleCard title is read."""
        self.approve(self.draft_project, title=f'  {TITLE}  ')
        record = self.hand_off_draft()
        self.assertEqual((record['status'], record['content']['title']), ('views-ready', 'normalization-only'))
        card = self.draft_short('Card', title_holder='titleCard')
        self.approve(self.root / 'Card-project')
        record = handoff.hand_off(self.request('card.json', attempt=card, player=self.serve_player(
            [Attempt('Card', 'TEST card', card)])))
        self.assertEqual((record['content']['built']['title'], record['content']['title']), (TITLE, 'exact'))
        self.assertEqual(record['content']['built']['words'], [index for index, _text in WORDS])

    def test_a_caption_correction_on_an_approved_word_stays_matching_and_is_listed(self) -> None:
        """The approved script is the spoken words: a display correction is listed, never a mismatch."""
        correction = {'occurrenceId': 2, 'expectedSourceText': 'say,', 'displayText': 'says:',
                      'reason': 'TEST the speaker says "says"; ASR heard "say,"'}
        corrected = self.draft_short('Corrected', corrections=[correction])
        self.approve(self.root / 'Corrected-project')
        player = self.serve_player([Attempt('Corrected', 'TEST corrected', corrected)])
        record = handoff.hand_off(self.request('corrected.json', attempt=corrected, player=player))
        self.assertEqual((record['status'], record['failures']), ('views-ready', []))
        self.assertTrue(record['content']['wordTextsMatchApproval'] and record['content']['wordsMatchApproval'])
        self.assertEqual(record['content']['displayCorrections'], [
            {'occurrenceId': 2, 'sourceWord': 20, 'sourceText': 'say,', 'expectedSourceText': 'say,',
             'displayText': 'says:', 'reason': correction['reason']}])

    def test_an_export_naming_a_batch_clip_needs_the_folder_binding(self) -> None:
        """Probe p17: an export whose productionBudget names batch-test/Q1 is read by that name; a folder the batch does
        not bind (or binds to another clip) is APPROVAL_BINDING_MISSING, never 'unknown'."""
        record = self.hand_off_draft('unbound.json')
        self.assertEqual(self.codes(record), ['APPROVAL_BINDING_MISSING'])
        self.assertIn("names batch batch-test clip Q1, whose approval cannot be read", record['failures'][0]['message'])
        other = self.draft_short('Other')
        self.approve(self.root / 'Other-project')
        record = self.hand_off_draft('elsewhere.json')
        self.assertEqual(self.codes(record), ['APPROVAL_BINDING_MISSING'])
        self.assertIn('no batch binds this project folder', record['content']['approvalBinding']['problem'])
        self.assertEqual(record['content']['operatorApproval']['readFrom'], 'studio.production.api.read_approval')
        self.assertTrue(other.is_dir())

    def test_display_corrections_beyond_the_cap_are_counted_not_dropped(self) -> None:
        """P-B: 130 accepted corrections list the first 128 and count the other 2 in displayCorrectionsOmitted."""
        from studio import native_handoff_content as content
        rows = [{'occurrenceId': index % 4, 'expectedSourceText': 'TEST', 'displayText': f'TEST {index}',
                 'reason': 'TEST display spelling'} for index in range(130)]
        plan = {'canvas': {'occurrences': [[0, 0, 10, 0, 10, 'People', 0]], 'captionCorrections': rows}, 'assets': []}
        shown = content.planned(plan)
        self.assertEqual((len(shown['displayCorrections']), shown['displayCorrectionsOmitted']), (128, 2))

    def test_the_hold_of_an_ended_hand_off_is_prunable(self) -> None:
        """P-C: a hand-off that ended handoff-incomplete keeps no hold, though its intent file still names its token;
        a views-ready hand-off's hold stays."""
        ended = self.hand_off_draft('ended.json')
        self.assertEqual(ended['status'], 'handoff-incomplete')
        self.approve(self.draft_project)
        ready = self.hand_off_draft('ready.json')
        self.assertEqual(ready['status'], 'views-ready')
        pruned = handoff.prune(self.draft_project, self.root / 'prune-ended.json', 10.0)
        self.assertEqual([row['token'] for row in pruned['dropped']], [ended['viewToken']])
        self.assertEqual([row['token'] for row in pruned['kept']], [ready['viewToken']])

    def test_an_export_that_names_no_batch_is_unknown_not_refused(self) -> None:
        """Without a productionBudget and without a folder binding, approval is recorded as not-supplied (unknown)."""
        request = json.loads((self.draft / 'export-request.json').read_text())
        del request['productionBudget']
        (self.draft / 'export-request.json').write_text(json.dumps(request))
        record = self.hand_off_draft('unnamed.json')
        self.assertEqual((record['status'], record['content']['operatorApproval']['status']), ('views-ready', 'not-supplied'))
        self.assertEqual(record['content']['wordsMatchApproval'], None)

    def test_cut_seconds_and_the_transcript_are_compared_with_the_approval(self) -> None:
        """Probes p12/p12b: the same words with shifted cut seconds, or another transcript, differ from the approval."""
        for name, fields, key in (('seconds', {'ranges': [[1.1, 2.0], [3.0, 4.5]]}, 'secondsMatchApproval'),
                                  ('transcript', {'transcript': 'd' * 64}, 'transcriptMatchesApproval')):
            self.approve(self.draft_project, **fields)
            record = self.hand_off_draft(f'{name}.json')
            with self.subTest(name):
                self.assertEqual(self.codes(record), ['APPROVED_CONTENT_DIFFERS_FROM_BUILD'])
                self.assertIn(key, record['failures'][0]['message'])
                self.assertTrue(record['content']['wordsMatchApproval'] and record['content']['wordTextsMatchApproval'])

if __name__ == '__main__':
    unittest.main()

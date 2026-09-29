"""Local review player: honest status labels, exact read-only bytes and loopback-only serving."""
from __future__ import annotations
import base64
import hashlib
import http.client
import json
import os
import re
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_native_review_admission as admission
from studio import review_player_inventory as inventory
from studio.review_player import ReviewPlayer
from studio.review_player_inventory import DRAFT_STATUS, Attempt, Evaluator, read_attempts
from studio.native_runtime import digest

FINAL = 'native-short-checked-for-review'
FINDING = {'code': 'TEST_TITLE_EXIT', 'severity': 'major', 'lane': 'motion', 'message': 'TEST title exit unreviewed',
           'requiredAction': 'TEST review the exit', 'source': 'prebuild-review'}


def make_attempt(base: Path, name: str, status: str, **fields: object) -> Path:
    """A TEST attempt folder with a pinned plan, placeholder MP4 bytes and a delivery record."""
    root, project = base / name, base / f'{name}-project'
    root.mkdir(); project.mkdir()
    plan = project / 'SHORT-PROJECT.json'
    plan.write_text(json.dumps({'canvas': {'frameRate': '25/1', 'totalFrames': 50,
                                           'segments': [{'startFrame': 0, 'endFrameExclusive': 50}]}}))
    output = root / ('review-draft.mp4' if status == DRAFT_STATUS else 'review.mp4')
    output.write_bytes(bytes(range(256)) * 40)
    (root / 'export-request.json').write_text(json.dumps({'project': str(project), 'output': str(root),
                                                          'pins': {str(plan): digest(plan)}}))
    decode = {'playability': {'fullAudioVideoDecodePassed': True}} if status == DRAFT_STATUS \
        else {'fullAudioVideoDecodePassed': True}
    (root / 'delivery.json').write_text(json.dumps({'status': status, 'output': str(output), 'sha256': digest(output),
                                                    'humanApproved': False, **decode, **fields}))
    return root


class PlayerLabelTests(unittest.TestCase):
    """Every state is listed; only exact recorded bytes play; a re-verified checked MP4 is never called final."""

    def setUp(self) -> None:
        """Isolated TEST attempts under a canonical temporary folder."""
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp')))

    def evaluate(self, name: str) -> dict:
        """Label one attempt with fresh caches."""
        return Evaluator().evaluate(Attempt(name, f'TEST {name}', self.base / name))

    def test_checked_requires_receipts_that_verify_now_and_is_never_editor_approved(self) -> None:
        """CHECKED requires receipts that verify now and never presents a technical pass as an approved final."""
        make_attempt(self.base, 'good', FINAL, audioReviewRequired=True)
        with mock.patch.dict(inventory.RECEIPT_READERS, {FINAL: lambda export: None}):
            row = self.evaluate('good')
        self.assertEqual((row['kind'], row['label'], row['playable']), ('checked', inventory.CHECKED_LABEL, True))
        self.assertIn('editorial approval: see native-review.ts check-final', row['label'])
        self.assertNotIn('FINAL', row['label'])
        self.assertEqual(row['durationSeconds'], 2.0)
        self.assertIn('Audio listening review required.', row['notes'])
        def refuse(export: Path) -> None:
            """A TEST receipt reader that finds a changed input."""
            raise ValueError('TEST changed input')
        with mock.patch.dict(inventory.RECEIPT_READERS, {FINAL: refuse}):
            row = self.evaluate('good')
        self.assertEqual(row['kind'], 'unverified')
        self.assertTrue(row['playable'])
        self.assertNotIn('CHECKED FOR REVIEW', row['label'])
        self.assertIn('Receipts: ValueError: TEST changed input', row['notes'])
        malformed = mock.Mock(side_effect=AttributeError("TEST 'NoneType' object has no attribute 'get'"))
        with mock.patch.dict(inventory.RECEIPT_READERS, {FINAL: malformed}):
            self.assertEqual(self.evaluate('good')['kind'], 'unverified')

    def test_a_receipt_refusal_is_read_again_not_cached(self) -> None:
        """One long-lived evaluator: a refusal is never reused, so a later pass is shown as it is."""
        make_attempt(self.base, 'flaky', FINAL)
        evaluator, attempt = Evaluator(), Attempt('flaky', 'TEST flaky', self.base / 'flaky')
        outcomes = [ValueError('TEST refusal'), None, ValueError('TEST not reached: a pass is cached')]
        def reader(export: Path) -> None:
            """Refuse once, then pass."""
            outcome = outcomes.pop(0)
            if outcome:
                raise outcome
        with mock.patch.dict(inventory.RECEIPT_READERS, {FINAL: reader}):
            self.assertEqual([evaluator.evaluate(attempt)['kind'] for _ in range(3)], ['unverified', 'checked', 'checked'])
        self.assertEqual(len(outcomes), 1)

    def test_drafts_show_findings_and_are_never_final(self) -> None:
        """Drafts show findings and are never final."""
        make_attempt(self.base, 'draft', DRAFT_STATUS, openFindings=[FINDING], label='TEST REVIEW DRAFT label')
        make_attempt(self.base, 'pending', DRAFT_STATUS, openFindings=[])
        row = self.evaluate('draft')
        self.assertEqual((row['kind'], row['playable']), ('draft', True))
        self.assertEqual(row['label'], 'REVIEW DRAFT — open findings (1) (receipts not re-verified)')
        self.assertEqual(row['findings'][0]['code'], 'TEST_TITLE_EXIT')
        self.assertIn('TEST REVIEW DRAFT label', row['notes'])
        with mock.patch.dict(inventory.RECEIPT_READERS, {DRAFT_STATUS: lambda export: None}):
            self.assertEqual(self.evaluate('draft')['label'], 'REVIEW DRAFT — open findings (1)')
            self.assertEqual(self.evaluate('pending')['label'], 'REVIEW DRAFT — editorial review pending')

    def test_undelivered_changed_and_unsafe_attempts_are_listed_not_served(self) -> None:
        """Undelivered changed and unsafe attempts are listed not served."""
        make_attempt(self.base, 'failed', 'failed', failureCategory='renderer-failure', error='TEST crash')
        make_attempt(self.base, 'preview', 'native-motion-previews-complete')
        make_attempt(self.base, 'awaiting', 'native-short-rendered-awaiting-qc')
        make_attempt(self.base, 'unknown', 'native-short-something-new')
        make_attempt(self.base, 'undecoded', FINAL, fullAudioVideoDecodePassed=False)
        changed = make_attempt(self.base, 'changed', FINAL); (changed / 'review.mp4').write_bytes(b'TEST replaced')
        running = make_attempt(self.base, 'running', FINAL); (running / 'delivery.json').unlink()
        elsewhere = make_attempt(self.base, 'elsewhere', FINAL)
        record = json.loads((elsewhere / 'delivery.json').read_text())
        (elsewhere / 'delivery.json').write_text(json.dumps({**record, 'output': str(self.base / 'other.mp4')}))
        linked = make_attempt(self.base, 'linked', FINAL)
        (linked / 'review.mp4').rename(linked / 'actual.mp4'); (linked / 'review.mp4').symlink_to(linked / 'actual.mp4')
        expected = {'failed': 'FAILED', 'preview': 'PREVIEW EXCERPTS ONLY', 'awaiting': 'RENDERED, AWAITING QC',
                    'unknown': 'UNRECOGNIZED STATUS', 'undecoded': 'NOT PLAYABLE', 'changed': 'CHANGED',
                    'running': 'IN PROGRESS', 'elsewhere': 'NOT PLAYABLE', 'linked': 'UNREADABLE', 'absent': 'NOT STARTED'}
        for name, text in expected.items():
            row = self.evaluate(name)
            with self.subTest(name=name):
                self.assertTrue(row['label'].startswith(text), row['label'])
                self.assertEqual((row['kind'], row['playable']), ('blocked', False))
        self.assertIn('TEST crash', self.evaluate('failed')['detail'])

    def test_manifest_and_attempt_arguments_fail_closed(self) -> None:
        """Manifest and attempt arguments fail closed."""
        folder = make_attempt(self.base, 'one', FINAL)
        manifest = self.base / 'manifest.json'
        manifest.write_text(json.dumps({'schemaVersion': 1, 'compositions': [
            {'id': 'One', 'title': 'TEST title', 'export': str(folder)}]}))
        rows = read_attempts(manifest, [f'Missing={self.base / "later"}'])
        self.assertEqual([(row.identity, row.title) for row in rows], [('One', 'TEST title'), ('Missing', 'Missing')])
        (self.base / 'alias').symlink_to(folder)
        bad = [[f'one={folder}', f'ONE={self.base / "x"}'], [f'two={folder}', f'three={folder}'], ['relative=one'],
               [f'1bad={folder}'], [str(folder)], [f'alias={self.base / "alias"}'], [f'dots={self.base}/x/../one'], []]
        for pairs in bad:
            with self.subTest(pairs=pairs), self.assertRaises(ValueError):
                read_attempts(None, pairs)
        manifest.write_text(json.dumps({'schemaVersion': 2, 'compositions': []}))
        with self.assertRaises(ValueError):
            read_attempts(manifest, [])


class PlayerReceiptTests(unittest.TestCase):
    """The real maintained receipt reader decides CHECKED; a second hard link withdraws it."""

    def test_real_receipts_label_checked_until_a_hard_link_appears(self) -> None:
        """Real receipts label a checked MP4 (never an approved final) until a hard link appears."""
        helper = admission.NativeReviewAdmissionTests('test_original_and_resumed_checked_exports_admit')
        helper.setUp(); self.addCleanup(helper.doCleanups)
        attempt = Attempt('Checked', 'TEST checked export', helper.f.root)
        row = Evaluator().evaluate(attempt)
        self.assertEqual((row['kind'], row['label'], row['playable']), ('checked', inventory.CHECKED_LABEL, True))
        os.link(helper.f.root / 'review.mp4', helper.f.base / 'TEST-dropin-copy.mp4')
        row = Evaluator().evaluate(attempt)
        self.assertEqual((row['kind'], row['playable']), ('unverified', True))
        self.assertIn('unsafe', row['receipts']['reason'])
        self.assertTrue(any('2 hard links' in note for note in row['notes']))

    def test_a_project_rewritten_after_the_first_check_is_no_longer_checked(self) -> None:
        """One long-lived evaluator (a serving player) re-reads receipts once Studio rewrote the project."""
        helper = admission.NativeReviewAdmissionTests('test_original_and_resumed_checked_exports_admit')
        helper.setUp(); self.addCleanup(helper.doCleanups)
        evaluator, attempt = Evaluator(), Attempt('Checked', 'TEST checked export', helper.f.root)
        self.assertEqual(evaluator.evaluate(attempt)['kind'], 'checked')
        index = helper.f.project / 'index.html'
        index.write_text(index.read_text().replace('<p>', '<p data-hf-id="hf-p-0">', 1))
        row = evaluator.evaluate(attempt)
        self.assertEqual((row['kind'], row['playable']), ('unverified', True))
        self.assertIn('current authored project differs from supervised sources', row['receipts']['reason'])


class PlayerServerTests(unittest.TestCase):
    """Real loopback sockets: page, range seeking, refusals and untouched media."""

    def setUp(self) -> None:
        """Serve one re-verified checked export, one draft and one failed TEST attempt on an ephemeral port."""
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp')))
        make_attempt(self.base, 'Final', FINAL)
        make_attempt(self.base, 'Draft', DRAFT_STATUS, openFindings=[FINDING])
        make_attempt(self.base, 'Failed', 'failed', error='TEST crash')
        self.enterContext(mock.patch.dict(inventory.RECEIPT_READERS, {FINAL: lambda export: None}))
        attempts = [Attempt(name, f'TEST <{name}>', self.base / name) for name in ('Final', 'Draft', 'Failed')]
        self.server = ReviewPlayer(attempts, 0)
        self.port = self.server.server_address[1]
        thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close); self.addCleanup(self.server.shutdown)
        self.video = self.base / 'Final/review.mp4'

    def request(self, method: str, path: str, headers: dict | None = None,
                body: bytes | None = None) -> tuple[int, dict, bytes]:
        """One request on a fresh loopback connection."""
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        self.addCleanup(connection.close)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()

    def test_page_labels_and_policy_forbid_every_network_origin(self) -> None:
        """Page labels and policy forbid every network origin."""
        self.assertEqual(self.server.server_address[0], '127.0.0.1')
        status, headers, body = self.request('GET', '/')
        page = body.decode()
        self.assertEqual(status, 200)
        for text in (inventory.CHECKED_LABEL, 'REVIEW DRAFT — open findings (1)', 'FAILED — no complete MP4',
                     '1 checked for review', 'This page does not read editorial reviews',
                     'TEST_TITLE_EXIT', 'TEST &lt;Final&gt;', 'src="/media/Final.mp4"', 'class SelectionPlayback'):
            self.assertIn(text, page)
        self.assertNotIn('/media/Failed.mp4', page)
        self.assertNotRegex(page, r'https?://')
        policy = headers['Content-Security-Policy']
        self.assertTrue(policy.startswith("default-src 'none'; media-src 'self';"))
        script = re.search(r'<script>(.*)</script>', page, re.S)[1]
        self.assertIn("'sha256-" + base64.b64encode(hashlib.sha256(script.encode()).digest()).decode() + "'", policy)
        self.assertEqual(headers['Cache-Control'], 'no-store')

    def test_inventory_json_lists_the_page_labels_and_exact_bytes(self) -> None:
        """The hand-off reads the same labels and hashes as JSON; nothing else is exposed."""
        status, headers, body = self.request('GET', '/inventory.json')
        self.assertEqual((status, headers['Content-Type']), (200, 'application/json'))
        document = json.loads(body)
        rows = {row['id']: row for row in document['attempts']}
        self.assertEqual(set(rows), {'Final', 'Draft', 'Failed'})
        self.assertEqual(set(rows['Final']), {'id', 'title', 'export', 'kind', 'label', 'playable', 'sha256', 'bytes',
                                              'route', 'receipts', 'findings'})
        self.assertEqual((rows['Final']['label'], rows['Final']['sha256']), (inventory.CHECKED_LABEL, digest(self.video)))
        self.assertEqual((rows['Draft']['kind'], rows['Draft']['findings'][0]['code']), ('draft', 'TEST_TITLE_EXIT'))
        self.assertEqual((rows['Failed']['playable'], rows['Failed']['sha256']), (False, None))
        self.assertEqual(self.request('GET', '/inventory.json', {'Host': f'attacker.test:{self.port}'})[0], 403)

    def test_single_byte_ranges_seek_exact_bytes(self) -> None:
        """Single byte ranges seek exact bytes."""
        data, size = self.video.read_bytes(), self.video.stat().st_size
        cases = {'bytes=0-9': (0, 9), 'bytes=100-': (100, size - 1), 'bytes=-5': (size - 5, size - 1),
                 f'bytes=0-{size * 2}': (0, size - 1)}
        for value, (start, end) in cases.items():
            status, headers, body = self.request('GET', '/media/Final.mp4', {'Range': value})
            with self.subTest(value=value):
                self.assertEqual((status, body), (206, data[start:end + 1]))
                self.assertEqual(headers['Content-Range'], f'bytes {start}-{end}/{size}')
        status, headers, body = self.request('GET', '/media/Final.mp4')
        self.assertEqual((status, body, headers['Accept-Ranges']), (200, data, 'bytes'))
        status, headers, body = self.request('HEAD', '/media/Draft.mp4')
        self.assertEqual((status, body, headers['Content-Length']), (200, b'', str(size)))
        for value in (f'bytes={size}-', 'bytes=5-2', 'bytes=0-1,4-5', 'items=0-1', 'bytes=-0', 'bytes=-'):
            status, headers, _body = self.request('GET', '/media/Final.mp4', {'Range': value})
            with self.subTest(value=value):
                self.assertEqual((status, headers['Content-Range']), (416, f'bytes */{size}'))

    def test_paths_methods_and_foreign_hosts_refuse(self) -> None:
        """Paths methods and foreign hosts refuse."""
        refusals = [('GET', '/media/Failed.mp4', None, 404), ('GET', '/media/../Final/review.mp4', None, 404),
                    ('GET', '/Final/review.mp4', None, 404), ('GET', '/?clip=Final', None, 404),
                    ('GET', f'http://127.0.0.1:{self.port}/', None, 404), ('POST', '/', None, 403), ('POST', '/activity', None, 403),
                    ('DELETE', '/media/Final.mp4', None, 405), ('GET', '/', {'Host': f'attacker.test:{self.port}'}, 403),
                    ('GET', '/media/Final.mp4', {'Host': 'localhost:1'}, 403)]
        for method, path, headers, code in refusals:
            with self.subTest(method=method, path=path, headers=headers):
                self.assertEqual(self.request(method, path, headers)[0], code)
        self.assertEqual(self.request('GET', '/', {'Host': f'localhost:{self.port}'})[0], 200)

    def post_report(self, body: object, origin: str | None = None) -> int:
        """One page playback report on a fresh loopback connection (the page script's own POST)."""
        headers = {'Content-Type': 'application/json', 'Origin': origin or f'http://127.0.0.1:{self.port}',
                   'User-Agent': 'Mozilla/5.0 TEST page'}
        return self.request('POST', '/activity', {**headers, 'Content-Length': str(len(json.dumps(body)))},
                            json.dumps(body).encode())[0]

    def test_activity_is_kept_per_attempt_and_only_the_pages_own_reports_count(self) -> None:
        """P-A: per-attempt logs without 404s or favicon; item #4: a report needs a page token, this origin and the
        attempt's own route, and is recorded apart from media requests."""
        _status, _headers, body = self.request('GET', '/')
        token = body.decode().split('data-page-token="', 1)[1].split('"', 1)[0]
        for path in ('/favicon.ico', '/media/Failed.mp4', '/media/Final.mp4'):
            self.request('GET', path, {'User-Agent': 'curl/8.7.1'})
        good = {'token': token, 'attempt': 'Final', 'route': '/media/Final.mp4', 'event': 'playing', 'currentTime': 0.5}
        refused = [({**good, 'token': 'f' * 32}, None, 400), ({**good, 'route': '/media/Draft.mp4'}, None, 400),
                   ({**good, 'attempt': 'Failed', 'route': '/media/Failed.mp4'}, None, 400), ({**good, 'event': 'seeked'}, None, 400),
                   ({**good, 'extra': 1}, None, 400), (good, 'http://attacker.test', 403)]
        for body, origin, code in refused:
            with self.subTest(body=body, origin=origin):
                self.assertEqual(self.post_report(body, origin), code)
        self.assertEqual(self.post_report(good), 204)
        activity = json.loads(self.request('GET', '/inventory.json')[2])['activity']
        self.assertEqual(set(activity['attempts']), {'Final'})
        final = activity['attempts']['Final']
        self.assertEqual([(row['path'], row['userAgent']) for row in final['mediaRequests']],
                         [('/media/Final.mp4', 'curl/8.7.1')])
        self.assertEqual([(row['event'], row['token'], row['currentTime']) for row in final['playback']], [('playing', token, 0.5)])
        self.assertEqual([page['token'] for page in activity['pages']], [token])

    def test_media_is_never_modified_and_changed_bytes_stop_serving(self) -> None:
        """Media is never modified and changed bytes stop serving."""
        before = (digest(self.video), self.video.stat().st_mtime_ns, self.video.stat().st_nlink)
        for value in ('bytes=0-99', 'bytes=50-', None):
            self.request('GET', '/media/Final.mp4', {'Range': value} if value else None)
        self.assertEqual((digest(self.video), self.video.stat().st_mtime_ns, self.video.stat().st_nlink), before)
        self.video.write_bytes(b'TEST replaced after verification')
        self.assertEqual(self.request('GET', '/media/Final.mp4')[0], 409)
        _status, _headers, body = self.request('GET', '/')
        self.assertIn('CHANGED — MP4 bytes differ from the delivery receipt', body.decode())
        self.assertEqual(self.request('GET', '/media/Final.mp4')[0], 404)


if __name__ == '__main__': unittest.main()

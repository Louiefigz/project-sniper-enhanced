"""Shared hand-off TEST fixture: a real checked export, a fake Studio, the real review player, a fake A12 reader.

The review-admission fixture supplies a checked TEST export whose real receipt reader passes; the
managed registry is real with inert TEST process identities; Studio is the loopback fake that
answers the pinned runtime's routes; the review player is the real loopback server. The batch
authority root is a private temp folder and A12's ``studio.production.api.approval_for_project`` is
patched with a TEST reader answering from ``self.approvals`` (the end-to-end chain through the real
authority is test_approved_content_chain.py). No Node,
browser or media process is started and no signal reaches a real process.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import threading
from dataclasses import replace
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

import test_native_review_admission as admission
from _fake_studio_server import FakeStudio
from _managed_preview_fixture import ManagedPreviewFixture
from studio import managed_preview_launch as launching
from studio import native_budget_store
from studio import native_handoff as handoff
from studio import native_handoff_approval as approval_reader
from studio.native_budget_store import BudgetAuthorityError
from studio.native_runtime import digest
from studio.review_player import ReviewPlayer
from studio.review_player_inventory import DRAFT_STATUS, Attempt
from test_review_player import make_attempt

OWNER = 'batch-test:Q1'
SOURCE = 'a' * 64
TITLE = 'TEST press play and post'
WORDS = [(10, 'People'), (11, 'always'), (20, 'say,'), (21, 'hey.')]
# A 40-word TEST transcript in the writer's order; the kept words sit inside the cuts [1, 2] and [3, 4.5] s.
TIMES = {10: (1.0, 1.4), 11: (1.5, 1.9), 20: (3.0, 3.4), 21: (3.5, 4.4)}
TRANSCRIPT = json.dumps({'status': 'done', 'transcript': [{'start': 0, 'end': 7, 'text': 'TEST', 'words': [
    {'word': dict(WORDS).get(index, f'w{index}'),
     'start': TIMES.get(index, (round(index * 0.1 + (1.0 if index > 11 else 0) + (1.3 if index > 21 else 0), 3),))[0],
     'end': TIMES.get(index, (0, round(index * 0.1 + (1.0 if index > 11 else 0) + (1.3 if index > 21 else 0) + 0.05, 3)))[1]}
    for index in range(40)]}]}).encode()
# Writer frames at 25 fps for those words: segment 0 is cut [1, 2] s (frames 0-25), segment 1 cut [3, 4.5] s (25-62).
OCCURRENCES = [[0, 0, 10, 0, 10, 'People', 0], [1, 0, 11, 12, 23, 'always', 0], [2, 1, 20, 25, 35, 'say,', 0],
               [3, 1, 21, 37, 60, 'hey.', 0]]


def approval_row(**fields: object) -> dict:
    """An approval-v2 row as A12's reader returns it (TEST values; identities not recomputed here)."""
    return {'title': TITLE, 'titleSha256': 'c' * 64, 'source': SOURCE,
            'transcript': hashlib.sha256(TRANSCRIPT).hexdigest(), 'transcriptWords': 40,
            'wordRanges': [[10, 11], [20, 21]], 'wordTexts': [text for _index, text in WORDS],
            'ranges': [[1.0, 2.0], [3.0, 4.5]], 'script': 'e' * 64, 'identity': 'f' * 64, 'wordCount': 4, **fields}


class HandoffFixture(ManagedPreviewFixture):
    """A delivered TEST export, its project, a fake Studio, a real review player and a TEST authority reader.

    ``TEST_READER = False`` (the end-to-end chain) leaves A12's real reader answering from the private root.
    """

    TEST_READER = True

    def setUp(self) -> None:
        """Wire the launcher so the hand-off's own view is the one the fake Studio answers for."""
        super().setUp()
        helper = admission.NativeReviewAdmissionTests('test_original_and_resumed_checked_exports_admit')
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        self.export, self.project = helper.f.root, helper.f.project
        self.studio = FakeStudio()
        self.addCleanup(self.studio.close)
        self.enterContext(mock.patch.object(launching, 'pick_free_port', return_value=self.studio.port))
        self.enterContext(mock.patch.object(native_budget_store, 'default_root', return_value=self.root / 'budgets'))
        self.approvals: dict[str, dict] = {}
        self.request_packet = self.source_inputs()
        if self.TEST_READER:
            self.enterContext(mock.patch.object(approval_reader.authority, 'approval_for_project',
                                                lambda root, project: self.approvals.get(str(project))))
            self.enterContext(mock.patch.object(approval_reader.authority, 'read_approval', self.read_approval))
        self.mocks[3].side_effect = self.launch_served
        self.player_url = self.serve_player([Attempt('Q1', 'TEST Q1', self.export)])

    def source_inputs(self) -> dict:
        """The TEST transcript, admitted manifest and request packet a draft plan binds (no media is read)."""
        source = self.root / 'source'
        source.mkdir(exist_ok=True)
        (source / 'raw-1.transcript.json').write_bytes(TRANSCRIPT)
        manifest = source / 'asset_manifest.json'
        manifest.write_text(json.dumps({'sources': [{'id': 'raw-1', 'path': str(source / 'raw.media'), 'sourceSha256': SOURCE,
                                                     'duration': 60.0, 'frameRate': '25/1',
                                                     'transcriptPath': 'raw-1.transcript.json'}]}))
        request = source / 'SHORT-REQUEST.json'
        request.write_text(json.dumps({'schemaVersion': 1, 'scope': 'TEST', 'manifest': {'path': str(manifest),
                                                                                          'sha256': digest(manifest)}}))
        return {'path': str(request), 'sha256': digest(request)}

    def read_approval(self, root: Path, batch: str, clip: str) -> dict:
        """TEST reader by batch clip: the approval self.approve recorded for it, or the authority's refusal."""
        found = [row for row in self.approvals.values() if (row['batchId'], row['clipId']) == (batch, clip)]
        if not found:
            raise BudgetAuthorityError(f'Unknown or missing budget batch: {batch}')
        return found[-1]

    def launch_served(self, cli: str, project: str, port: int, **options: object) -> object:
        """An inert TEST server identity; the fake Studio answers for the one on its port."""
        record = self.launch(cli, project, port, **options)
        if port == self.studio.port:
            self.studio.serve(project, record.pid)
        return record

    def serve_player(self, attempts: list[Attempt], port: int = 0) -> str:
        """The real loopback review player on an ephemeral (or the given) port; ``self.players`` keeps it."""
        server = ReviewPlayer(attempts, port)
        threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True).start()
        self.addCleanup(self.stop_player, server)
        url = f'http://127.0.0.1:{server.server_address[1]}/'
        self.players = {**getattr(self, 'players', {}), url: server}
        return url

    def stop_player(self, server: ReviewPlayer) -> None:
        """Stop one TEST review player (idempotent)."""
        if not getattr(server, 'stopped', False):
            server.shutdown()
            server.server_close()
            server.stopped = True

    def browser_load(self, url: str, route: str, agent: str = 'Mozilla/5.0 TEST browser') -> int:
        """What a browser's video element does on page load: a ranged GET of the MP4 route."""
        connection = http.client.HTTPConnection('127.0.0.1', urlsplit(url).port, timeout=10)
        try:
            connection.request('GET', route, headers={'User-Agent': agent, 'Range': 'bytes=0-1'})
            response = connection.getresponse()
            response.read()
            return response.status
        finally:
            connection.close()

    def page_playback(self, url: str, route: str, attempt: str = 'Q1', agent: str = 'Mozilla/5.0 TEST browser') -> int:
        """What the served review page does when its video plays: load the page (its token), then report 'playing'.
        TEST stand-in for a browser; nothing is played."""
        port = urlsplit(url).port
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        try:
            connection.request('GET', '/', headers={'User-Agent': agent})
            page = connection.getresponse().read().decode()
            token = page.split('data-page-token="', 1)[1].split('"', 1)[0]
            body = json.dumps({'token': token, 'attempt': attempt, 'route': route, 'event': 'playing', 'currentTime': 0.04})
            connection.request('POST', '/activity', body=body, headers={
                'User-Agent': agent, 'Origin': f'http://127.0.0.1:{port}', 'Content-Type': 'application/json'})
            response = connection.getresponse()
            response.read()
            return response.status
        finally:
            connection.close()

    def request(self, name: str = 'handoff.json', **fields: object) -> handoff.HandoffRequest:
        """One hand-off of the TEST export, recorded outside the attempt and project."""
        base = handoff.HandoffRequest(self.export, self.root / name, OWNER, self.player_url, load_seconds=10.0,
                                      wait_seconds=10.0)
        return replace(base, **fields)

    def codes(self, record: dict) -> list[str]:
        """The failure codes a record names."""
        return [row['code'] for row in record['failures']]

    def draft_short(self, name: str, title_holder: str = 'catalogTitle', corrections: list | None = None,
                    **delivery: object) -> Path:
        """A TEST review draft whose plan stages a title, kept words and optional caption display corrections."""
        attempt = make_attempt(self.root, name, DRAFT_STATUS, **delivery)
        project = self.root / f'{name}-project'
        plan = project / 'SHORT-PROJECT.json'
        canvas = {**json.loads(plan.read_text())['canvas'], 'sourceFile': 'assets/source.mp4', 'totalFrames': 62,
                  'segments': [{'startFrame': 0, 'endFrameExclusive': 25}, {'startFrame': 25, 'endFrameExclusive': 62}],
                  'cuts': [{'start': 1.0, 'end': 2.0, 'speed': 1}, {'start': 3.0, 'end': 4.5, 'speed': 1}],
                  'occurrences': OCCURRENCES, **({'captionCorrections': corrections} if corrections else {})}
        staged = {'copy': {'text': TITLE}, 'file': 'compositions/title.html'}
        value = {'canvas': {**canvas, 'titleCard': staged} if title_holder == 'titleCard' else canvas,
                 'assets': [{'file': 'assets/source.mp4', 'role': 'source', 'sha256': SOURCE}],
                 'requestPacket': self.request_packet,
                 **({'catalogTitle': staged} if title_holder == 'catalogTitle' else {})}
        plan.write_text(json.dumps(value))
        (project / 'index.html').write_text('<html><body><p data-hf-id="hf-p">TEST draft</p></body></html>')
        request = json.loads((attempt / 'export-request.json').read_text())
        request.update(pins={str(plan): digest(plan)},
                       productionBudget={'batchId': 'batch-test', 'clipId': 'Q1', 'attemptId': 'b' * 32, 'route': 'draft'})
        (attempt / 'export-request.json').write_text(json.dumps(request))
        return attempt

    def approve(self, project: Path, **fields: object) -> dict:
        """The TEST authority binds this project's clip to an approval-v2 row (fields override)."""
        found = {'batchId': 'batch-test', 'clipId': 'Q1', 'status': 'active', 'current': approval_row(**fields),
                 'history': [approval_row(**fields)], 'canonicalForm': 'approval-v2: TEST canonical form'}
        self.approvals[str(project)] = found
        return found

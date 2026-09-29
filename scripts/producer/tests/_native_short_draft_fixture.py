"""TEST-only review-draft fixtures: real seals and readers, synthetic undecodable media bytes."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from _native_short_pipeline_fixture import STUDIO, ShortPipelineFixture, write_json
from studio.native_runtime import digest
from studio.native_short_draft import DRAFT_MEDIA_STATUS, DRAFT_OUTPUT

PROJECT_FINDING = {'code': 'TEST_OPEN_ISSUE', 'severity': 'major', 'lane': 'plan',
                   'message': 'TEST synthetic finding; no reviewer inspected media',
                   'requiredAction': 'TEST correct it', 'source': 'prebuild-review'}


def check_draft_result(state: str) -> dict:
    """What native-short.ts check-draft reports; no TS reader runs in these tests."""
    draft = {'schemaVersion': 1, 'state': 'review-findings', 'verdict': 'revise',
             'materialIssueCodes': ['TEST_OPEN_ISSUE']} if state == 'draft' else None
    return {'status': 'project-current', 'reviewState': state, 'finalEligible': state != 'draft',
            'promotable': state != 'draft', 'draft': draft, 'label': None, 'humanApproved': False,
            'prebuildReview': {'status': f'TEST {state} prebuild status'}, 'totalFrames': 25,
            'openFindings': [PROJECT_FINDING] if state == 'draft' else []}


class DraftFixture(ShortPipelineFixture):
    """Adds a manifest, a complete canvas and draft/promotion owner outputs to the Short fixture."""

    def __init__(self, base: Path, state: str = 'final-eligible') -> None:
        """Use a real project inventory so review-bundle admission can read the draft."""
        super().__init__(base)
        self.state = state
        write_json(self.project / 'SHORT-PROJECT.json', {'canvas': {'frameRate': '25/1', 'totalFrames': 25,
                   'segments': [{'startFrame': 0, 'endFrameExclusive': 25}]}, 'strategy': {'schemaVersion': 2}, 'assets': []})
        rows = [{'file': name, 'sha256': digest(self.project / name)} for name in ('index.html', 'SHORT-PROJECT.json')]
        write_json(self.project / 'PROJECT-MANIFEST.json', {'schemaVersion': 1, 'files': rows})
        self.inputs = {str(file): digest(file) for file in (
            self.cli, self.node, self.source, *self.project.iterdir(),
            self.runtime / 'dist/native-capture-library.mjs', Path(sys.executable).resolve(),
            STUDIO / 'native_short_capture.mjs', STUDIO / 'native_short_worker.py', STUDIO / 'native_localhost_only.sb')}
        self.request = {**self.request, 'pins': self.inputs}
        self.write_request(self.request)

    def draft_request(self, output: Path | None = None) -> dict:
        """A review-draft request as the public exporter would publish it."""
        return {**self.request, 'output': str(output or self.root), 'reviewDraft': True, 'previewOnly': False,
                'draftAuthority': {'schemaVersion': 1, 'projectReviewState': self.state, 'projectDraft': None,
                                   'prebuildReview': {'status': 'TEST'}, 'openFindings': [], 'suppliedFindings': None,
                                   'editorialReview': 'pending'}}

    def admission(self, command: list[str], **_options: object) -> subprocess.CompletedProcess:
        """Stand in for the TS cold readers: check-draft reports this fixture's review state."""
        stdout = json.dumps(check_draft_result(self.state)) if command[-2] == 'check-draft' else ''
        return subprocess.CompletedProcess(command, 0, stdout=stdout)

    def write_phase(self, label: str, root: Path) -> None:
        """Model the draft owner and the real promotion worker; other phases are unchanged."""
        request = json.loads((root / 'export-request.json').read_text())
        if label == 'draft':
            self.write_draft(root)
        elif label == 'pipeline' and request.get('promoteDraft'):
            self.promote(request)
        elif label == 'verification' and request.get('promoteDraft'):
            media = json.loads((root / 'render-result.json').read_text())
            write_json(root / 'checks.json', {**media, 'status': 'checks-passed-awaiting-owned-cleanup',
                       'sha256': digest(root / 'review.mp4'), 'fullAudioVideoDecodePassed': True,
                       'pictureFramesChecked': 0, 'TEST': 'No decode or picture comparison ran'})
        else:
            super().write_phase(label, root)

    def promote(self, request: dict) -> None:
        """Run the actual promotion worker with only the media gates stubbed (no decoder here)."""
        from studio.native_short_draft_worker import execute_draft_phase
        with patch('studio.native_motion_previews.require_motion_previews') as gate, \
                patch('studio.native_picture_references.check_samples'), \
                patch('studio.native_short_draft_worker.static_admission', return_value={'staticPreflight': 'TEST'}):
            execute_draft_phase(request, 'promote')
        self.promotion_gate_calls = gate.call_count

    def write_draft(self, root: Path) -> None:
        """Synthetic draft outputs with the exact proof fields the real draft worker writes."""
        (root / 'picture.mp4').write_bytes(b'TEST draft picture, not decodable')
        (root / DRAFT_OUTPUT).write_bytes(b'TEST review draft audio and picture, not decodable')
        (root / 'audio').mkdir()
        (root / 'audio/program-master.wav').write_bytes(b'TEST float master')
        (root / 'audio/candidate.mp4').write_bytes(b'TEST AAC candidate')
        write_json(root / 'audio/receipt.json', {'status': 'audio-qualified', 'audioQuality': [],
                   'audioReviewRequired': False, 'masterSha256': digest(root / 'audio/program-master.wav'),
                   'candidateSha256': digest(root / 'audio/candidate.mp4')})
        draft = root / DRAFT_OUTPUT
        color = {'output': str(draft), 'sha256': digest(draft), 'aacPacketsIdentical': True,
                 'additionalPictureEncodes': 0, 'additionalAudioEncodes': 0}
        write_json(root / 'draft-result.json', {'status': DRAFT_MEDIA_STATUS, 'reviewState': 'draft', **color,
                   'audioReceipt': str(root / 'audio/receipt.json'), 'audioQuality': [], 'audioReviewRequired': False,
                   'color': color, 'technicalAdmission': {'staticPreflight': 'TEST not run'},
                   'playability': {'fullAudioVideoDecodePassed': True, 'TEST': 'No decode ran'},
                   'editorialReview': 'pending', 'finalQc': 'not-run', 'humanApproved': False})

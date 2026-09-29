"""Read-only labeled inventory of native export attempts for the local review player.

Status comes from each attempt's own ``delivery.json``. An MP4 is playable only when it
is the attempt's recorded output, the delivery records a passing full decode and its
current bytes equal the recorded SHA-256. ``CHECKED FOR REVIEW`` additionally requires the
maintained receipt admission (the same reader review bundles use) to pass now; it is a
technical pass. The player does not read editorial reviews: whether a checked MP4 is an
editorially approved final is reported only by ``native-review.ts check-final`` on its
FINAL-REVIEW record. Every other state is labeled for what it is. Only a passing admission is
cached, and only while the delivery, the MP4, every pinned input and the project's and attempt's
top-level files keep their exact file identities, so a project Studio rewrote after the page first
loaded is re-read, never still shown as CHECKED FOR REVIEW. Nothing here writes, links or re-encodes.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import re
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from cut_preview_io import MAX_MEDIA, bound_json, file_identity, real_directory
from studio.native_review_contract import FINAL_STATUSES, checked_delivery
from studio.native_review_html import canvas_clock
from studio.native_short_draft import DRAFT_STATUS, review_draft_delivery

OUTPUTS = {DRAFT_STATUS: 'review-draft.mp4', **{status: 'review.mp4' for status in FINAL_STATUSES.values()}}
NOT_DELIVERABLE = {'failed': 'FAILED — no complete MP4',
                   'native-short-rendered-awaiting-qc': 'RENDERED, AWAITING QC — not checked, not a deliverable',
                   'native-motion-previews-complete': 'PREVIEW EXCERPTS ONLY — no full-length MP4'}
# One reader per deliverable status; drafts are re-verified by the draft reader.
RECEIPT_READERS = {**{status: checked_delivery for status in FINAL_STATUSES.values()},
                   DRAFT_STATUS: review_draft_delivery}
CHECKED_LABEL = 'CHECKED FOR REVIEW — technical checks pass; editorial approval: see native-review.ts check-final'
SAFE_ID = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,63}\Z')
# Malformed or refused evidence of any shape becomes a visible label, never CHECKED.
EVIDENCE_ERRORS = (OSError, ValueError, RuntimeError, KeyError, TypeError, AttributeError, IndexError)


def require(value: bool, message: str) -> None:
    """Refuse invalid player input explicitly."""
    if not value:
        raise ValueError(f'Review player: {message}')


@dataclass(frozen=True)
class Attempt:
    """One named attempt folder the player lists, delivered or not."""

    identity: str
    title: str
    export: Path
    plan: str | None = None


def attempt_folder(value: object) -> Path:
    """Admit an absolute canonical folder, or a not-yet-created one under a canonical parent."""
    require(isinstance(value, str) and Path(value).is_absolute(), 'attempt folder must be an absolute path')
    path = Path(value)
    require('..' not in path.parts and path.name not in ('', '.') and str(path) == value,
            'attempt folder must be a normalized path')
    anchor = path if path.exists() or path.is_symlink() else path.parent
    require(anchor.is_dir() and anchor.resolve() == anchor, 'attempt folder must be canonical, without links')
    return path


def attempt_row(row: object) -> Attempt:
    """Validate one manifest or command-line attempt row."""
    require(type(row) is dict and {'id', 'export'} <= set(row) <= {'id', 'title', 'export', 'plan', 'entry'},
            'invalid attempt row')
    identity, title, plan = row['id'], row.get('title', row['id']), row.get('plan')
    require(isinstance(identity, str) and SAFE_ID.fullmatch(identity) is not None, 'unsafe attempt id')
    require(isinstance(title, str) and 0 < len(title.strip()) <= 200, 'invalid attempt title')
    require(plan is None or (isinstance(plan, str) and re.fullmatch(r'[A-Z][A-Z-]*\.json', plan) is not None),
            'invalid plan file name')
    return Attempt(identity, title, attempt_folder(row['export']), plan)


def read_attempts(manifest: Path | None, pairs: list[str]) -> list[Attempt]:
    """Accept a review-bundle manifest and/or ID=/absolute/attempt pairs, in order."""
    rows: list[object] = []
    if manifest is not None:
        value = bound_json(manifest.resolve(strict=True))
        require(set(value) == {'schemaVersion', 'compositions'} and type(value['schemaVersion']) is int
                and value['schemaVersion'] == 1 and type(value['compositions']) is list, 'invalid manifest schema')
        rows += value['compositions']
    for pair in pairs:
        identity, separator, folder = pair.partition('=')
        require(separator == '=', 'attempts are given as ID=/absolute/attempt-folder')
        rows.append({'id': identity, 'export': folder})
    require(1 <= len(rows) <= 64, 'the player lists one to 64 attempts')
    attempts = [attempt_row(row) for row in rows]
    require(len({row.identity.casefold() for row in attempts}) == len(attempts), 'duplicate attempt id')
    require(len({row.export for row in attempts}) == len(attempts), 'duplicate attempt folder')
    return attempts


def duration_seconds(request: dict, plan_name: str | None) -> float:
    """Samples at the pinned authored clock, exactly as the review bundle's page uses them."""
    long = request.get('adapter') == 'native-long'
    project = Path(request['project'])
    plan_file = project / (plan_name or ('LONG-PROJECT.json' if long else 'SHORT-PROJECT.json'))
    plan = bound_json(plan_file, request['pins'][str(plan_file)])
    if long:
        from studio.native_long_contract import long_audio_canvas
        plan = {**plan, 'canvas': long_audio_canvas(plan)}
    timeline, _duration = canvas_clock(plan['canvas'])
    return timeline.sample_at_frame(plan['canvas']['totalFrames']) / 48000


def label(status: str, delivery: dict, receipts: dict) -> tuple[str, str]:
    """The visible state: CHECKED only with re-verified receipts; editorial approval is check-final's to report."""
    if status in FINAL_STATUSES.values():
        if receipts['verified'] is True:
            return 'checked', CHECKED_LABEL
        return 'unverified', 'NOT RE-VERIFIED — recorded as checked, but its receipts do not verify now'
    findings = delivery.get('openFindings') or []
    text = f'REVIEW DRAFT — open findings ({len(findings)})' if findings else 'REVIEW DRAFT — editorial review pending'
    return 'draft', text + ('' if receipts['verified'] is True else ' (receipts not re-verified)')


def notes(delivery: dict, receipts: dict, media: dict) -> list[str]:
    """Plain, recorded facts beside the label; nothing here approves anything."""
    rows = [str(delivery['label'])] if delivery.get('label') else []
    rows += [str(row) for row in delivery.get('limitations') or []]
    if delivery.get('humanApproved') is not True:
        rows.append('Not human-approved.')
    if delivery.get('audioReviewRequired') is True:
        rows.append('Audio listening review required.')
    rows += [f"Audio check {row.get('name')}: {row.get('status')} ({row.get('measured')})"
             for row in delivery.get('audioQuality') or [] if isinstance(row, dict) and row.get('status') != 'pass']
    if receipts['verified'] is not True:
        rows.append(f"Receipts: {receipts['reason']}")
    if media['links'] > 1:
        rows.append(f"This MP4 has {media['links']} hard links; verification and review readers require "
                    'exactly one. Copy delivered MP4s, never hard-link them.')
    return [row[:1000] for row in rows]


def findings(delivery: dict) -> list[dict]:
    """Recorded draft findings, as plain strings for display."""
    keys = ('severity', 'code', 'message', 'requiredAction')
    return [{key: str(row.get(key, ''))[:1000] for key in keys}
            for row in delivery.get('openFindings') or [] if isinstance(row, dict)]


def blocked(text: str, detail: str | None = None) -> dict:
    """An attempt that is listed but never served."""
    return {'kind': 'blocked', 'label': text, 'detail': (detail or '')[:600] or None}


def _stat_key(path: Path) -> tuple | None:
    """A path's exact file identity without following links; None when it is absent."""
    try:
        return file_identity(path.lstat())
    except FileNotFoundError:
        return None


def inputs_key(request: dict, export: Path) -> tuple:
    """Identities of every pinned input and of the project's and attempt's top-level files.

    Those are what a receipt reader rehashes or reads (stage seals, owner receipts, checks). A
    missing project folder only changes the key; the receipt reader then reports it.
    """
    project, paths = Path(request['project']), {Path(name) for name in request['pins']}
    for folder in (project, export):
        with contextlib.suppress(FileNotFoundError, NotADirectoryError):
            paths |= {path for path in folder.iterdir() if path.is_file()}
    return tuple((str(path), _stat_key(path)) for path in sorted(paths))


def descriptor_sha256(descriptor: int, key: tuple) -> str:
    """Stream the whole open file and prove it did not change while it was read."""
    result = hashlib.sha256()
    while chunk := os.read(descriptor, 1 << 20):
        result.update(chunk)
    require(file_identity(os.fstat(descriptor)) == key, 'MP4 changed while it was hashed')
    return result.hexdigest()


class Evaluator:
    """Cache exact byte hashes and receipt admissions by file identity; never write."""

    def __init__(self) -> None:
        """Start with empty caches shared by concurrent evaluations."""
        self.lock = threading.Lock()
        self.hashes: dict[tuple, str] = {}
        self.receipts: dict[tuple, dict] = {}

    def media(self, file: Path) -> dict:
        """Hash one regular no-follow file once per identity."""
        descriptor = os.open(file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(descriptor)
            require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= MAX_MEDIA, 'MP4 is not a bounded regular file')
            key = file_identity(info)
            with self.lock:
                known = self.hashes.get(key)
            known = known or descriptor_sha256(descriptor, key)
            with self.lock:
                self.hashes[key] = known
            return {'sha256': known, 'identity': key, 'bytes': info.st_size, 'links': info.st_nlink}
        finally:
            os.close(descriptor)

    def receipt(self, status: str, export: Path, key: tuple) -> dict:
        """Run the maintained receipt admission; only a pass is reused, and only for identical inputs."""
        reader = RECEIPT_READERS.get(status)
        if reader is None:
            return {'verified': None, 'reason': 'this build has no receipt reader for this status'}
        with self.lock:
            cached = self.receipts.get(key)
        if cached is None:
            try:
                reader(export)
                cached = {'verified': True, 'reason': None}
            except EVIDENCE_ERRORS as error:  # a refusal is re-read on the next evaluation, never cached
                return {'verified': False, 'reason': f'{type(error).__name__}: {error}'[:600]}
        with self.lock:
            self.receipts[key] = cached
        return cached

    def deliverable(self, attempt: Attempt, status: str, delivery: dict) -> dict:
        """Serve only the exact recorded output of a final or draft delivery."""
        file = attempt.export / OUTPUTS[status]
        decoded = delivery if status in FINAL_STATUSES.values() else delivery.get('playability') or {}
        if delivery.get('output') != str(file) or decoded.get('fullAudioVideoDecodePassed') is not True:
            return blocked('NOT PLAYABLE — the delivery does not record a fully decoded MP4 in this attempt')
        media = self.media(file)
        if media['sha256'] != delivery.get('sha256'):
            return blocked('CHANGED — MP4 bytes differ from the delivery receipt', media['sha256'])
        request = bound_json(attempt.export / 'export-request.json')
        seconds = duration_seconds(request, attempt.plan)
        delivery_key = file_identity((attempt.export / 'delivery.json').stat())
        receipts = self.receipt(status, attempt.export, (status, str(attempt.export), delivery_key, media['identity'],
                                                         inputs_key(request, attempt.export)))
        kind, text = label(status, delivery, receipts)
        return {'kind': kind, 'label': text, 'playable': True, 'file': str(file), 'sha256': media['sha256'],
                'identity': list(media['identity']), 'bytes': media['bytes'], 'durationSeconds': seconds,
                'route': f'/media/{attempt.identity}.mp4', 'receipts': receipts,
                'notes': notes(delivery, receipts, media), 'findings': findings(delivery)}

    def classify(self, attempt: Attempt) -> dict:
        """Read the attempt's own receipts; absent or failed work is never served."""
        if not attempt.export.exists():
            return blocked('NOT STARTED — attempt folder does not exist yet')
        real_directory(attempt.export)
        if not (attempt.export / 'delivery.json').exists():
            return blocked('IN PROGRESS — no delivery.json yet')
        delivery = bound_json(attempt.export / 'delivery.json')
        status = delivery.get('status')
        if status in OUTPUTS:
            return self.deliverable(attempt, status, delivery)
        detail = ' '.join(str(delivery.get(key)) for key in ('failureCategory', 'failedPhase', 'error')
                          if delivery.get(key))
        return blocked(NOT_DELIVERABLE.get(status, f'UNRECOGNIZED STATUS — {status}'), detail)

    def evaluate(self, attempt: Attempt) -> dict:
        """Label one attempt; unreadable evidence is shown, never guessed past."""
        row = {'id': attempt.identity, 'title': attempt.title, 'export': str(attempt.export),
               'playable': False, 'notes': [], 'findings': []}
        try:
            return {**row, **self.classify(attempt)}
        except EVIDENCE_ERRORS as error:
            return {**row, **blocked('UNREADABLE — attempt evidence could not be read', f'{type(error).__name__}: {error}')}

    def inventory(self, attempts: list[Attempt]) -> list[dict]:
        """Evaluate attempts concurrently, keeping their listed order."""
        with ThreadPoolExecutor(max_workers=min(4, len(attempts))) as pool:
            return list(pool.map(self.evaluate, attempts))

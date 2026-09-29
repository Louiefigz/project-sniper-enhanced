"""Milestone evidence for batch status: shared checks and the editorial final approval.

A delivery in the authority is a media receipt: it proves an encoded MP4 and nothing more. The
hand-off seam is ``native_budget_handoffs``; this module holds what both use and the final review.

Editorial approval comes only from ``native-review.ts check-final`` over a FINAL-REVIEW record
(``check_final``, the one seam; the files run at most ``FINAL_CHECK_WORKERS`` at a time inside one
``FINAL_CHECK_BUDGET_SECONDS`` budget, each in its own process group that is killed whole when its
time runs out, so nothing it started outlives it) reporting ``editorialFinal: approved`` over the
exact MP4 of a final delivery, with ``recordSha256`` equal to the bytes read here, and answering
this batch's approved content: ``approvedContent.approved`` names this batch, the delivery's clip
and the identity of the approval in force when that delivery's launch was admitted. It is
``current`` only for the clip's latest delivery under its current approval; otherwise it is
``historical``. Its batch-clock time comes from the submission's timing in the same bytes,
cross-checked against the trail (``native_budget_review_timing``). Contradictions and proposed
changes the review recorded travel with it. It is never human approval (``humanApproved`` is
false until an operator-attestation mechanism exists). check-final re-derives the approved content
from the current active or draining batch, so a closed batch's reviews are not run: each is
reported ``not verifiable after close``.

Wall-clock stamps (a FINAL-REVIEW submission's ``submittedAt``, a hand-off's ``viewsVerifiedAt``
and ``visibleHandoffAt``) are display only: reported as written, never converted to batch elapsed
seconds and never a reason to reject a verdict. A wall clock can step back, so a stamp later than
this observation's own wall reading is flagged ``wallAheadOfObservation``. Each file yields a
verdict, accepted or rejected with its specific reason; a rejected one establishes nothing.
Records are unsigned: shape, hashes and bindings to the batch are verified, not who wrote them.
"""
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
REVIEW_CLI = REPO / 'scripts' / 'producer' / 'native-review.ts'
MAX_RECORD_BYTES = 4 * 1024 * 1024
CHECK_SECONDS = 120
FINAL_CHECK_WORKERS = 4
FINAL_CHECK_BUDGET_SECONDS = 150
KILL_GRACE_SECONDS = 5
WALL = 'wall clock (not on the batch clock)'
LATE = f'not checked within the {FINAL_CHECK_BUDGET_SECONDS} s status budget for final reviews'
CLOSED = ('not verifiable after close: check-final re-derives approved content from the current active or '
          'draining batch, and a closed batch\'s approval binds nothing')


class EvidenceRejected(ValueError):
    """A milestone record that does not establish what it claims."""


def require(condition: object, reason: str) -> None:
    """Reject the record with this reason unless the condition holds."""
    if not condition:
        raise EvidenceRejected(reason)


def mapping(value: object) -> dict:
    """A JSON object field, or an empty one when absent or of another type."""
    return value if isinstance(value, dict) else {}


def read_record(path: Path) -> tuple[dict, str]:
    """A bounded JSON object and the SHA-256 of the exact bytes read."""
    with path.open('rb') as handle:
        data = handle.read(MAX_RECORD_BYTES + 1)
    require(len(data) <= MAX_RECORD_BYTES, f'{path} exceeds {MAX_RECORD_BYTES} bytes')
    value = json.loads(data)
    require(isinstance(value, dict), f'{path} is not a JSON object')
    return value, hashlib.sha256(data).hexdigest()


def _moment(stamp: object) -> float | None:
    """A zoned ISO-8601 wall time as epoch seconds, or None when it is not one."""
    try:
        moment = datetime.fromisoformat(stamp.replace('Z', '+00:00')) if isinstance(stamp, str) else None
    except ValueError:
        return None
    return moment.timestamp() if moment is not None and moment.tzinfo is not None else None


def wall_stamps(record: dict, stamps: dict) -> dict:
    """Display-only wall stamps as written, flagged when later than this observation's wall reading (never rejected)."""
    shown = {name: stamp for name, stamp in stamps.items() if stamp is not None}
    moments = {name: _moment(stamp) for name, stamp in shown.items()}
    return {**shown, 'wallAheadOfObservation': any(moment is not None and moment > record['clock']['epoch']
                                                   for moment in moments.values()),
            'wallUnreadable': [name for name, moment in moments.items() if moment is None]}


def same_path(first: str, second: str) -> bool:
    """The same file path, directly or after resolving links."""
    return first == second or os.path.realpath(first) == os.path.realpath(second)


def find_delivery(record: dict, mp4: object, kinds: tuple[str, ...]) -> tuple[str, dict]:
    """The clip and delivery whose MP4 path and SHA-256 equal this record's."""
    require(isinstance(mp4, dict) and isinstance(mp4.get('path'), str) and isinstance(mp4.get('sha256'), str),
            'the record names no MP4 path and SHA-256')
    rows = ((clip_id, row) for clip_id, clip in record['clips'].items() for row in clip['deliveries'])
    for clip_id, row in rows:
        if row['kind'] in kinds and row['sha256'] == mp4['sha256'] and row['output'] \
                and same_path(row['output'], mp4['path']):
            return clip_id, row
    raise EvidenceRejected(f'{mp4["path"]} ({mp4["sha256"][:12]}…) is not a {"/".join(kinds)} delivery '
                           f'recorded by batch {record["batchId"]}')


def delivery_summary(record: dict, clip_id: str, row: dict) -> dict:
    """The delivery a verdict is bound to, and whether it is the clip's latest."""
    last = record['clips'][clip_id]['deliveries'][-1]
    return {'clipId': clip_id, 'kind': row['kind'], 'attemptId': row['attemptId'], 'output': row['output'],
            'sha256': row['sha256'], 'encodedAt': row['elapsed'],
            'latest': (last['attemptId'], last['sha256']) == (row['attemptId'], row['sha256'])}


def _kill_group(process: subprocess.Popen) -> None:
    """SIGKILL the check's whole process group, then reap its leader.

    The leader is not reaped yet, so its group id is still this check's and cannot name anyone else's.
    """
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    for stream in (process.stdout, process.stderr):
        stream.close()
    process.wait(timeout=KILL_GRACE_SECONDS)


def _run(command: list[str], environment: dict, timeout: float) -> tuple[int, str, str]:
    """Run a command in a new session; on its timeout (or any interruption) its whole group is killed."""
    process = subprocess.Popen(command, cwd=REPO, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
    try:
        out, err = process.communicate(timeout=timeout)
    except BaseException:
        _kill_group(process)
        raise
    return process.returncode, out, err


def check_final(file: Path, timeout: float = CHECK_SECONDS) -> dict:
    """The one seam to the typed final-review reader: ``native-review.ts check-final`` over this record."""
    from studio.native_run_config import local_environment
    tools, environment = local_environment()
    code, out, err = _run([tools['node'], '--import', 'tsx', str(REVIEW_CLI), 'check-final', str(file)],
                          environment, timeout)
    require(code == 0, 'check-final refused the record: ' + (err or out).strip()[-400:])
    value = json.loads(out)
    require(isinstance(value, dict), 'check-final printed no result object')
    return value


def in_force(clip: dict, attempt_id: str) -> dict:
    """The approval in force when this delivery's launch was admitted."""
    attempt = next((row for row in clip['attempts'] if row['id'] == attempt_id), None)
    require(attempt is not None, f'the delivery\'s launch {attempt_id} is not recorded')
    rows = [row for row in clip['approvals'] if row['elapsed'] <= attempt['admittedElapsed']]
    require(rows, 'no approved content was bound when the delivery\'s launch was admitted')
    return rows[-1]


def _answered(record: dict, clip_id: str, checked: dict, attempt_id: str) -> dict:
    """The approved content the review answered is this batch's, this clip's and in force for the delivery."""
    content = mapping(checked.get('approvedContent'))
    approved = content.get('approved')
    require(isinstance(approved, dict), 'the review bound no approved content (approvedContent.approved is absent)')
    require(approved.get('batch') == record['batchId'],
            f'the review answered batch {approved.get("batch")!r}, not {record["batchId"]}')
    require(approved.get('clip') == clip_id, f'the review answered clip {approved.get("clip")!r}, not {clip_id}')
    clip = record['clips'][clip_id]
    expected = in_force(clip, attempt_id)
    require(approved.get('identity') == expected['identity'],
            'the review answered approved content that was not in force when the delivery was admitted')
    current = clip['approvals'][-1]['identity'] == expected['identity']
    return {'identity': expected['identity'], 'currentApproval': current,
            **{key: [str(item) for item in content[key][:32]] if isinstance(content.get(key), list) else []
               for key in ('departures', 'contradictions', 'proposedChanges')}}


def _approved(record: dict, read: tuple[dict, str, dict], events: tuple[dict, ...]) -> dict:
    """An editorial final over a delivered final MP4 of this batch's approved content. read = (record, sha, result)."""
    from studio.native_budget_review_timing import approval_time
    value, digest, checked = read
    require(checked.get('editorialFinal') == 'approved',
            f'check-final reports editorialFinal {checked.get("editorialFinal")!r} '
            f'(missing: {"; ".join(map(str, checked.get("missing") or [])) or "not reported"})')
    clip_id, row = find_delivery(record, checked.get('video'), ('final',))
    content = _answered(record, clip_id, checked, row['attemptId'])
    delivery = delivery_summary(record, clip_id, row)
    current = delivery['latest'] and content['currentApproval']
    return {'kind': 'editorial-final', 'standing': 'current' if current else 'historical', 'delivery': delivery,
            'approvedContent': content, 'timing': approval_time(record, value, digest, (clip_id, events)),
            'wall': wall_stamps(record, {'submittedAt': mapping(value.get('submission')).get('submittedAt')}),
            'clock': WALL, 'humanApproved': False, 'independence': checked.get('independence'),
            'reviewer': checked.get('reviewer'), 'status': checked.get('status')}


def final_review_verdict(record: dict, path: Path, timeout: float = CHECK_SECONDS,
                         events: tuple[dict, ...] = ()) -> dict:
    """What one FINAL-REVIEW record establishes, as check-final reads it now, timed against the observed trail."""
    try:
        path = path.resolve(strict=True)
        value, digest = read_record(path)
        checked = check_final(path, timeout)
        require(checked.get('recordSha256') == digest, 'the FINAL-REVIEW record changed while it was checked')
        found = _approved(record, (value, digest, checked), events)
    except (EvidenceRejected, OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        return {'file': str(path), 'accepted': False, 'reason': f'{type(error).__name__}: {error}'[:600]}
    return {'file': str(path), 'sha256': digest, 'accepted': True, **found}


def _within(record: dict, path: Path, deadline: float, events: tuple[dict, ...]) -> dict:
    """One check with whatever remains of the overall budget when it starts."""
    remaining = min(CHECK_SECONDS, deadline - time.monotonic())
    if remaining <= 0:
        return {'file': str(path), 'accepted': False, 'reason': LATE}
    return final_review_verdict(record, path, remaining, events)


def final_review_verdicts(record: dict, files: tuple[Path, ...], events: tuple[dict, ...] = ()) -> list[dict]:
    """Every named FINAL-REVIEW record, checked concurrently inside one overall budget.

    A check starts with what remains of the budget as its own timeout and its process group is
    killed when that runs out, so every started check ends by the budget (plus the grace to reap
    it); checks not started by then are reported as not checked. A closed batch runs none.
    """
    if record['status'] == 'closed':
        return [{'file': str(path), 'accepted': False, 'reason': CLOSED} for path in files]
    if not files:
        return []
    deadline = time.monotonic() + FINAL_CHECK_BUDGET_SECONDS
    pool = ThreadPoolExecutor(max_workers=FINAL_CHECK_WORKERS)
    futures = [pool.submit(_within, record, path, deadline, events) for path in files]
    wait(futures, timeout=FINAL_CHECK_BUDGET_SECONDS + KILL_GRACE_SECONDS)
    pool.shutdown(wait=False, cancel_futures=True)
    return [future.result() if future.done() and not future.cancelled()
            else {'file': str(path), 'accepted': False, 'reason': LATE} for future, path in zip(futures, files)]

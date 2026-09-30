"""``native_batch.py status``: one locked observation, the evidence the caller names, one status vocabulary.

``status_observation`` reads the record, advances the clock, marks provably dead launches and reads
the authority trail's hand-off, claim, release, packet-resolved and review-submitted events in the
same batch-lock session, so a delivery or hand-off landing between two reads cannot produce a false
miss, and a review's timing is cross-checked against the trail observed with the record.
``audited_observation`` adds the capacity audit (``queue_audit.audit_record``) from that same read, so a status
reads the trail once (X183 n3). ``production_status``
adds to ``native_budget_report.batch_status`` each output's state, next actions, blockers,
milestones and forecast path, and the run's AI, usage, media and cleanup
(``native_budget_outputs``, ``_milestones``, ``_handoffs``, ``_evidence``, ``_usage``,
``_breakdown``, ``_run_status``). By default it prints that compactly; ``--full`` prints the whole
production block. Evidence files are named (``--handoff``, ``--final-review``, ``--timing``,
``--transcript``); nothing is discovered, and one unreadable file is named without hiding the rest.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from agent_usage import collect_files
from stage_timing_report import read_journals, summarize_timings
from studio.native_budget_binding import advance_clock
from studio.native_budget_breakdown import breakdown
from studio.native_budget_evidence import final_review_verdicts
from studio.native_budget_handoffs import handoff_verdicts
from studio.native_budget_launch import reconcile_running
from studio.native_budget_outputs import output_status
from studio.native_budget_report import batch_status
from studio.native_budget_run_status import run_status
from studio.native_budget_store import EVENTS, MAX_EVENT_BYTES, BudgetAuthorityError, locked_batch
from studio.native_budget_usage import ai_usage

TRAIL_EVENTS = ('clip-handed-off', 'task-claimed', 'task-released', 'packet-resolved', 'review-submitted')
SECTIONS = ('preparation', 'encoding', 'visibleMp4', 'matchingStudio', 'editorialApproval', 'cleanup', 'slaMiss')


@dataclass(frozen=True)
class StatusInputs:
    """One status read: the named evidence files, the observed trail events and the dispatcher's state."""

    handoffs: tuple[Path, ...] = ()
    final_reviews: tuple[Path, ...] = ()
    timing: tuple[Path, ...] = ()
    transcripts: tuple[Path, ...] = ()
    events: tuple[dict, ...] = ()
    dispatcher: dict | None = None
    full: bool = False
    audit: dict | None = None   # queue_audit.audit_record, from cmd_status's one trail read; None: not audited


CLOCK_KEYS = ('timingPolicy', 'totalElapsedSeconds', 'countedProductionSeconds', 'excludedRenderQueueSeconds',
              'uncertainQueueSeconds', 'capacityWaits')


def status_arguments(parser: argparse.ArgumentParser) -> None:
    """The evidence options of ``native_batch.py status`` (each repeatable) and ``--full``."""
    for option, text in (('--handoff', 'a hand-off record or confirmation file (not on the batch clock)'),
                         ('--final-review', 'a FINAL-REVIEW record, read with native-review.ts check-final'),
                         ('--timing', 'a stage_timings.jsonl journal of this batch (a launch\'s attempt journal)'),
                         ('--transcript', 'a host transcript (Claude Code JSONL or Codex rollout) for token usage')):
        parser.add_argument(option, action='append', type=Path, default=[], help=text)
    parser.add_argument('--full', action='store_true', help='print the whole production block, not the summary')


def _trail(session: object) -> tuple[dict, list[dict]]:
    """Inside the caller's batch lock: the trail events status reads (``TRAIL_EVENTS``) and every committed event
    (``approvals.trail_events``: an event followed by its own failure is dropped), from one read."""
    from headless.durable_files import DurableFileError, read_private_file
    from studio.production.approvals import trail_events
    try:
        data = read_private_file(session.dir_fd, EVENTS, MAX_EVENT_BYTES)
        rows = [json.loads(line) for line in data.decode('utf-8').splitlines() if line.strip()]
        committed = trail_events(data)
    except (OSError, DurableFileError, UnicodeError, ValueError) as error:
        raise BudgetAuthorityError(f'Budget event trail for {session.batch_id} is unreadable: {error}') from error
    return tuple(row for row in rows if isinstance(row, dict) and row.get('event') in TRAIL_EVENTS), committed


def _observe(root: Path, batch_id: str) -> tuple[dict, float, tuple[tuple[dict, ...], list[dict]]]:
    """Lock once: read, advance the clock, mark provably dead launches, commit, read the trail."""
    with locked_batch(root, batch_id) as session:
        record = session.read()
        elapsed = advance_clock(record)
        abandoned = reconcile_running(record, elapsed)
        session.commit(record, {'event': 'observed', 'elapsed': elapsed, 'abandoned': abandoned})
        return record, elapsed, _trail(session)


def status_observation(root: Path, batch_id: str) -> tuple[dict, float, tuple[dict, ...]]:
    """One locked observation: the record, its elapsed time and the trail events status reads."""
    record, elapsed, (events, _committed) = _observe(root, batch_id)
    return record, elapsed, events


def audited_observation(root: Path, batch_id: str) -> tuple[dict, float, tuple[dict, ...], dict]:
    """``status_observation`` plus each v2 Short's capacity audit, from the same trail read (X183 n3)."""
    from studio.production.queue_audit import audit_record
    record, elapsed, (events, committed) = _observe(root, batch_id)
    return record, elapsed, events, audit_record(record, committed)


def status_inputs(args: argparse.Namespace, events: tuple[dict, ...], dispatcher: dict | None) -> StatusInputs:
    """The named evidence of a parsed status command, with the observation's trail events.

    An in-process caller (``native_batch.cmd_status(Namespace(batch=...))``) may omit every option: none is named
    and the view is compact.
    """
    named = [tuple(getattr(args, key, None) or ()) for key in ('handoff', 'final_review', 'timing', 'transcript')]
    return StatusInputs(*named, events, dispatcher, bool(getattr(args, 'full', False)))


def _timing(record: dict, journals: tuple[Path, ...]) -> tuple[dict | None, dict]:
    """The merged timing summary; each span keeps the directory of the journal it came from."""
    if not journals:
        return None, {'status': 'not-supplied'}
    rows, unreadable = [], []
    for path in journals:
        try:
            rows += [{**row, 'journalDir': str(path.parent)} for row in read_journals([path])]
        except (OSError, UnicodeError) as error:
            unreadable.append({'journal': str(path), 'reason': f'{type(error).__name__}: {error}'[:300]})
    summary = summarize_timings(rows, record['batchId'])
    summary['journalDirs'] = [str(path.parent) for path in journals]
    return summary, {'status': 'read', 'journals': len(journals), 'unreadable': unreadable,
                     'spans': len(summary['spans']), 'issues': len(summary['issues']),
                     'lineageRejectedSpans': summary['lineageRejectedSpans']}


def _transcripts(record: dict, files: tuple[Path, ...]) -> dict | None:
    """Host usage records from the batch start to this observation, each once across files."""
    return collect_files(list(files), (record['startEpoch'], record['clock']['epoch'])) if files else None


def production_status(record: dict, elapsed: float, inputs: StatusInputs) -> dict:
    """``batch_status`` plus each output's status and milestones and the run's; compact unless ``full``."""
    status = batch_status(record, elapsed, inputs.audit)
    found = {'handoffs': handoff_verdicts(record, inputs.events, inputs.handoffs, elapsed),
             'finalReviews': final_review_verdicts(record, inputs.final_reviews, inputs.events)}
    timing, journal = _timing(record, inputs.timing)
    transcripts = _transcripts(record, inputs.transcripts)
    parts = {'verdicts': found, 'transcripts': transcripts, 'timing': timing, 'events': inputs.events}
    for clip_id, row in status['clips'].items():
        row['production'] = output_status(record, clip_id, elapsed, {**parts, 'actions': row['actions']})
    misses = [clip_id for clip_id, row in status['clips'].items() if row['production']['milestones']['slaMiss']['miss']]
    status['production'] = {
        'run': run_status(record, elapsed, inputs.dispatcher), 'ai': ai_usage(record, None, transcripts),
        'elapsedBreakdown': breakdown(record, elapsed, timing, (None, inputs.events)), 'evidence': found,
        'timingJournal': journal, 'visibleSlaMisses': misses,
        'slaBasis': {'slaMisses': 'no complete MP4 encoded by the delivery deadline (necessary, not sufficient)',
                     'visibleSlaMisses': 'no visible hand-off recorded on the batch clock by the delivery deadline'}}
    return status if inputs.full else compact(status)


def _compact_output(row: dict) -> dict:
    """One output's state, next actions, blockers, milestone times and statuses, and forecast path status."""
    found, forecast = row['milestones'], row['forecast']
    return {'state': row['state'], 'nextActions': row['nextActions'], 'blockers': row['blockers'],
            'milestones': {'timestamps': found['timestamps'], **{name: found[name]['status'] for name in SECTIONS}},
            'forecast': {'status': forecast['status'], 'pathStatus': (forecast['path'] or {}).get('status'),
                         'latestSafeStartElapsed': (forecast['path'] or {}).get('latestSafeStartElapsed')}}


def compact(status: dict) -> dict:
    """The default status: every earlier field, and the production block summarized (``--full`` for all of it).

    Each output's compact view carries its counted clock (``queue_clock.status``: policy, total and counted
    production seconds, settled render-queue credit, uncertain seconds and capacity waits; P0 Step 4.3).
    """
    production, usage = status['production'], status['production']['ai']['usage']
    for row in status['clips'].values():
        row['production'] = {**_compact_output(row['production']), 'clock': {key: row[key] for key in CLOCK_KEYS}}
    run = production['run']
    status['production'] = {
        'full': False, 'visibleSlaMisses': production['visibleSlaMisses'], 'slaBasis': production['slaBasis'],
        'run': {'ai': {key: run['ai'].get(key) for key in ('slots', 'active', 'reservations', 'charged',
                                                          'liveAiTasks', 'readyAiTasks')},
                'dispatcherRunning': (run['dispatcher'] or {}).get('running'),
                'pool': run['media']['hostPool']['status'],
                'cleanupSettled': run['cleanup']['settled']},
        'usageTotals': {'authority': usage['authority']['totals'], 'transcripts': usage['transcripts'].get('totals')},
        'rejectedEvidence': sum(not row['accepted'] for rows in production['evidence'].values() for row in rows),
        'timingJournal': production['timingJournal']['status'], 'more': 'native_batch.py status --full'}
    return status

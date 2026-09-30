"""The ``native_batch.py`` command vocabulary: its parser, the production-task commands and exit codes.

Batch commands (start, bind, admit, status, wait, hold, handoff, close, archive) are in
``commands``; add-clip, change-approval, staged-starts and discard-start in
``handover_commands``. The task commands here call the locked Python API (``production.api``),
each one locked, validated read-modify-write with one event:

- ``enroll`` records the running director with its exact host handle (AI work descends from it);
- ``enqueue`` adds a typed submission (``inputs.load_tasks``); a media task's request is kept
  privately with its launch input identity (``media.store_request``); the task's input fingerprint
  binds both (``task_schema.launch_fingerprint``);
- ``next`` claims the most urgent admissible AI or check task for the enrolled director (``--peek``
  only lists admissible work). Media tasks are claimed by the dispatcher only. AI work is recorded
  under supervised governance only: the coordinator must stay alive to interrupt it;
- ``attach``, ``complete`` (artifact receipts hashed here, or ``--failure``), ``release``,
  ``cancel-request``, ``cancelled`` and ``reconcile`` are the fenced callbacks and recovery;
- ``dispatch`` starts the detached media dispatcher (``dispatch``); ``run-media`` runs one claimed
  media task's public export under the export watchdog (``process_watch``).

Exit codes: 0 ok, 3 refused (do not start the work), 2 invalid or corrupt authority; ``run-media``
exits with its exporter's code.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from studio import native_budget_store as store
from studio.native_budget_binding import BudgetRefused
from studio.native_budget_clock import BudgetClockError
from studio.native_budget_status import status_arguments
from studio.native_budget_store import BudgetAuthorityError
from studio.production import api, commands, dispatch, handover_commands, inputs, media, queue_commands
from studio.production.callbacks import TaskFailure, TaskResult
from studio.production.claims import ClaimRef, Enrollment
from studio.production.process import ExportLaunch, TaskClaim
from studio.production.task_schema import holds_slot, is_ai
from studio.production.tasks import TaskRefused

REFUSED, INVALID = 3, 2
ROOT_COMMANDS = ('staged-starts', 'discard-start')   # a staged start is named by its staging name, not a batch
TASK_COMMANDS = ('attach', 'complete', 'release', 'cancelled', 'run-media')


def _ref(args: argparse.Namespace) -> ClaimRef:
    """The fenced claim a callback speaks for."""
    return ClaimRef(args.task, args.epoch, args.token)


def cmd_enroll(args: argparse.Namespace) -> dict:
    """Record the running director with its exact host handle; it holds one AI slot and one reservation."""
    enrollment = Enrollment(args.task, inputs.handle(args.handle), args.version, args.fingerprint)
    return api.enroll_director(store.default_root(), args.batch, enrollment)


def cmd_enqueue(args: argparse.Namespace) -> dict:
    """Add one typed submission atomically; keep each media task's exact request under its task id."""
    submissions = inputs.load_tasks(args.tasks, args.batch)
    result = api.enqueue_tasks(store.default_root(), args.batch, tuple(row.spec for row in submissions))
    for row in submissions:
        if row.request is not None:
            media.store_request(store.default_root(), args.batch, row.spec.task_id, row.request)
    return result


def _director(record: dict) -> dict:
    """The enrolled, live director's handle: the claimer of the coordinator's AI and check work."""
    live = [task for task in record['production']['tasks'].values() if task['kind'] == 'director' and holds_slot(task)]
    if not live:
        raise TaskRefused('No running director is enrolled: enroll it with its host handle before claiming work')
    return live[0]['handle']


def cmd_next(args: argparse.Namespace) -> dict:
    """Claim the most urgent admissible AI or check task (``--peek``: list admissible work only)."""
    root = store.default_root()
    rows = [row for row in api.next_ready(root, args.batch) if row['kind'] != 'media'
            and (args.task is None or row['taskId'] == args.task)]
    work = [row for row in rows if row['refusal'] is None]
    held = [{'taskId': row['taskId'], 'reason': row['refusal']} for row in rows if row['refusal']]
    if args.peek or not work:
        return {'status': 'admissible-work' if work else 'no-admissible-work', 'work': work, 'held': held}
    record = store.read_batch(root, args.batch)
    task = record['production']['tasks'][work[0]['taskId']]
    governance = record['production']['governance'] or {}
    if is_ai(task) and governance.get('mode') != 'supervised':
        raise TaskRefused(f'AI work is recorded under supervised governance only; this run is '
                          f'{governance.get("mode") or "not enrolled"}')
    claimed = api.claim_task(root, args.batch, task['id'], _director(record))
    return {'status': 'claimed', 'claim': claimed, 'held': held}


def cmd_attach(args: argparse.Namespace) -> dict:
    """The launched execution acknowledges its claim with its exact handle before any work."""
    return api.attach_task(store.default_root(), args.batch, _ref(args), inputs.handle(args.handle))


def cmd_complete(args: argparse.Namespace) -> dict:
    """Record the execution's artifact receipts (hashed here), or its failure category."""
    usage = inputs.usage(args.usage)
    if args.failure is not None:
        if args.artifact or args.detail is None:
            raise ValueError('--failure CATEGORY takes --detail TEXT and binds no --artifact')
        failure = TaskFailure(args.failure, args.detail, usage, args.launch_error)
        return api.fail_task(store.default_root(), args.batch, _ref(args), failure)
    if args.launch_error is not None:
        raise ValueError('--launch-error goes with --failure: it records a launch call that itself failed')
    result = TaskResult(inputs.receipts(args.artifact or []), usage)
    return api.complete_task(store.default_root(), args.batch, _ref(args), result)


def cmd_release(args: argparse.Namespace) -> dict:
    """Release a claim no execution acknowledged; an AI claim needs the launch tool's own failure (--launch-error)."""
    return api.release_claim(store.default_root(), args.batch, _ref(args), args.launch_error)


def cmd_cancel_request(args: argparse.Namespace) -> dict:
    """Cancel unlaunched work, or ask live work to stop; returns the exact handle to interrupt."""
    return api.request_cancel(store.default_root(), args.batch, args.task, args.reason)


def cmd_cancelled(args: argparse.Namespace) -> dict:
    """The caller observed the execution's termination; its slot frees only as ``task_end`` allows (G9)."""
    return api.confirm_cancelled(store.default_root(), args.batch, _ref(args), inputs.usage(args.usage))


def cmd_reconcile(args: argparse.Namespace) -> dict:
    """Apply one process-table read (and the host's reported turn states) to every unsettled task."""
    host = json.loads(args.host) if args.host else None
    return api.reconcile(store.default_root(), args.batch, host)


def cmd_dispatch(args: argparse.Namespace) -> dict:
    """Start the batch's detached media dispatcher, or report the one already running."""
    return dispatch.start(store.default_root(), args.batch)


def cmd_run_media(args: argparse.Namespace) -> dict:
    """Run one claimed media task's public export under the export watchdog."""
    root = store.default_root()
    kept = media.stored_request(root, args.batch, args.task)
    task = store.read_batch(root, args.batch)['production']['tasks'].get(args.task)
    if kept is None or task is None:
        raise TaskRefused(f'Media task {args.task} has no kept request in batch {args.batch}')
    media.check_request(task, *kept)
    held = task['claim'] or {}
    if task['state'] != 'claimed' or task['handle'] is not None \
            or (held.get('epoch'), held.get('token')) != (args.epoch, args.token):
        raise TaskRefused(f'Media task {args.task} is {task["state"]} and this is not its unacknowledged claim')
    request, arguments = kept[0], media.exporter_arguments(kept[0])
    media.check_route(arguments, request['route'])
    from studio.production.process_watch import supervise_export
    claim = TaskClaim(args.batch, args.task, args.epoch, args.token, kept[1])
    launch = ExportLaunch(tuple(arguments), Path(request['project']), claim)
    return {'status': 'run-media-finished', 'taskId': args.task, 'exitCode': supervise_export(launch)}


HANDLERS = {'start': commands.cmd_start, 'admit': commands.cmd_admit, 'status': commands.cmd_status,
            'wait': commands.cmd_wait, 'hold': commands.cmd_hold, 'add-clip': handover_commands.cmd_add_clip,
            'handoff': commands.cmd_handoff, 'close': commands.cmd_close, 'bind': commands.cmd_bind,
            'archive': commands.cmd_archive, 'change-approval': handover_commands.cmd_change_approval,
            'staged-starts': handover_commands.cmd_staged_starts,
            'discard-start': handover_commands.cmd_discard_start, 'enroll': cmd_enroll, 'enqueue': cmd_enqueue,
            'next': cmd_next,
            'attach': cmd_attach, 'complete': cmd_complete, 'release': cmd_release,
            'cancel-request': cmd_cancel_request, 'cancelled': cmd_cancelled, 'reconcile': cmd_reconcile,
            'dispatch': cmd_dispatch, 'run-media': cmd_run_media, **queue_commands.HANDLERS}


def _batch_parsers(sub: argparse._SubParsersAction) -> None:
    """The batch commands' arguments."""
    start = sub.add_parser('start')
    start.add_argument('--clips', required=True)
    start.add_argument('--approval', action='append', metavar='CLIP=FILE',
                       help='One clip\'s approved title and script (native-short-approval); repeat per clip')
    start.add_argument('--approvals', type=Path, help='Every clip\'s approval in one native-short-approvals file')
    start.add_argument('--source', action='append', type=Path,
                       help='A recording the operator authorized for this batch (recorded); repeat for several')
    start.add_argument('--pool-slots', type=int, help='Defaults to the host pool\'s qualified heavy slots')
    start.add_argument('--ai-slots', type=int, help='Concurrent AI slots, director included (default 4, at most 16)')
    start.add_argument('--ai-reservations', type=int,
                       help='AI tasks the run may charge (default: per-clip dispatch ceilings + 8, at most 256)')
    for name in ('bind', 'admit', 'add-clip', 'change-approval', 'handoff'):
        sub.add_parser(name).add_argument('--clip', required=True)
    sub.choices['bind'].add_argument('project', type=Path)
    sub.choices['admit'].add_argument('--kind', required=True, choices=('author', 'review', 'planReview',
                                                                        'repairCycle'))
    sub.choices['admit'].add_argument('--label', default='')
    sub.choices['add-clip'].add_argument('--reason', required=True)
    sub.choices['add-clip'].add_argument('--approval', type=Path, help='The added clip\'s native-short-approval')
    sub.choices['change-approval'].add_argument('--approval', type=Path, required=True,
                                                help='The clip\'s changed native-short-approval (title and script)')
    sub.choices['change-approval'].add_argument('--reason', required=True, help='Why (echoed; not recorded)')
    sub.choices['handoff'].add_argument('--confirmation', type=Path, required=True,
                                        help='The native_handoff.py confirm record (visible-handoff)')
    for name in ('status', 'close', 'archive', 'reconcile', 'dispatch', *ROOT_COMMANDS):
        sub.add_parser(name)
    status_arguments(sub.choices['status'])
    sub.choices['archive'].add_argument('--reason', required=True,
                                        help="The operator's request to release this closed batch's Shorts")
    discard = sub.choices['discard-start']
    discard.add_argument('--name', required=True, help='The staging name staged-starts lists')
    discard.add_argument('--reason', required=True, help="The operator's decision to discard that staged start")
    sub.choices['reconcile'].add_argument('--host', help='JSON {"host:thread:turn": running|terminal|unknown}')
    wait = sub.add_parser('wait')
    wait.add_argument('--clip')
    wait.add_argument('--until', choices=('change', 'delivery'), default='change')
    wait.add_argument('--timeout', type=float, default=600)
    hold = sub.add_parser('hold')
    hold.add_argument('action', choices=('start', 'end'))
    hold.add_argument('--reason', required=True)


def _task_parsers(sub: argparse._SubParsersAction) -> None:
    """The production-task commands' arguments."""
    enroll = sub.add_parser('enroll')
    for name in ('--task', '--handle', '--version', '--fingerprint'):
        enroll.add_argument(name, required=True)
    sub.add_parser('enqueue').add_argument('--tasks', type=Path, required=True)
    nxt = sub.add_parser('next')
    nxt.add_argument('--task', help='Claim this ready task instead of the most urgent one')
    nxt.add_argument('--peek', action='store_true', help='List admissible work without claiming it')
    for name in TASK_COMMANDS:
        command = sub.add_parser(name)
        command.add_argument('--task', required=True)
        command.add_argument('--epoch', type=int, required=True)
        command.add_argument('--token', required=True)
    sub.choices['attach'].add_argument('--handle', required=True, help='JSON process or host handle')
    complete = sub.choices['complete']
    complete.add_argument('--artifact', action='append', type=Path, help='An immutable output file; repeat')
    complete.add_argument('--failure', help='A failure category slug (instead of artifacts)')
    complete.add_argument('--detail', help='The failure detail')
    for name in ('complete', 'release'):
        sub.choices[name].add_argument('--launch-error', help="The launch tool's own failure, verbatim (1-512 bytes)")
    for name in ('complete', 'cancelled'):
        sub.choices[name].add_argument('--usage', help='JSON cumulative host token usage')
    cancel = sub.add_parser('cancel-request')
    cancel.add_argument('--task', required=True)
    cancel.add_argument('--reason', required=True)


def parser(description: str) -> argparse.ArgumentParser:
    """The closed command vocabulary; every command names its batch except the staged-start ones."""
    main_parser = argparse.ArgumentParser(description=description,
                                          formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = main_parser.add_subparsers(dest='command', required=True)
    _batch_parsers(sub)
    _task_parsers(sub)
    queue_commands.register(sub)
    for name, command in sub.choices.items():
        if name not in ROOT_COMMANDS:
            command.add_argument('--batch', required=True)
    return main_parser


def main(description: str, argv: list[str] | None = None) -> None:
    """Dispatch one command; refusals are ordinary, visible outcomes (exit 3)."""
    args = parser(description).parse_args(argv)
    try:
        result = HANDLERS[args.command](args)
    except BudgetRefused as error:
        print(json.dumps({'status': 'refused', 'reason': str(error)}, indent=2, sort_keys=True), flush=True)
        raise SystemExit(REFUSED) from error
    except (BudgetAuthorityError, BudgetClockError, ValueError, KeyError, OSError, RuntimeError) as error:
        print(json.dumps({'status': 'error', 'error': f'{type(error).__name__}: {error}'}, indent=2, sort_keys=True),
              flush=True)
        raise SystemExit(INVALID) from error
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    if args.command == 'run-media':
        raise SystemExit(result['exitCode'])

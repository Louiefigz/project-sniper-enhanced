"""Reserve the AI slots the current Long section rows still need (G9: X114 M5, X125 N2, X168).

This is a claim admission check inside the existing transaction, not a scheduler.
Attached reviewers keep their original claim, deadline and charge. Only the
current frozen Long assignment inventory contributes prerequisite work; unrelated
or obsolete author tasks never create a phantom reservation.

Under G9 a host turn's end keeps its slot until termination evidence (none before M-102),
so an early review cannot reuse its author's slot. A started row whose early review can still
run reserves one slot: its author is live and its end would not release a slot for the review
(``task_end.end_proof``), or its author completed and the review has not started (none yet, or
blocked or ready). A row that can never progress reserves nothing (X168): an author that ended
without completing, or is asked to stop or revoked (it can only end cancelled or superseded),
never gets its review bound, since a review binds to its author's completed result; a review
that ended or was cancelled before it ran is never claimed again. No path returns an ended
task to ``blocked`` or ``ready`` (``dependencies.refresh`` moves only unclaimed tasks,
``claims._release`` readies only a claimed one, a replayed id is never reset); a new plan's
rows are new rows. A row whose author has not started (none yet, or blocked or ready) is
dormant: it needs two slots, its author's and its early review's; the +2 applies once, since
one author starts at a time and its own check then holds the rest. Admission, for the claims
this module is asked about:
- an early review of a current row may use a reserved slot;
- the author of a current row is admitted only while the reserved slots and its own early
  review still fit after it (free slots > reserved + 1);
- any other AI work of the Long's clip, or run-scoped, is refused, by name and waitable,
  while free slots <= reserved, plus two while a row is dormant.
A Short's clip has no section family, so its work never waits for a Long's rows. Limits:
- the rows are known from a chunk reviewer's own request, or from the clip's recorded section
  family (``sectionFamilies``, written at its first section media reservation); before that,
  only chunk reviewers are checked, so an author or other work is admitted as before;
- a row read without its chunk request cannot see a retained early-review proof, so a reused
  early review may still count (over-reserving, never under);
- under G9 a Long with more rows than free slots cannot finish every row before M-102; the
  check then refuses by name rather than strand a started row's early review;
- a clip's family plan that cannot be read or verified refuses every claim that reads it, by
  name (fail closed; the plan must be restored or the family repaired).
"""
from __future__ import annotations

from pathlib import Path

from studio.production.section_chunk_plan import read_chunk_plan
from studio.production.section_plan import read_plan
from studio.production.section_results import rehash, require
from studio.production.task_end import end_proof
from studio.production.task_schema import LIVE, UNCLAIMED
from studio.production.tasks import TaskRefused, active_ai


def _family_context(record: dict, clip_id: str) -> dict:
    """The clip's current family plan, checked against its pin, batch and clip."""
    pin = record['clips'][clip_id]['sectionFamilies'][-1]['plan']
    rehash(pin)
    context = read_plan(Path(pin['path']))
    require(context['plan'] == pin and context['batchId'] == record['batchId'] and context['clipId'] == clip_id,
            'current chunk author plan differs from its family')
    return context


def current_assignments(record: dict, task: dict) -> tuple[dict | None, list[dict]]:
    """Read the current family's frozen assignment plan, retaining the original request fallback."""
    _plan, request = read_chunk_plan(task['sectionBinding'])
    context = request['sectionProduction']
    require(context['batchId'] == record['batchId'] and context['clipId'] == task['clipId'],
            'chunk reviewer and assignment authority differ')
    if record['clips'][task['clipId']].get('sectionFamilies', []):
        context = _family_context(record, task['clipId'])
    current = request if request['sectionProduction'] == context else None
    return current, context['assignments']


def _current_rows(record: dict, task: dict) -> list[tuple[dict, dict | None]]:
    """The current rows a claim competes with: its own clip's, or every active Long clip's for run-scoped work.

    A chunk reviewer's rows come with its request (the retained early proof included); other work reads the
    clip's current family plan alone.
    """
    if task.get('sectionBinding', {}).get('chunkPlan'):
        request, assignments = current_assignments(record, task)
        return [(row, request) for row in assignments]
    clips = [task['clipId']] if task['clipId'] else list(record['clips'])
    return [(row, None) for clip_id in clips
            if record['clips'][clip_id].get('sectionFamilies') and record['clips'][clip_id]['state'] == 'active'
            for row in _family_rows(record, clip_id, task)]


def _family_rows(record: dict, clip_id: str, task: dict) -> list[dict]:
    """The clip's current family rows; a plan that cannot be read or verified refuses by name (fail closed)."""
    try:
        return _family_context(record, clip_id)['assignments']
    except (OSError, ValueError) as error:
        raise TaskRefused(f'AI task {task["id"]} is refused: clip {clip_id}\'s current section family plan cannot be '
                          f'read or verified ({type(error).__name__}: {error}); restore the plan or repair the family '
                          'before more Long or run-scoped AI work starts') from error


def _early_task(record: dict, row: dict, request: dict | None) -> dict | None:
    """Use actual current or retained early-proof resolution, never the plan's unbound task-name prefix."""
    tasks = record['production']['tasks']
    if request is not None:
        from studio.production.sections import early_result, review_binding, review_task
        from studio.production.section_review_reuse import retained_early
        retained = retained_early(request, row, record)
        if retained is not None:
            return tasks[retained[1].task_id]
        binding, _expected = review_binding(request, row, record)
        actual = tasks.get(review_task(request['sectionProduction'], row, binding).task_id)
        if actual is not None and actual['state'] == 'completed':
            early_result(request, row, record)
        return actual
    matches = [task for task in tasks.values() if task.get('sectionBinding', {}).get('role') == 'early-review'
               and task['sectionBinding'].get('authorTaskId') == row['authorTaskId']
               and all(task['sectionBinding'].get(key) == row[key]
                       for key in ('sectionId', 'generation', 'inputIdentity', 'frameRange'))]
    # A runnable or live early review first; else an ended one, which reserves nothing (X168 P2-M1, P1-RP2 MA2):
    # a review cancelled before it ran, failed unlaunched, or (from M-102) released is never "not enqueued yet".
    return min(matches, key=lambda task: task['state'] not in (*UNCLAIMED, *LIVE), default=None)


def _dormant(author: dict | None) -> bool:
    """A row whose author has not started: none yet, or blocked or ready (X168: an ended one is not dormant)."""
    return author is None or author['state'] in UNCLAIMED


def _pending(record: dict, row: dict, request: dict | None) -> bool:
    """Whether this started row reserves a slot for its early review (one slot per such row, X125, X168).

    A live author frees its own slot for its early review only when its end would be termination evidence
    (G9); that early review cannot start before the author's result exists (its binding is read from that
    result). A completed author's early review needs a slot while it has not started (none yet, or blocked or
    ready). A row that can never progress reserves nothing: an author asked to stop or revoked (it can only end
    cancelled or superseded), an author that ended without completing (its own held slot is already counted),
    and an early review that ended or was cancelled before it ran. A dormant row reserves nothing here.
    """
    author = record['production']['tasks'].get(row['authorTaskId'])
    if _dormant(author) or author['cancelRequested'] or author['revoked']:
        return False
    if author['state'] in LIVE:
        return not end_proof(author, 'host-ended').slot_released
    if author['state'] != 'completed':
        return False
    early = _early_task(record, row, request)
    return early is None or early['state'] in UNCLAIMED


def _refusal(task: dict, free: int, reserved: list[dict], dormant: list[dict]) -> str:
    """The named, waitable refusal: who waits, for which section, and the counted slots."""
    who = 'Chunk reviewer' if task.get('sectionBinding', {}).get('chunkPlan') else 'AI task'
    section = (reserved or dormant)[0]['sectionId']
    return (f'{who} {task["id"]} must leave an AI slot for current section {section} authoring and early review '
            f'({free} free, {len(reserved)} reserved for early reviews whose author keeps its slot (G9), '
            f'{len(dormant)} section(s) not yet authored); it waits until that prerequisite work has its slots')


def reviewer_liveness_refusal(record: dict, task: dict) -> str | None:
    """Refuse an AI claim that would take a slot the current section rows still need (G9, X125, X168); None admits."""
    rows = _current_rows(record, task)
    authors = {row['authorTaskId'] for row, _request in rows}
    binding = task.get('sectionBinding') or {}
    if not rows or (binding.get('role') == 'early-review' and binding.get('authorTaskId') in authors):
        return None
    tasks = record['production']['tasks']
    free = record['production']['ai']['slots'] - active_ai(record)
    reserved = [row for row, request in rows if _pending(record, row, request)]
    dormant = [row for row, _request in rows if _dormant(tasks.get(row['authorTaskId']))]
    if task['id'] in authors:
        need = len(reserved) + 1          # its own early review joins the reserved slots once it starts
    else:
        need = len(reserved) + (2 if dormant else 0)
    if free > need:
        return None
    if task['id'] in authors:
        return (f'Section author {task["id"]} waits: after it starts, {free - 1} free slot(s) must still hold '
                f'{need} early review(s) whose author keeps its slot (G9); it waits until a slot frees')
    return _refusal(task, free, reserved, dormant)

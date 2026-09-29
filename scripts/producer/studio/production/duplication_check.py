"""C-2's recorded duplication check: overlapping source seconds are recorded, never refused on their own.

Two Shorts of one run may cut overlapping seconds of one recording and still be distinct approved jobs. When a
new Short is authorized (``add-clip`` or ``authorize_output``), every other clip whose current approved seconds
are the same Short under ``native_budget_selection.same_short`` is compared with it, and the result is one value,
``duplicationCheck`` (X121):

- ``None`` when no other clip overlaps;
- otherwise a list ordered by clip id, one row per overlapping clip:
  ``{"clip", "overlapSeconds" (the seconds both cut, millisecond precision),
  "identity": {"script": "same"|"different", "title": "same"|"different", "lineage": bool}}``.

``title`` compares the exact approved title (its SHA-256), ``script`` the script identity, and ``lineage`` says
whether the candidate's approval identity is one of that clip's earlier approvals. An effective duplicate (same
title and script, or ``lineage`` true) never reaches the check: ``outputs.same_job`` refuses it first and nothing
is written, so a recorded row always has ``lineage`` false and differs in its title or its script.

The value travels on the clip's adding event (``clip-added`` or ``output-authorized``), with no record key; status
reads it from there (``approvals.recorded_checks``). Each non-null check is also one ``coordinator-note`` decision
on the batch trail, in P3a's ``coordination-decision`` line shape (``duplication_decision``), which
``approvals.record_duplication_decision`` appends once.
"""
from __future__ import annotations

from datetime import datetime, timezone

from studio.native_budget_selection import _shared_seconds, merged, same_short
from studio.production.host_contract import clip_text

DECISION_EVENT = 'coordination-decision'   # P3a section 4.0.5; M-085's decision_log reads these lines
DECISION_PREFIX = 'duplication-check.'     # + the first 32 hex of the adding event's approval identity


def duplication_check(record: dict, clip_id: str, candidate: dict) -> list[dict] | None:
    """The recorded check of a candidate Short against the run's other clips, or None when none overlaps.

    ``candidate`` is the clip being authorized (its first approval is what it binds); a clip without an
    approval (a Long) has none. It never refuses.
    """
    first = candidate['approvals'][0] if candidate['approvals'] else None
    rows = [_compared(first, other, clip['approvals']) for other, clip in sorted(record['clips'].items())
            if first is not None and other != clip_id and clip['approvals']
            and same_short(_selection(first), _selection(clip['approvals'][-1]))]
    return rows or None


def _selection(row: dict) -> dict:
    """An approval's source and merged source seconds, the selection ``same_short`` compares."""
    return {'source': row['source'], 'ranges': merged([list(item) for item in row['ranges']])}


def _compared(first: dict, other: str, approvals: list[dict]) -> dict:
    """One row: the other clip, the seconds both cut and how the identities compare with its current approval."""
    current = approvals[-1]
    return {'clip': other, 'overlapSeconds': round(_shared_seconds(_selection(first), _selection(current)), 3),
            'identity': {'script': 'same' if first['script'] == current['script'] else 'different',
                         'title': 'same' if first['titleSha256'] == current['titleSha256'] else 'different',
                         'lineage': first['identity'] in {row['identity'] for row in approvals[:-1]}}}


def duplication_decision(record: dict, added: dict, elapsed: float) -> dict:
    """The one ``coordinator-note`` decision for an adding event whose check is not None (P3a line shape).

    ``decisionId`` is derived from the event's approval identity, which no other adding event of the run can
    carry (``same_job``). The author is the operator who recorded the output; the full check stays on the event.
    """
    clip_id, check = added['clipId'], added['duplicationCheck']
    decision = (f'Clip {clip_id} was admitted as a distinct job beside {len(check)} overlapping clip(s): '
                f'{", ".join(row["clip"] for row in check)}')
    reason = (f'C-2 duplication check, recorded as duplicationCheck on its {added["event"]} event: no overlapping clip '
              'carries its approved title and script or has it in its lineage, and overlap alone never refuses')
    author = {'role': 'operator', 'taskId': None, 'epoch': None, 'handle': None,
              'recordedBy': record['clips'][clip_id]['output']['recordedBy']}
    return {'event': DECISION_EVENT, 'decisionId': DECISION_PREFIX + added['approval'][:32], 'outputId': clip_id,
            'kind': 'coordinator-note', 'decision': clip_text(decision), 'reason': clip_text(reason),
            'author': author, 'planVersion': None, 'refs': [], 'supersedes': None, 'elapsed': round(elapsed, 3),
            'recordedAt': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}

"""C-2's job identity and its recorded duplication check: overlap is recorded, never refused on its own.

**One job (C-2, X144).** Two approvals are the same job when they have the same title, source, transcript, word
ranges and word texts (``one_job``). The derived second ranges are not part of it: they are a cut choice inside the
word gaps, not the job. Titles compare after NFC normalisation with surrounding whitespace trimmed and internal runs
collapsed (``native_budget_selection.compare_titles``: a normalization-only difference is the same title).
``outputs.same_job`` refuses a new Short that is the same job as another clip's current or earlier approval.

**The check (X121).** When a new Short is authorized (``add-clip`` or ``authorize_output``), every other clip whose
current approved seconds are the same Short under ``native_budget_selection.same_short`` is compared with it, and the
result is one value, ``duplicationCheck``:

- ``None`` when no other clip overlaps;
- otherwise a list ordered by clip id, one row per overlapping clip:
  ``{"clip", "overlapSeconds" (the seconds both cut, millisecond precision),
  "identity": {"script": "same"|"different", "title": "same"|"different", "lineage": bool}}``.

``script`` compares the words (source, transcript, word ranges and texts), ``title`` the folded title, both with that
clip's current approval; ``lineage`` says whether the candidate is the same job as one of its earlier approvals. An
effective duplicate never reaches the check (``same_job`` refuses it first and nothing is written), so a recorded row
always has ``lineage`` false and differs in its title or its words.

The value travels on the clip's adding event only, with no record key. ``recorded_checks`` reads it back for status
and replays: a clip whose adding event carries no ``duplicationCheck`` (declared at start, or written before M-052)
has no entry, never ``None`` (X50: absent is not "no overlap"). Each non-null check is also one ``coordinator-note``
decision on the batch trail in P3a's ``coordination-decision`` line shape (``duplication_decision``);
``pending_decisions`` names the ones the trail does not hold yet, so any later add, replay or status writes them.
"""
from __future__ import annotations

from datetime import datetime, timezone

from studio.native_budget_selection import _shared_seconds, compare_titles, merged, same_short
from studio.production.host_contract import clip_text

ADDING_EVENTS = ('clip-added', 'output-authorized')   # the events that bind a later clip's first approval
DECISION_EVENT = 'coordination-decision'   # P3a section 4.0.5; M-085's decision_log reads these lines
DECISION_PREFIX = 'duplication-check.'     # + the first 32 hex of the adding event's approval identity
WORDS = ('source', 'transcript', 'wordRanges', 'wordTexts')   # the script half of the job identity (no seconds)


def same_words(first: dict, second: dict) -> bool:
    """Two approval rows keep the same words of the same transcript of the same source."""
    return all(first[key] == second[key] for key in WORDS)


def same_title(first: dict, second: dict) -> bool:
    """Two approval rows carry the same title once NFC and whitespace are folded."""
    return compare_titles(first['title'], second['title']) != 'different'


def one_job(first: dict, second: dict) -> bool:
    """C-2's job identity: the same title and the same words (the derived seconds are not compared)."""
    return same_title(first, second) and same_words(first, second)


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
    """One row: the other clip, the seconds both cut and how the job identities compare with its current approval."""
    current = approvals[-1]
    return {'clip': other, 'overlapSeconds': round(_shared_seconds(_selection(first), _selection(current)), 3),
            'identity': {'script': 'same' if same_words(first, current) else 'different',
                         'title': 'same' if same_title(first, current) else 'different',
                         'lineage': any(one_job(first, row) for row in approvals[:-1])}}


def last_adding(events: list[dict] | tuple[dict, ...]) -> dict:
    """Each clip's last adding event (earlier ones were killed before their record took them)."""
    return {row['clipId']: row for row in events if row.get('event') in ADDING_EVENTS}


def recorded_checks(events: list[dict] | tuple[dict, ...]) -> dict:
    """Each added clip's recorded ``duplicationCheck``; a clip whose adding event carries none has no entry."""
    return {clip: row['duplicationCheck'] for clip, row in last_adding(events).items() if 'duplicationCheck' in row}


def pending_decisions(record: dict, events: list[dict] | tuple[dict, ...], elapsed: float) -> list[dict]:
    """The decision lines owed by recorded non-null checks of the record's clips and not yet on ``events``."""
    written = {row.get('decisionId') for row in events if row.get('event') == DECISION_EVENT}
    lines = [duplication_decision(record, row, elapsed) for clip, row in sorted(last_adding(events).items())
             if clip in record['clips'] and row.get('duplicationCheck')]
    return [line for line in lines if line['decisionId'] not in written]


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

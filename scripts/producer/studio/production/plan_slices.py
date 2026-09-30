"""Slices, change classes and changed entries of the shared plan record (P3a S2 §4.0.6; MASTER-PLAN M-081).

``plan_short_projection``'s idea applied to the plan: content digests over entries, and anything not provably local
is global. A result or task bound to version k is current for version n iff ``task_slice`` is equal in both; that
is the only currency rule, recomputed on every read and never stored. ``plan_record`` re-exports every name here.
"""
from __future__ import annotations

from cut_preview_io import digest
from studio.production.coordination_catalog import RESPONSIBILITIES, SECTION_OWNER, reads
from studio.production.plan_fields import closed
from studio.production.plan_sections import entry_rows


def entry_digest(entry: dict) -> str:
    """``digest(entry)`` (§4.0.6): the whole entry, its own ``digest`` included."""
    return digest(entry)


def responsibility_of(section: str, entry: dict) -> str:
    """The section owner, or an ``unresolved`` row's own responsibility."""
    return entry['responsibility'] if section == 'unresolved' else SECTION_OWNER[section]


def global_digest(plan: dict) -> str:
    """Approved content, clock, speech, story, sections and every global entry (§4.0.6)."""
    entries = sorted([section, entry['id'], entry_digest(entry)] for section, entry in entry_rows(plan)
                     if entry.get('isolation') == 'global')
    return digest({**{key: plan[key] for key in ('approvedContent', 'clock', 'speech', 'story', 'sections')},
                   'globalEntries': entries})


def _meets(span: list | None, scope: list | None) -> bool:
    """Half-open ranges intersect; None is the whole output."""
    return span is None or scope is None or span[0] < scope[1] and scope[0] < span[1]


def slice_digest(plan: dict, responsibility: str, scope: dict) -> str:
    """The global digest plus the responsibility's entries meeting ``scope.range`` or listed in ``scope.entryIds``."""
    closed(scope, ('range', 'entryIds'), 'scope')
    listed = set(scope['entryIds'] or ())
    entries = sorted([section, entry['id'], entry_digest(entry)] for section, entry in entry_rows(plan)
                     if responsibility_of(section, entry) == responsibility
                     and (_meets(entry['range'], scope['range']) or entry['id'] in listed))
    return digest({'global': global_digest(plan), 'entries': entries})


def task_slice(plan: dict, responsibilities: tuple[str, ...], scope: dict) -> str:
    """One digest over the slices of everything a task reads (``coordination_catalog.reads``)."""
    return digest({name: slice_digest(plan, name, scope) for name in sorted(reads(responsibilities))})


def classify(parent: dict | None, plan: dict) -> str:
    """``initial`` with no parent; ``global`` when the global digest changed; otherwise ``local``."""
    if parent is None:
        return 'initial'
    return 'global' if global_digest(parent) != global_digest(plan) else 'local'


def changed_entries(parent: dict, plan: dict) -> list[dict]:
    """``{section, id, responsibility, range}`` of every entry added, removed or changed, sorted."""
    before = {(section, entry['id']): entry for section, entry in entry_rows(parent)}
    after = {(section, entry['id']): entry for section, entry in entry_rows(plan)}
    keys = sorted(key for key in set(before) | set(after)
                  if key not in before or key not in after or entry_digest(before[key]) != entry_digest(after[key]))
    return [{'section': key[0], 'id': key[1], 'responsibility': responsibility_of(key[0], after.get(key) or before[key]),
             'range': (after.get(key) or before[key])['range']} for key in keys]


def affected_sections(parent: dict, plan: dict) -> set[str]:
    """[P4 interface] Long sections of ``plan`` whose slice for any responsibility changed from ``parent``."""
    return {row['id'] for row in plan['sections']
            if any(slice_digest(parent, name, {'range': row['range'], 'entryIds': None})
                   != slice_digest(plan, name, {'range': row['range'], 'entryIds': None}) for name in RESPONSIBILITIES)}

"""Reading a schema 5-7 budget record under schema 8 (X7, M-044): the additive lift and its one guard.

``native_budget_store.BatchSession.read`` asks, before any lift, whether a record that claims an older version
carries content only schema 8 writes (``newer_content_problem``). A genuine 5-7 record never does: this engine
writes version 8 and adds the optional production keys, the optional attempt and delivery keys and v2 capacity
clocks only under it. So such a record is refused by name, never lifted, and a lift can never hand a record
schema-8 state (a writable clock, a closure) it was not written with (P1-RP1 m4). Then ``lift_additive_fields``
supplies the older schemas' implicit fields, and nothing else, before closed validation. Both read raw JSON and
leave every other shape problem to the validator.
"""
from __future__ import annotations

from studio.native_budget_schema import LIFTED_VERSIONS, OPTIONAL_ROWS
from studio.native_budget_schema_data import CLIP_ROWS
from studio.production.production_optional import PRODUCTION_OPTIONAL
from studio.production.queue_clock_schema import POLICY as CLOCK_V2


def _newer_rows(record: dict) -> list[str]:
    """``<clip>.<row list>.<key>`` for each optional attempt or delivery key a clip row carries."""
    found = []
    clips = record.get('clips') if type(record.get('clips')) is dict else {}
    for clip_id, clip in clips.items():
        for rows, kind in CLIP_ROWS.items():
            keys = set(OPTIONAL_ROWS.get(kind, {}))
            values = clip.get(rows) if type(clip) is dict and type(clip.get(rows)) is list else []
            found += [f'{clip_id}.{rows}.{key}' for row in values if type(row) is dict
                      for key in sorted(keys & set(row))]
    return found


def newer_content_problem(record: object) -> str | None:
    """The named refusal for a record that claims version 5-7 but carries content only version 8 writes."""
    if type(record) is not dict or record.get('schemaVersion') not in LIFTED_VERSIONS:
        return None
    block = record.get('production') if type(record.get('production')) is dict else {}
    found = [f'production.{key}' for key in sorted(PRODUCTION_OPTIONAL & set(block))] + _newer_rows(record)
    clips = record.get('clips') if type(record.get('clips')) is dict else {}
    found += [f'{clip_id}.capacityClock v2' for clip_id, clip in clips.items()
              if type(clip) is dict and type(clip.get('capacityClock')) is dict
              and clip['capacityClock'].get('policy') == CLOCK_V2]
    if not found:
        return None
    return (f'claims schema {record["schemaVersion"]} but carries content only schema 8 writes '
            f'({", ".join(found[:8])}); it is refused, never lifted')


def lift_additive_fields(record: object) -> None:
    """Supply the old schema's implicit defaults before closed validation."""
    if type(record) is not dict or record.get('schemaVersion') not in LIFTED_VERSIONS:
        return
    block = record.get('production')
    if type(block) is not dict:
        return
    authorization = block.get('authorization')
    if type(authorization) is dict and set(authorization) == {'identity', 'setup', 'setupElapsed'}:
        authorization.update(prior=[], priorOmitted=0)
    tasks = block.get('tasks')
    if type(tasks) is dict:
        _lift_tasks(tasks)


def _lift_tasks(tasks: dict) -> None:
    """Infer revocation only from the previously durable terminal/stale state."""
    for row in tasks.values():
        if type(row) is dict:
            row.setdefault('owners', [])
        if type(row) is dict and 'revoked' not in row:
            row['revoked'] = row.get('state') == 'superseded' or (row.get('approvalStale') is True
                                                                  and row.get('state') != 'completed')

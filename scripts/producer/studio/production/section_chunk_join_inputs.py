"""Late full-project join evidence for one existing incremental section reviewer.

Interior chunks can be judged before neighboring authors finish. The final
review still requires independently authored judgments of every assigned global
join, bound to one registered full integration with the same frozen assignments.
This module derives inputs and validates receipts; it never writes approval.
"""
from __future__ import annotations

from pathlib import Path

from studio.native_export_history import require_current_section_attempt
from studio.native_segments.compatibility import _parent
from studio.production.section_chunk_plan import read_chunk_plan
from studio.production.section_judgments import validate_judgment
from studio.production.section_media import read_index
from studio.production.section_results import claim_directory, rehash, require
from studio.production.section_review_scope import descriptor, early_join, encoded_join
from studio.production.section_scope import join_pairs, require_full_scope

KIND = 'native-long-chunk-global-join-review'
KEYS = {'schemaVersion', 'kind', 'chunkPlan', 'request', 'judgments'}


def assigned_pairs(binding: dict) -> tuple[dict, list[tuple[dict, dict]]]:
    """Derive required global joins from the original immutable assignment plan."""
    _plan, original = read_chunk_plan(binding)
    context = original['sectionProduction']
    rows = [row for row in context['assignments'] if row['sectionId'] == binding['sectionId']]
    require(len(rows) == 1, 'chunk reviewer has no unique original assignment')
    return original, join_pairs(context, rows[0])


def full_join_request(binding: dict, pin: dict, retained: bool = False) -> dict:
    """Require exact registered full evidence; new judgments additionally need the latest attempt.

    Completed receipts may outlive their original attempt. The assembly reader
    separately compares their exact media with its current registered request.
    """
    from studio.production.section_plan import revalidate_context
    original, _pairs = assigned_pairs(binding)
    rehash(pin)
    file = Path(pin['path'])
    require(file.name == 'export-request.json', 'global joins need an immutable export request')
    request = _parent(file.parent, pin['sha256'])
    require_full_scope(request)
    if not retained:
        require_current_section_attempt(request)
    context = revalidate_context(request)
    require(context == revalidate_context(original), 'global joins belong to another assignment generation')
    require(request['revision']['canvas'] == original['revision']['canvas'],
            'global joins changed the original program clock')
    return request


def chunk_global_join_inputs(binding: dict, pin: dict, retained: bool = False) -> tuple[dict, list[dict]]:
    """Return exact existing continuous-preview and sealed-edge inputs for a real reviewer."""
    _original, pairs = assigned_pairs(binding)
    require(bool(pairs), 'this chunk reviewer has no assigned global joins')
    request = full_join_request(binding, pin, retained)
    scopes = []
    for left, right in pairs:
        name = f"join:{left['sectionId']}:{right['sectionId']}"
        scopes.append(descriptor(f'early-{name}', [left, right], early_join(request, left, right)))
        scopes.append(descriptor(f'encoded-{name}', [left, right], encoded_join(request, left, right)))
    return request, scopes


def validate_chunk_global_joins(record: dict, task: dict, pin: dict | None) -> list[dict]:
    """Validate a claim-owned authored join receipt without manufacturing any judgment."""
    binding = task['sectionBinding']
    _original, pairs = assigned_pairs(binding)
    if not pairs:
        require(pin is None, 'unassigned global join approval is not accepted')
        return []
    require(type(pin) is dict and pin.get('path') == str(claim_directory(task) / 'global-joins.json'),
            'required global join review must belong to the current reviewer claim')
    document = read_index(pin)
    require(set(document) == KEYS and type(document['schemaVersion']) is int
            and document['schemaVersion'] == 1 and document['kind'] == KIND
            and document['chunkPlan'] == binding['chunkPlan'], 'global join review binding differs')
    request, expected = chunk_global_join_inputs(binding, document['request'], retained=task['state'] == 'completed')
    judgments = document['judgments']
    require(type(judgments) is list and len(judgments) == len(expected),
            'global join review omits required stages or boundaries')
    from studio.production.section_join_barrier import check_authors
    from studio.production.sections import integrated_author
    for judgment, scope in zip(judgments, expected):
        validate_judgment(judgment, scope)
        check_authors(record, task, scope['sections'])
    involved = {section['sectionId'] for scope in expected for section in scope['sections']}
    for row in request['sectionProduction']['assignments']:
        if row['sectionId'] in involved:
            integrated_author(request, row, record)
    return expected

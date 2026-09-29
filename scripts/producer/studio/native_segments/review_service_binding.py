"""Immutable operational envelopes beside existing private batch authority.

These files grant no work and never enter creative/source identity. Only an
existing family's pin selects one; unreferenced preparations have no authority.
Runtime conditions are currently unavailable at pre-preparation admission, so
public freezing selects conservative rates until that separate proof is wired.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from cut_preview_io import MAX_JSON
from headless.durable_files import read_private_file, write_pending_replace
from native_work_service_pins import identity, require
from native_work_service_rates import RateCatalog
from studio.native_budget_store import batch_directory, canonical

KIND = 'native-long-review-service-binding'


def planned_binding(project: Path, context: dict) -> dict | None:
    """Derive prospective geometry without pretending current runtime conditions exist."""
    from studio.native_segments.review_service import planned_service
    evidence = planned_service(project, context, RateCatalog(rejected='Runtime conditions are not admitted'))
    if evidence is None:
        return None
    return {'schemaVersion': 1, 'kind': KIND,
            **{key: context[key] for key in ('batchId', 'clipId', 'plan', 'sharedPlan')}, 'envelope': evidence}


def inherited_binding(record: dict, context: dict) -> tuple[bool, dict | None]:
    """A preview and final share one frozen selection; legacy families remain legacy."""
    families = [row for row in record['clips'][context['clipId']].get('sectionFamilies', [])
                if row['plan'] == context['plan']]
    if not families:
        return False, None
    bindings = [row.get('reviewService') for row in families]
    require(all(row == bindings[0] for row in bindings), 'Family service bindings disagree')
    return True, bindings[0]


def freeze_binding(session: object, context: dict, value: dict) -> dict:
    """Publish one bounded derived file atomically under the already held batch lock."""
    data = canonical(value)
    require(len(data) <= MAX_JSON, 'Service envelope exceeds existing JSON bound')
    name = f'long-review-service-{hashlib.sha256(data).hexdigest()}.json'
    try:
        os.stat(name, dir_fd=session.dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        write_pending_replace(session.dir_fd, (name + '.pending', name), data)
    retained = read_private_file(session.dir_fd, name, MAX_JSON)
    require(retained == data, 'Immutable service envelope changed')
    file = batch_directory(Path(context['authority']), context['batchId']) / name
    return {'schemaVersion': 1, 'envelope': {'path': str(file), 'sha256': hashlib.sha256(data).hexdigest(),
                                          'bytes': len(data)}}


def read_binding(session: object, context: dict, binding: dict) -> dict:
    """Reopen exactly the family-selected private artifact; no missing/corrupt fallback."""
    from studio.native_budget_family_schema import service_ok
    require(service_ok(binding), 'Malformed service binding')
    pin = binding['envelope']
    file = batch_directory(Path(context['authority']), context['batchId']) / f"long-review-service-{pin['sha256']}.json"
    require(str(file) == pin['path'], 'Service envelope is outside its batch namespace')
    data = read_private_file(session.dir_fd, file.name, MAX_JSON)
    require(len(data) == pin['bytes'] and hashlib.sha256(data).hexdigest() == pin['sha256'],
            'Service envelope pin changed')
    value = json.loads(data)
    require(set(value) == {'schemaVersion', 'kind', 'batchId', 'clipId', 'plan', 'sharedPlan', 'envelope'}
            and type(value['schemaVersion']) is int and value['schemaVersion'] == 1 and value['kind'] == KIND
            and all(value[key] == context[key] for key in ('batchId', 'clipId', 'plan', 'sharedPlan')),
            'Service envelope belongs to different section authority')
    evidence = value['envelope']
    require(type(evidence) is dict and evidence.get('kind') == 'native-long-review-service-envelope'
            and evidence.get('identity') == identity({key: item for key, item in evidence.items() if key != 'identity'}),
            'Service envelope identity changed')
    return evidence


def prepare_admission(session: object, record: dict, settings: dict) -> None:
    """Prepare service evidence before the caller refreshes its original clock.

    The caller holds the batch lock; no budget counter, grant or clock is changed.
    Missing runtime/cell eligibility falls back, while corrupt declared evidence
    refuses. Preview outcomes never reduce this prospective final-work estimate.
    """
    context = settings['context']
    from studio.production.section_plan import require_context
    require_context(record, context)
    inherited, binding = inherited_binding(record, context)
    if not inherited and settings.get('plannedService') is not None:
        binding = freeze_binding(session, context, settings['plannedService'])
    settings['reviewService'] = binding
    settings['reviewServiceSeconds'] = None
    if binding is None:
        return
    evidence = read_binding(session, context, binding)
    from native_work_pool_policy import host_identity
    from native_work_service_rates import read_service_rates
    from studio.native_segments.review_service_estimate import estimate_service
    from studio.native_segments.review_service_plan import remaining_selection
    catalog = read_service_rates(host_identity()) if evidence['conditions'] is not None else RateCatalog()
    result = estimate_service(evidence, catalog, remaining_selection(evidence))
    settings['reviewServiceSeconds'] = result['seconds']

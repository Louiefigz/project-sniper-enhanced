"""The shared plan record: shape, exact bytes, digests, slices and change classes (P3a S2 §4.0.2, §4.0.6; M-081).

``validate_plan_record`` checks the closed shape, every bound, the format's section rules, unique entry ids and the
1,048,576-byte canonical size; ``read_plan_record`` reads a pinned record as its exact canonical bytes
(``canonical_compact_json`` + ``\\n``) and refuses changed or non-canonical bytes. ``approved_content_problem`` and
``homes_problem`` are freeze-time checks: the first reuses ``role_packet_given.bound_facts`` exactly as role packets
call it (never a text comparison), the second rehashes the homes and recomputes ``role_packet_native.plan_hash``.
Slices follow §4.0.6 (``plan_slices``, re-exported here): a task bound to version k is current for version n iff
its ``task_slice`` is equal in both.
Checks that need the ledger or the trail (contributions, conflicts, decisions, caps, ``changeClass`` against the
parent) belong to the steps that own those readers (S6-S8); ``require_sections`` waits for S12.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from cross_runtime_canonical_json import canonical_compact_json
from cut_preview_io import read_bytes
from studio.native_short_regions import REGIONS
from studio.production.coordination_catalog import BOUNDS, PLAN_BOUNDS
from studio.production.plan_fields import (
    PREFIX, check, closed, contiguous, frame_range, hex64, identifier, identifiers, maybe_pin, nesting_problem, pin, pins,
    raw_depth, read_pinned_json, refuse, rows,
)
from studio.production.plan_sections import (
    entry_digest_problem, entry_rows, validate_audio, validate_captions, validate_conflicts, validate_contributions,
    validate_framing, validate_graphics, validate_holds, validate_ownership, validate_source_facts, validate_story,
    validate_transitions, validate_unresolved, validate_work_plan,
)
from studio.production.plan_slices import (  # noqa: F401  re-exported: P3a names them on plan_record
    affected_sections, changed_entries, classify, entry_digest, global_digest, responsibility_of, slice_digest,
    task_slice,
)
from studio.production.section_results import TOKEN, canonical_path, matches

KIND = 'sniper-coordination-plan'
TOP_KEYS = ('schemaVersion', 'kind', 'batchId', 'outputId', 'format', 'version', 'parent', 'integration',
            'approvedContent', 'homes', 'inputs', 'clock', 'speech', 'sections', 'story', 'holds', 'framing',
            'captions', 'graphics', 'transitions', 'audio', 'sourceFacts', 'unresolved', 'ownership', 'contributions',
            'conflicts', 'workPlan', 'decisions', 'changeClass')
HOME_KEYS = ('nativePlan', 'project', 'planHash', 'regions', 'sharedEvidence', 'longChunks')
SPEECH_KEYS = ('occurrencesSha256', 'cutsSha256', 'segmentsSha256')
CHANGE_CLASSES = ('initial', 'local', 'global')
PASSING_TITLES = ('exact', 'normalization-only')


def _frame_rate(value: object) -> bool:
    """``N/D`` with positive integers and no leading zero."""
    parts = value.split('/') if type(value) is str else []
    return len(parts) == 2 and all(part.isdigit() and part.isascii() and part[0] != '0' for part in parts)


def _header(plan: dict) -> None:
    """Kind, ids, format, the version chain, the integration claim and the approved-content identities."""
    check(type(plan['schemaVersion']) is int and plan['schemaVersion'] == 1 and plan['kind'] == KIND, 'shape',
          f'not a schema-1 {KIND}')
    identifier(plan['batchId'], 'batchId')
    identifier(plan['outputId'], 'outputId')
    check(plan['format'] in ('short', 'long'), 'format', 'must be short or long')
    version, parent = plan['version'], plan['parent']
    check(type(version) is int and 1 <= version <= BOUNDS['planVersions'], 'version',
          f'must be 1..{BOUNDS["planVersions"]}')
    check((parent is None) == (version == 1), 'parent', 'is null exactly at version 1')
    if parent is not None:
        closed(parent, ('version', 'sha256'), 'parent')
        check(type(parent['version']) is int and parent['version'] == version - 1, 'parent', 'must be version - 1')
        hex64(parent['sha256'], 'parent')
    check(plan['changeClass'] in CHANGE_CLASSES and (plan['changeClass'] == 'initial') == (parent is None),
          'changeClass', 'is initial exactly at version 1, else local or global')
    claim = closed(plan['integration'], ('taskId', 'epoch', 'token'), 'integration')
    identifier(claim['taskId'], 'integration')
    check(type(claim['epoch']) is int and claim['epoch'] >= 1 and matches(claim['token'], TOKEN), 'integration',
          'needs the claim epoch and its 32-hex token')
    keys = ('approvalIdentity', 'titleSha256', 'scriptSha256') if plan['format'] == 'short' else ('outputIdentity',)
    for key in closed(plan['approvedContent'], keys, 'approvedContent'):
        hex64(plan['approvedContent'][key], 'approvedContent')


def _homes(plan: dict) -> None:
    """A Short's executable homes (native plan under its project, plan hash, regions, evidence); a Long has none."""
    homes = closed(plan['homes'], HOME_KEYS, 'homes')
    maybe_pin(homes['sharedEvidence'], 'homes')
    maybe_pin(homes['longChunks'], 'homes')
    if plan['format'] == 'long':
        check(all(homes[key] is None for key in HOME_KEYS[:4]), 'homes', 'a Long has no native plan home')
        return
    check(homes['longChunks'] is None, 'homes', 'a Short pins no Long chunks')
    try:
        project = canonical_path(homes['project'])
    except ValueError as error:
        refuse('homes', f'project: {error}')
    check(pin(homes['nativePlan'], 'homes')['path'] == str(project / 'SHORT-PROJECT.json'), 'homes',
          'nativePlan must be <project>/SHORT-PROJECT.json')
    hex64(homes['planHash'], 'homes')
    check(maybe_pin(homes['regions'], 'homes') is None or homes['regions']['path'] == str(project / REGIONS), 'homes',
          f'regions must be <project>/{REGIONS}')


def _clock(plan: dict) -> dict:
    """The frame clock, the Short's speech digests and a Long's 1..3 contiguous sections."""
    clock = closed(plan['clock'], ('frameRate', 'totalFrames'), 'clock')
    total = clock['totalFrames']
    check(_frame_rate(clock['frameRate']) and type(total) is int and 1 <= total <= PLAN_BOUNDS['totalFrames'], 'clock',
          f'needs frameRate N/D and totalFrames 1..{PLAN_BOUNDS["totalFrames"]}')
    if plan['format'] == 'short':
        for key in closed(plan['speech'], SPEECH_KEYS, 'speech'):
            hex64(plan['speech'][key], 'speech')
        check(plan['sections'] == [], 'sections', 'a Short has no sections')
        return clock
    check(plan['speech'] is None, 'speech', 'a Long has no derived speech')
    for row in rows(plan['sections'], 'sections', (1, PLAN_BOUNDS['sections'])):
        closed(row, ('id', 'range'), 'sections')
        frame_range(row['range'], clock, 'sections')
    identifiers([row['id'] for row in plan['sections']], 'sections', (1, PLAN_BOUNDS['sections']))
    contiguous([row['range'] for row in plan['sections']], clock, 'sections')
    return clock


def _covers(outer: list | None, inner: list) -> bool:
    """Whether a range (None = whole output) holds another."""
    return outer is None or outer[0] <= inner[0] and inner[1] <= outer[1]


def _long_rules(plan: dict) -> None:
    """A graphic not known feasible needs a blocking gap over its frames; a transition across sections is integration's."""
    blocking = [row['range'] for row in plan['unresolved']
                if row['responsibility'] == 'graphics-motion' and row['blocks'] in ('final', 'execution')]
    for rule in plan['graphics']:
        check(rule['feasibility'] == 'feasible' or any(_covers(span, rule['range']) for span in blocking), 'graphics',
              f'{rule["id"]} is {rule["feasibility"]}: an unresolved graphics-motion row blocking final or execution '
              'must cover its frames')
    edges = [row['range'][0] for row in plan['sections'][1:]]
    owner = {'task': plan['integration']['taskId']}
    for transition in plan['transitions']:
        start, end = transition['range']
        check(not any(start < edge < end for edge in edges) or transition['owner'] == owner, 'transitions',
              f'{transition["id"]} crosses a section boundary, so the integration task owns it')


def _sections(plan: dict, clock: dict) -> None:
    """Every content section, then the cross-section Long rules and unique entry ids."""
    authored, sections = plan['format'] == 'long', plan['sections']
    validate_story(plan['story'], clock)
    validate_framing(plan['framing'], clock)
    validate_captions(plan['captions'], clock, authored)
    validate_graphics(plan['graphics'], clock, authored)
    validate_transitions(plan['transitions'], clock, sections, authored)
    validate_audio(plan['audio'], clock, plan['inputs'], authored)
    validate_source_facts(plan['sourceFacts'], clock)
    validate_unresolved(plan['unresolved'], clock)
    others = [row['id'] for section in ('story', 'framing', 'captions', 'graphics', 'transitions', 'audio',
                                        'sourceFacts') for row in plan[section]]
    validate_holds(plan['holds'], set(others), clock, authored)
    ids = [entry['id'] for _section, entry in entry_rows(plan)]
    repeated = sorted({item for item in ids if ids.count(item) > 1})
    check(not repeated, 'entry ids', f'repeat across sections: {repeated[:8]}')
    if authored:
        _long_rules(plan)
    problem = entry_digest_problem(plan)
    if problem is not None:
        raise ValueError(problem)


def validate_plan_record(value: object) -> dict:
    """The closed record: keys, size, header, homes, clock, sections and coordination-only sections (§4.0.2).

    Raises:
        ValueError: ``Coordination plan: <rule>: <detail>`` for the first refused field.
    """
    problem = nesting_problem(value, BOUNDS['planDepth'])
    check(problem is None, 'shape', f'the record {problem}')
    plan = closed(value, TOP_KEYS, 'shape')
    try:
        size = len(canonical_compact_json(plan).encode())
    except ValueError as error:
        refuse('shape', f'not canonical JSON: {error}')
    check(size <= BOUNDS['planRecordBytes'], 'size', f'{size} canonical bytes exceed {BOUNDS["planRecordBytes"]}')
    _header(plan)
    _homes(plan)
    pins(plan['inputs'], 'inputs')
    clock = _clock(plan)
    _sections(plan, clock)
    validate_ownership(plan['ownership'], clock, plan['sections'])
    validate_contributions(plan['contributions'])
    validate_conflicts(plan['conflicts'], clock)
    validate_work_plan(plan['workPlan'], plan['version'])
    identifiers(plan['decisions'], 'decisions', (0, PLAN_BOUNDS['decisions']))
    return plan


def read_plan_record(record_pin: dict) -> dict:
    """Read a pinned record as exact canonical bytes (no link, no duplicate key, no other spacing), then validate it."""
    found = pin(record_pin, 'read')
    limit = BOUNDS['planRecordBytes'] + 1
    check(found['bytes'] <= limit, 'size', f'a plan record is at most {limit} bytes')
    try:
        raw = read_bytes(Path(found['path']), limit)
    except (OSError, RuntimeError, ValueError) as error:
        refuse('read', f'plan record cannot be read: {error}')
    check(len(raw) == found['bytes'] and hashlib.sha256(raw).hexdigest() == found['sha256'], 'read',
          'plan record bytes changed')
    check(raw_depth(raw) <= BOUNDS['planDepth'], 'read', f'plan record nests deeper than {BOUNDS["planDepth"]} levels')
    try:
        value = json.loads(raw)
        canonical = (canonical_compact_json(value) + '\n').encode()
    except ValueError as error:
        refuse('read', f'plan record is not JSON: {error}')
    check(canonical == raw, 'read', 'plan record is not exact canonical JSON (duplicate keys, spacing or key order)')
    return validate_plan_record(value)


def approved_content_problem(record: dict, plan: dict) -> str | None:
    """The plan names the authority's current approval, and its native plan reopens no approved word or title (A5)."""
    clip = record['clips'].get(plan['outputId'])
    if clip is None:
        return f'{PREFIX}: approvedContent: output {plan["outputId"]} is not in batch {record["batchId"]}'
    if plan['format'] == 'long':
        wanted = {'outputIdentity': (clip.get('output') or {}).get('identity')}
        return None if plan['approvedContent'] == wanted else \
            f'{PREFIX}: approvedContent: plan v{plan["version"]} does not name the output identity'
    if not clip['approvals']:
        return f'{PREFIX}: approvedContent: output {plan["outputId"]} has no approved title and script'
    current = clip['approvals'][-1]
    wanted = {'approvalIdentity': current['identity'], 'titleSha256': current['titleSha256'],
              'scriptSha256': current['script']}
    if plan['approvedContent'] != wanted:
        return f'{PREFIX}: approvedContent: plan v{plan["version"]} does not name the current approval'
    return _reopened(record, plan, current)


def _reopened(record: dict, plan: dict, current: dict) -> str | None:
    """Run the existing approved-content comparison (``role_packet_given.bound_facts``) on the frozen native plan."""
    from role_packet_files import ArtifactError
    from role_packet_given import bound_facts
    reopens = f'{PREFIX}: plan v{plan["version"]} reopens approved content'
    native = read_pinned_json(plan['homes']['nativePlan'], 'approvedContent')
    found = {'current': current, 'batchId': record['batchId'], 'clipId': plan['outputId'], 'status': record['status']}
    try:
        facts = bound_facts(found, native)
    except (ArtifactError, OSError, RuntimeError) as error:
        return f'{reopens}: {error}'
    title = facts['title']
    failing = [] if title['status'] in PASSING_TITLES else \
        [f'title {title["status"]} (given {title["given"]!r}, planned {title["planned"]!r})']
    failing += [f'{name} {facts[name]["details"]}' for name in ('selection', 'captionText', 'timing')
                if not facts[name]['matches']]
    return f'{reopens}: {"; ".join(failing)}' if failing else None


def homes_problem(plan: dict) -> str | None:
    """Freeze-time: every home pin rehashes, ``planHash`` is the native plan's, regions and evidence are the plan's."""
    try:
        _check_homes(plan)
    except ValueError as error:
        return str(error)
    return None


def _check_homes(plan: dict) -> None:
    """``homes_problem`` raising its refusal."""
    from role_packet_native import plan_hash
    homes = plan['homes']
    for key in ('regions', 'sharedEvidence', 'longChunks'):
        if homes[key] is not None:
            read_pinned_json(homes[key], 'homes')
    if plan['format'] == 'long':
        return
    native = read_pinned_json(homes['nativePlan'], 'homes')
    check(plan_hash(native) == homes['planHash'], 'homes', 'planHash is not the native plan hash')
    check((homes['regions'] is not None) == (Path(homes['project']) / REGIONS).is_file(), 'homes',
          f'regions are pinned exactly when the project has {REGIONS}')
    bound = native.get('sharedEvidence')
    check(bound is None or type(bound) is dict and all(type(bound.get(key)) is str for key in ('path', 'sha256')), 'homes',
          "the native plan's sharedEvidence binding is malformed")
    named = None if bound is None else (bound['path'], bound['sha256'])
    pinned = None if homes['sharedEvidence'] is None else (homes['sharedEvidence']['path'], homes['sharedEvidence']['sha256'])
    check(named == pinned, 'homes', 'sharedEvidence must pin the sealed record the native plan binds')

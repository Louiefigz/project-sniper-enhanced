"""Typed media requests of production tasks, and the exporter child's acknowledgement of its claim.

A media task row stores no command. ``enqueue`` validates one typed request document
(``native-media-request``): the project, a new attempt directory that does not exist yet, one
delivering route and allowlisted options only (``PATH_OPTIONS``/``SWITCH_OPTIONS``);
``exporter_arguments`` maps it to the public exporter's own arguments, and ``check_route`` requires
the exporter's own parser and option checks to accept them and derive the same route (again at
``run-media``). A preview is not a media task: its success
leaves no delivery row in the authority, which is the only evidence a task completes from.
Enqueue then computes the launch's pre-preparation input identity (authored project bytes, route,
options, engine: ``native_budget_binding.input_identity``) and keeps the exact request and that
identity privately (``<authority root>/dispatch/<batch>/requests/<task>.json`` and ``.identity``).
The task's input fingerprint is ``task_schema.launch_fingerprint`` of both, so the reservation
(``claims.check_launch``) refuses a launch whose request or rendered inputs changed after enqueue.

Inside the exporter child, ``task_execution`` acknowledges the claim with the child's own exact
process identity before any preparation. The child never records an outcome: the watchdog
settles the task once, after the child's whole process group is gone (``process_settle``).
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from headless.durable_files import (
    DurableFileError, open_private_dir, private_child_dir, read_private_file, write_pending_replace,
)
from studio import native_budget_store as store
from studio.native_budget_schema import ROUTES, SHA256
from studio.native_budget_store import BudgetAuthorityError, ensure_root, require_batch_id, require_clip_id
from studio.production import api
from studio.native_budget_binding import launch_fingerprint
from studio.production.tasks import TASK_ID, TaskRefused

REQUEST_KIND = 'native-media-request'
MAX_REQUEST_BYTES = 64 * 1024
REQUEST_KEYS = frozenset({'schemaVersion', 'kind', 'batchId', 'taskId', 'clipId', 'route', 'project', 'output',
                          'options'})
# Path options. ``cache`` names the private source-frame store (a new empty folder is a cold-cache run);
# ``reviseFrom`` is the revision route (``--revise-from ATTEMPT``): the exporter's own parser and option
# checks accept or refuse it, so it is refused while that route is not in this engine.
PATH_OPTIONS = {'previewReviews': '--preview-reviews', 'promoteDraft': '--promote-draft',
                'verifyFrom': '--verify-from', 'resumeFrom': '--resume-from', 'previewFrom': '--preview-from',
                'draftFindings': '--draft-findings', 'audioStage': '--audio-stage', 'referenceMap': '--reference-map',
                'cache': '--cache', 'reviseFrom': '--revise-from'}
SWITCH_OPTIONS = {'cachedNativeBatches': '--cached-native-batches', 'sdkStreaming': '--sdk-streaming',
                  'acquireSourceCache': '--acquire-source-cache'}
ROUTE_SWITCHES = {'preview': ('--preview-only',), 'draft': ('--review-draft',)}
REQUIRED = {'final': ('previewReviews',), 'promote': ('promoteDraft', 'previewReviews'),
            'verify': ('verifyFrom',), 'resume': ('resumeFrom',)}
ROUTES_DELIVERING = tuple(route for route in ROUTES if route != 'preview')
STATE, REQUESTS, LOGS = 'dispatch', 'requests', 'logs'


def _unique(pairs: list) -> dict:
    """A JSON object whose keys are distinct."""
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError('duplicate JSON key')
    return dict(pairs)


def parse_json(data: bytes, where: str) -> dict:
    """One JSON object (UTF-8, no duplicate keys, no NaN/Infinity)."""
    def refuse(name: str) -> None:
        """NaN and Infinity are not typed input."""
        raise ValueError(f'{where} holds {name}')
    try:
        value = json.loads(data.decode('utf-8'), object_pairs_hook=_unique, parse_constant=refuse)
    except (UnicodeError, ValueError) as error:
        raise ValueError(f'{where} is not a JSON object: {error}') from error
    if type(value) is not dict:
        raise ValueError(f'{where} is not a JSON object')
    return value


def _absolute(value: object, name: str) -> str:
    """An absolute, normalized path string without control characters."""
    if type(value) is not str or not value.startswith('/') or os.path.normpath(value) != value \
            or any(ord(char) < 32 for char in value) or len(value) > 1024:
        raise ValueError(f'a media request names {name} as an absolute normalized path')
    return value


def _options(route: str, options: object) -> None:
    """Allowlisted options with typed values, and the options the route requires."""
    if type(options) is not dict or not set(options) <= set(PATH_OPTIONS) | set(SWITCH_OPTIONS):
        allowed = ', '.join(sorted(PATH_OPTIONS) + sorted(SWITCH_OPTIONS))
        raise ValueError(f'media request options are an object of allowlisted keys ({allowed})')
    for key, value in options.items():
        if key in SWITCH_OPTIONS and value is not True:
            raise ValueError(f'media request option {key} is true or absent')
        if key in PATH_OPTIONS:
            _absolute(value, key)
    missing = [key for key in REQUIRED.get(route, ()) if key not in options]
    if missing:
        raise ValueError(f'a {route} media request needs {", ".join(missing)}')


def parse_request(data: bytes, where: str) -> dict:
    """A validated ``native-media-request`` (closed keys, one route, allowlisted options)."""
    request = parse_json(data, where)
    if set(request) != REQUEST_KEYS or request['schemaVersion'] != 1 or request['kind'] != REQUEST_KIND:
        raise ValueError(f'{where} is not a {REQUEST_KIND} with exactly {", ".join(sorted(REQUEST_KEYS))}')
    require_batch_id(request['batchId'])
    require_clip_id(request['clipId'])
    if type(request['taskId']) is not str or TASK_ID.fullmatch(request['taskId']) is None:
        raise ValueError(f'{where} names no task id')
    if request['route'] not in ROUTES_DELIVERING:
        raise ValueError(f'{where} names route {request["route"]!r}; media tasks deliver an MP4 '
                         f'({", ".join(ROUTES_DELIVERING)}); run previews with native_export.py --preview-only')
    _absolute(request['project'], 'project')
    _absolute(request['output'], 'output')
    _options(request['route'], request['options'])
    return request


def exporter_arguments(request: dict) -> list[str]:
    """The public exporter's arguments for this request: PROJECT OUTPUT, route switch, options."""
    arguments = [request['project'], request['output'], *ROUTE_SWITCHES.get(request['route'], ())]
    for key in sorted(request['options']):
        arguments += [PATH_OPTIONS[key], request['options'][key]] if key in PATH_OPTIONS else [SWITCH_OPTIONS[key]]
    return arguments


def check_route(arguments: list[str], route: str) -> None:
    """The exporter's own parser and option checks accept these arguments and derive exactly this route."""
    from studio.native_budget_exporter import launch_route
    from studio.native_short_export import parser, source_cache_mode, validate_options
    message = io.StringIO()
    try:
        with contextlib.redirect_stderr(message):
            args = parser().parse_args(arguments)
    except SystemExit as error:  # argparse refuses unknown or conflicting options by exiting
        reason = message.getvalue().strip().splitlines()[-1:] or ['']
        raise ValueError(f'the exporter refuses these arguments ({reason[0]})') from error
    try:
        validate_options(args, args.project.resolve(strict=True), args.output.absolute())
        source_cache_mode(args)
    except (RuntimeError, OSError) as error:
        raise ValueError(f'the exporter refuses these arguments ({type(error).__name__}: {error})') from error
    derived = launch_route(args)
    if derived != route:
        raise ValueError(f'these exporter arguments launch route {derived}, not the task\'s {route}')


def _private_child(parent: Path, name: str) -> None:
    """Create or admit one owned mode-0700 child directory of a private directory."""
    fd = open_private_dir(str(parent))
    try:
        os.close(private_child_dir(fd, name))
    finally:
        os.close(fd)


def batch_state(root: Path, batch_id: str) -> Path:
    """The batch's private dispatcher state directory (created with its requests and logs children)."""
    ensure_root(root)
    directory = root / STATE / require_batch_id(batch_id)
    try:
        for parent, name in ((root, STATE), (root / STATE, batch_id), (directory, REQUESTS), (directory, LOGS)):
            _private_child(parent, name)
    except (DurableFileError, OSError) as error:
        raise BudgetAuthorityError(f'Dispatcher state for {batch_id} is unusable: {error}') from error
    return directory


def input_identity(request: dict) -> str:
    """The launch's pre-preparation input identity, exactly as its reservation will compute it."""
    from studio.native_budget_binding import input_identity as launch_identity
    from studio.native_budget_exporter import launch_options
    from studio.native_short_export import parser
    options = launch_options(parser().parse_args(exporter_arguments(request)))
    return launch_identity(Path(request['project']), request['route'], options)


def _require_short(project: Path, where: str) -> None:
    """A media task runs the Short exporter under Short deadlines: another format's project is refused."""
    from studio.native_export import export_adapter
    try:
        adapter = export_adapter(project.resolve(strict=True))
    except (RuntimeError, OSError) as error:
        raise ValueError(f'{where} names project {project}, which declares no native format: {error}') from error
    if adapter != 'native-short':
        raise ValueError(f'{where} names a {adapter} project: media tasks run the Short exporter under Short '
                         'deadlines, and this engine binds no other format')


def admit_request(data: bytes, where: str) -> tuple[dict, str, str]:
    """(request, request SHA-256, input identity) of a request enqueue may keep; refused when not admissible."""
    request = parse_request(data, where)
    _require_short(Path(request['project']), where)
    output = Path(request['output'])
    if output.exists() or output.is_symlink():
        raise ValueError(f'{where} names output {output}, which already exists: a media task writes a new '
                         'attempt directory')
    check_route(exporter_arguments(request), request['route'])
    return request, hashlib.sha256(data).hexdigest(), input_identity(request)


def store_request(root: Path, batch_id: str, task_id: str, kept: tuple[bytes, str]) -> None:
    """Keep the enqueued request bytes and input identity privately under the task id (identical copies stay)."""
    data, identity = kept
    current = stored_request(root, batch_id, task_id)
    if current is not None and (current[1], current[2]) == (hashlib.sha256(data).hexdigest(), identity):
        return
    fd = open_private_dir(str(batch_state(root, batch_id) / REQUESTS))
    try:
        write_pending_replace(fd, (f'.{task_id}.identity.pending', f'{task_id}.identity'), identity.encode())
        write_pending_replace(fd, (f'.{task_id}.pending', f'{task_id}.json'), data)
    finally:
        os.close(fd)


def stored_request(root: Path, batch_id: str, task_id: str) -> tuple[dict, str, str] | None:
    """(request, SHA-256 of its exact bytes, kept input identity) for this task, or None when none is kept."""
    directory = root / STATE / require_batch_id(batch_id) / REQUESTS
    if not (directory / f'{task_id}.json').is_file() or not (directory / f'{task_id}.identity').is_file():
        return None
    fd = open_private_dir(str(directory))
    try:
        data = read_private_file(fd, f'{task_id}.json', MAX_REQUEST_BYTES)
        identity = read_private_file(fd, f'{task_id}.identity', 128).decode('ascii')
    finally:
        os.close(fd)
    request = parse_request(data, f'the media request of task {task_id}')
    return request, hashlib.sha256(data).hexdigest(), identity


def check_request(task: dict, request: dict, request_sha256: str, identity: str) -> None:
    """The kept request and identity are exactly the ones this media task was enqueued with."""
    if task['kind'] != 'media' or SHA256.fullmatch(identity) is None \
            or launch_fingerprint(request_sha256, identity) != task['inputFingerprint'] \
            or (request['taskId'], request['clipId'], request['route']) != (task['id'], task['clipId'], task['route']):
        raise TaskRefused(f'The kept media request is not the one media task {task["id"]} was enqueued with')


@contextmanager
def task_execution(task: object) -> Iterator[bool]:
    """Acknowledge the claim with this process's exact identity before any work; yield whether to proceed.

    The claim is fenced (refused) when it was released, re-claimed or reconciled as uncertain; a
    stop requested before the acknowledgement yields False. The watchdog records every outcome.
    """
    from studio.production.process import own_process
    attached = api.attach_task(store.default_root(), task.batch_id, task.ref(), own_process())
    yield bool(attached['proceed'])

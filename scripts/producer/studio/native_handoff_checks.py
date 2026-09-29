"""Loopback checks that a hand-off's views really serve its exact project and MP4.

A Studio URL or a record file proves nothing on its own. ``studio_served`` asks the running
server which process and project it is (``/__hyperframes_config``), then performs the loads
Studio's page performs: the main preview and every sub-composition preview. Those are the same
requests on which pinned Studio stamps missing ``data-hf-id`` values and rewrites project files,
so the caller hashes the delivered project after this returns. ``player_row`` reads the review
player's ``/inventory.json`` for the attempt and requests its exact media route. Only 127.0.0.1
is ever contacted; nothing here opens a browser, plays media or approves anything.
"""
from __future__ import annotations

import http.client
import json
import time
from pathlib import Path
from urllib.parse import quote, urlsplit

from studio.studio_server import ServerRecord

HOST = '127.0.0.1'
JSON_LIMIT = 8 * 1024 * 1024
HTML_LIMIT = 64 * 1024 * 1024
MAX_COMPOSITIONS = 256
DEFAULT_LOAD_SECONDS = 45.0
TOOL_AGENT = 'sniper-native-handoff'  # this module's own requests, never counted as a browser's
CHECK_ERRORS = (OSError, http.client.HTTPException, ValueError, KeyError, TypeError)


class ViewCheckError(ValueError):
    """A live view answered, but not as the exact project or MP4 it must show."""


def expect(value: bool, message: str) -> None:
    """Refuse one failed view condition with its plain reason."""
    if not value:
        raise ViewCheckError(message)


def fetch(port: int, target: tuple[str, str], limit: int, deadline: float) -> tuple[int, dict, int, bytes]:
    """One loopback request: (status, headers, byte count, body kept up to ``limit``)."""
    method, path = target
    remaining = deadline - time.monotonic()
    expect(remaining > 0, f'view check deadline passed before {path}')
    connection = http.client.HTTPConnection(HOST, port, timeout=remaining)
    try:
        connection.request(method, path, headers={'User-Agent': TOOL_AGENT})
        response = connection.getresponse()
        body, size = bytearray(), 0
        while chunk := response.read(1 << 20):
            size += len(chunk)
            expect(size <= limit, f'{path} answered more than {limit} bytes')
            expect(time.monotonic() < deadline, f'view check deadline passed while reading {path}')
            body += chunk
        return response.status, {key.lower(): value for key, value in response.getheaders()}, size, bytes(body)
    finally:
        connection.close()


def fetch_json(port: int, path: str, deadline: float) -> dict:
    """GET one JSON object; any other status or shape refuses."""
    status, _headers, _size, body = fetch(port, ('GET', path), JSON_LIMIT, deadline)
    expect(status == 200, f'{path} answered HTTP {status}')
    value = json.loads(body)
    expect(isinstance(value, dict), f'{path} did not answer a JSON object')
    return value


def load(port: int, path: str, deadline: float) -> dict:
    """Load one preview document exactly as Studio's page requests it."""
    status, headers, size, _body = fetch(port, ('GET', path), HTML_LIMIT, deadline)
    expect(status == 200 and headers.get('content-type', '').startswith('text/html'),
           f'{path} answered HTTP {status} {headers.get("content-type", "")}'.strip())
    return {'path': path, 'status': status, 'bytes': size}


def compositions(info: dict, project: str, name: str) -> list[str]:
    """Studio's own composition list for this exact project, bounded."""
    expect(info.get('id') == name and info.get('dir') == project, 'Studio describes another project')
    rows = info.get('compositions')
    expect(isinstance(rows, list) and len(rows) <= MAX_COMPOSITIONS
           and all(isinstance(row, str) and row and not row.startswith('/') and '..' not in Path(row).parts
                   for row in rows), 'Studio composition list is malformed')
    return rows


def studio_served(project: str, record: ServerRecord, seconds: float) -> dict:
    """Verify the view's process serves this project, and load it as Studio's page would."""
    deadline, name = time.monotonic() + seconds, Path(project).name
    base = f'/api/projects/{quote(name, safe="")}'
    result = {'verified': False, 'reason': None, 'port': record.port, 'pid': record.pid, 'loads': []}
    try:
        config = fetch_json(record.port, '/__hyperframes_config', deadline)
        expect(config.get('isHyperframes') is True and config.get('pid') == record.pid,
               f'port {record.port} is not the registered Studio process {record.pid}')
        expect(config.get('projectDir') == project and config.get('projectName') == name,
               f'Studio on port {record.port} serves {config.get("projectDir")!r}, not this project')
        result['version'] = str(config.get('version', ''))[:64]
        paths = compositions(fetch_json(record.port, base, deadline), project, name)
        result['loads'].append(load(record.port, f'{base}/preview', deadline))
        for path in (row for row in paths if row != 'index.html'):
            result['loads'].append(load(record.port, f'{base}/preview/comp/{quote(path)}', deadline))
    except CHECK_ERRORS as error:
        result['reason'] = f'{type(error).__name__}: {error}'[:600]
        return result
    return {**result, 'verified': True}


def player_port(url: str) -> int:
    """Admit only this computer's review player root URL; nothing is sent anywhere else."""
    parts = urlsplit(url)
    expect(parts.scheme == 'http' and parts.hostname in {HOST, 'localhost'} and parts.port is not None
           and parts.path in {'', '/'} and not (parts.query or parts.fragment or parts.username or parts.password),
           'review player URL must be http://127.0.0.1:<port>/ as review_player.py serve printed it')
    return parts.port


def player_row(url: str, attempt: Path, mp4: dict, seconds: float) -> dict:
    """The player's server identity and own label for this attempt, verified to serve these exact MP4 bytes now."""
    deadline = time.monotonic() + seconds
    result = {'url': url, 'verified': False, 'reason': None}
    try:
        port = player_port(url)
        document = fetch_json(port, '/inventory.json', deadline)
        result['server'] = document.get('server')
        rows = [row for row in document.get('attempts', []) if isinstance(row, dict) and row.get('export') == str(attempt)]
        expect(len(rows) == 1, 'the review player does not list this attempt exactly once')
        row = rows[0]
        activity = document.get('activity') if isinstance(document.get('activity'), dict) else {}
        attempts = activity.get('attempts') if isinstance(activity.get('attempts'), dict) else {}
        result.update(id=row.get('id'), kind=row.get('kind'), label=row.get('label'), route=row.get('route'),
                      pages=[page for page in activity.get('pages') or [] if isinstance(page, dict)],
                      activity=attempts.get(row.get('id')) if isinstance(attempts.get(row.get('id')), dict) else {})
        expect(row.get('playable') is True and row.get('sha256') == mp4['sha256'],
               'the review player does not serve this exact MP4')
        status, headers, _size, _body = fetch(port, ('HEAD', row['route']), 0, deadline)
        expect(status == 200 and headers.get('content-length') == str(mp4['bytes']),
               f'the review player media route answered HTTP {status}')
        result['mediaUrl'] = url.rstrip('/') + row['route']
    except CHECK_ERRORS as error:
        result['reason'] = f'{type(error).__name__}: {error}'[:600]
        return result
    return {**result, 'verified': True}

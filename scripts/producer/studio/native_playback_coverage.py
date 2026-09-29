"""Long playback coverage: how much of one exact MP4 the review page reported playing at normal speed (P4-20).

``capture`` reads the review player's own log (``review_player_activity``) through the visible hand-off's
verified-server path (``native_handoff_checks.player_row``) and writes one new record; ``check`` cold-reads a
record whose bytes a reader bound (M-141 spawns it). Each report pair and each span as a whole (X61) keep
``Δelement <= 1.05·Δserver + 0.5``. Not provable: that a person watched or listened; a local program can imitate
the page's reports (E-FORGE-3), and a forward wall-clock step widens the bound. Each command prints one JSON line
and exits 0 when it held, 1 on a named refusal (``code``), 2 on any other error (argparse usage errors: 2, no JSON):

  native_playback_coverage.py capture <attempt> --player <url> --output <file> [--plan <name the player lists>]
  native_playback_coverage.py check <file> --record-sha256 <hex> --mp4-sha <hex> --route <path> --seconds <P>
"""
from __future__ import annotations

import argparse
import json
import math
import stat
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from cut_preview_io import bound_json, file_hash, write_new
from studio.review_player_activity import now

SCHEMA_VERSION, KIND = 1, 'native-review-player-coverage'
MEANING = 'page-reported playback on the review player clock; not proof a person watched or listened'
SPEED, SLACK, END_TOLERANCE, RECORD_LIMIT = 1.05, 0.5, 0.5, 1024 * 1024
CODES = ('COVERAGE_ROUTE_MISMATCH', 'COVERAGE_INCOMPLETE', 'COVERAGE_NOT_NORMAL_SPEED', 'COVERAGE_RECORD_CHANGED')
CAPTURE_CODES = ('COVERAGE_DELIVERY_REFUSED', 'COVERAGE_PLAYER_NOT_VERIFIED')
RECORD_KEYS = {'schemaVersion', 'kind', 'server', 'attempt', 'mp4', 'route', 'coverage', 'capturedAt', 'meaning'}
COVERAGE_KEYS = {'coveredSeconds', 'spans', 'normalSpeed', 'first', 'last'}


class CoverageRefused(ValueError):
    """A coverage capture or record does not hold; ``code`` names the failed condition."""

    def __init__(self, code: str, message: str) -> None:
        """Keep the code with the reason; only the named codes exist."""
        if code not in CODES + CAPTURE_CODES:
            raise ValueError(f'unknown coverage refusal code {code!r}')
        super().__init__(f'{code}: {message}')
        self.code = code


def refuse(held: bool, code: str, message: str) -> None:
    """Raise ``CoverageRefused(code, message)`` unless ``held``."""
    if not held:
        raise CoverageRefused(code, message)


@dataclass(frozen=True)
class Report:
    """One page report on the route: page token, event, element time, server time and the log's own stamp."""

    token: str
    event: str
    element: float
    server: datetime
    stamp: str


def is_seconds(value: object) -> bool:
    """A finite, non-negative JSON number (never a bool); an integer above 2**53 is refused, never overflowed."""
    return (type(value) is float and math.isfinite(value) or type(value) is int and value <= 2 ** 53) and value >= 0


def is_hex64(value: object) -> bool:
    """A lowercase hexadecimal SHA-256."""
    return isinstance(value, str) and len(value) == 64 and all(char in '0123456789abcdef' for char in value)


def parse_report(row: dict) -> Report:
    """One log row as the review player records it; a malformed row refuses the whole reading."""
    token, event, element, stamp = (row.get(key) for key in ('token', 'event', 'currentTime', 'time'))
    server = datetime.fromisoformat(stamp) if isinstance(stamp, str) else None
    if not (isinstance(token, str) and token and isinstance(event, str) and event and is_seconds(element)
            and server is not None and server.tzinfo is not None):
        raise ValueError(f'Playback report malformed (token, event, element time, zoned server time): {row!r}'[:400])
    return Report(token, event, float(element), server, stamp)


def route_reports(reports: list[dict], route: str) -> list[Report]:
    """The reports on ``route``, in log order; other routes are not this media and are left out."""
    if not isinstance(reports, list) or not all(isinstance(row, dict) for row in reports):
        raise ValueError('Playback reports are a list of objects')
    return [parse_report(row) for row in reports if row.get('route') == route]


def counts(before: Report, after: Report) -> bool:
    """Whether element time from ``before`` to ``after`` played at normal speed, with no seek or pause between."""
    if before.event == 'pause' or after.event == 'seeked':  # the paused interval and the jump never count
        return False
    server = (after.server - before.server).total_seconds()
    element = after.element - before.element
    return server >= 0 and 0 <= element <= SPEED * server + SLACK


def token_spans(rows: list[Report]) -> list[tuple[float, float]]:
    """One token's maximal chains of counted pairs, each also within the speed bound as a whole (X61), as spans."""
    spans, chain, first = [], None, None
    for before, after in zip(rows, rows[1:]):
        first = before if chain is None else first
        if counts(before, after) and counts(first, after):  # the chain as a whole also keeps the speed bound
            chain = (first.element, after.element)
        elif chain is not None:
            spans, chain = spans + [chain], None
    return [span for span in spans + [chain] if span and span[1] > span[0]]


def covered_spans(reports: list[dict], route: str) -> list[tuple[float, float]]:
    """Every counted element-time span of ``route``, per page token, sorted by start (spans may overlap)."""
    tokens: dict[str, list[Report]] = {}
    for report in route_reports(reports, route):
        tokens.setdefault(report.token, []).append(report)
    return sorted(span for rows in tokens.values() for span in token_spans(rows))


def union(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Merge overlapping or touching spans into a sorted, disjoint union."""
    merged: list[tuple[float, float]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            continue
        merged.append((start, end))
    return merged


def reaches(merged: list[tuple[float, float]], end: float) -> bool:
    """Whether a sorted, disjoint union covers ``[0, end]`` without a gap."""
    return bool(merged) and merged[0][0] <= 0 and merged[0][1] >= end


def coverage(reports: list[dict], route: str, duration: float) -> dict:
    """Covered seconds, the union of spans, ``normalSpeed``, and the first and last report's own log ``time``."""
    if not is_seconds(duration) or duration <= END_TOLERANCE:
        raise ValueError(f'Coverage duration must be finite seconds above {END_TOLERANCE}: {duration!r}')
    rows, merged = route_reports(reports, route), union(covered_spans(reports, route))
    return {'coveredSeconds': sum(end - start for start, end in merged),
            'spans': [[start, end] for start, end in merged],
            'normalSpeed': reaches(merged, duration - END_TOLERANCE),
            'first': rows[0].stamp if rows else None, 'last': rows[-1].stamp if rows else None}


def coverage_record(attempt: Path, mp4: dict, row: dict, cover: dict) -> dict:
    """The record ``capture`` writes: P4-20's shape, from a verified player ``row`` and computed ``cover``."""
    server = {'pid': row['server']['pid'], 'port': row['server']['port'], 'started': row['server']['startedAt']}
    return {'schemaVersion': SCHEMA_VERSION, 'kind': KIND, 'server': server, 'attempt': str(attempt),
            'mp4': {'path': mp4['path'], 'sha256': mp4['sha256']}, 'route': row['route'],
            'coverage': cover, 'capturedAt': now(), 'meaning': MEANING}


def delivery_mp4(attempt: Path, plan: str | None) -> tuple[dict, float]:
    """The MP4 identity via the player's own reader (D-F a), and the seconds the page plays for the listed ``plan``."""
    from studio.native_review_contract import checked_delivery  # imported here: the cold reader never loads it
    from studio.review_player_inventory import EVIDENCE_ERRORS, attempt_row, duration_seconds
    try:
        listed = attempt_row({'id': 'coverage', 'export': str(attempt), 'plan': plan})  # the player's own row rules
        delivery, request, _pins = checked_delivery(attempt)
        path, seconds = Path(delivery['output']), duration_seconds(request, listed.plan)
        info = path.lstat()
    except EVIDENCE_ERRORS as error:
        raise CoverageRefused('COVERAGE_DELIVERY_REFUSED', f'{attempt}: {type(error).__name__}: {error}') from error
    refuse(stat.S_ISREG(info.st_mode), 'COVERAGE_DELIVERY_REFUSED', f'{path} is not a regular MP4 file')
    return {'path': str(path), 'sha256': delivery['sha256'], 'bytes': info.st_size}, seconds


def verified_row(attempt: Path, player_url: str, mp4: dict) -> dict:
    """The live player's own row for this attempt, serving these exact bytes now, with one server identity."""
    from studio.native_handoff_checks import DEFAULT_LOAD_SECONDS, player_port, player_row
    row = player_row(player_url, attempt, mp4, DEFAULT_LOAD_SECONDS)
    refuse(row['verified'] is True, 'COVERAGE_PLAYER_NOT_VERIFIED', str(row['reason']))
    server = row.get('server') if isinstance(row.get('server'), dict) else {}
    refuse(type(server.get('pid')) is int and server.get('port') == player_port(player_url)
           and isinstance(server.get('startedAt'), str) and isinstance(row.get('route'), str)
           and isinstance((row.get('activity') or {}).get('playback'), list), 'COVERAGE_PLAYER_NOT_VERIFIED',
           f'the review player at {player_url} did not report one server identity, route and playback log')
    return row


def capture(attempt: Path, player_url: str, output: Path, plan: str | None) -> dict:
    """Publish one new record (O_EXCL) from the live log of this attempt as the player lists it (``plan``)."""
    mp4, duration = delivery_mp4(attempt, plan)
    row = verified_row(attempt, player_url, mp4)
    try:
        cover = coverage(row['activity']['playback'], row['route'], duration)
    except ValueError as error:
        raise CoverageRefused('COVERAGE_PLAYER_NOT_VERIFIED', f'the playback log is malformed: {error}') from error
    record = coverage_record(attempt, mp4, row, cover)
    write_new(output, record)
    return record


@dataclass(frozen=True)
class CoverageBinding:
    """The coverage record a reader bound: its absolute path and the SHA-256 of its exact bytes (D-F b)."""

    path: Path
    sha256: str


def record_problem(record: dict) -> str | None:
    """Why parsed JSON is not a coverage record as ``capture`` writes it, or None."""
    mp4, server, cover = record.get('mp4'), record.get('server'), record.get('coverage')
    if set(record) != RECORD_KEYS or (type(record['schemaVersion']), record['schemaVersion']) != (int, SCHEMA_VERSION):
        return f'not a schema-{SCHEMA_VERSION} coverage record (keys {sorted(record)})'
    if record['kind'] != KIND or record['meaning'] != MEANING:
        return f'kind or meaning is not {KIND!r} with the page-reported meaning'
    if not (isinstance(mp4, dict) and set(mp4) == {'path', 'sha256'} and is_hex64(mp4['sha256'])
            and isinstance(mp4['path'], str) and isinstance(server, dict) and set(server) == {'pid', 'port', 'started'}
            and type(server['pid']) is int and type(server['port']) is int and isinstance(server['started'], str)
            and all(isinstance(record[key], str) for key in ('route', 'attempt', 'capturedAt'))):
        return 'the media, attempt, capture time or server identity is malformed'
    if not (isinstance(cover, dict) and set(cover) == COVERAGE_KEYS and type(cover['normalSpeed']) is bool
            and all(value is None or isinstance(value, str) for value in (cover['first'], cover['last']))):
        return 'the coverage block is malformed'
    return spans_problem(cover['spans'], cover['coveredSeconds'])


def spans_problem(spans: object, seconds: object) -> str | None:
    """Why recorded spans are not a sorted, disjoint union of positive pairs whose length is ``seconds``, or None."""
    if not isinstance(spans, list) or not all(isinstance(span, list) and len(span) == 2 and all(map(is_seconds, span))
                                              and span[0] < span[1] for span in spans):
        return 'coverage spans are not [start, end] element-time pairs'
    if any(later[0] <= earlier[1] for earlier, later in zip(spans, spans[1:])):
        return 'coverage spans are not a sorted, disjoint union'
    if not is_seconds(seconds) or abs(sum(end - start for start, end in spans) - seconds) > 1e-6:
        return 'coveredSeconds is not the length of the recorded spans'
    return None


def read_record(binding: CoverageBinding) -> dict:
    """The bound record's exact bytes as a coverage record; other bytes, none, or another shape: RECORD_CHANGED."""
    try:
        record = bound_json(binding.path, binding.sha256, maximum=RECORD_LIMIT)
    except (OSError, RuntimeError, ValueError) as error:
        raise CoverageRefused('COVERAGE_RECORD_CHANGED', f'{binding.path}: {type(error).__name__}: {error}') from error
    problem = record_problem(record)
    refuse(problem is None, 'COVERAGE_RECORD_CHANGED', f'{binding.path}: {problem}')
    return record


def check(binding: CoverageBinding, mp4_sha: str, route: str, program_seconds: float) -> dict:
    """Cold-read one bound record; refuse by code in P4-20's order: bytes/kind, sha/route, speed, then length."""
    if not (binding.path.is_absolute() and is_hex64(binding.sha256) and is_hex64(mp4_sha) and isinstance(route, str)
            and route and is_seconds(program_seconds) and program_seconds > END_TOLERANCE):
        raise ValueError('check takes an absolute record path, two SHA-256 hex digests, a route and P > 0.5 seconds')
    record = read_record(binding)
    cover, end = record['coverage'], program_seconds - END_TOLERANCE
    refuse(record['mp4']['sha256'] == mp4_sha and record['route'] == route, 'COVERAGE_ROUTE_MISMATCH',
           f"the record covers {record['route']!r} of MP4 {record['mp4']['sha256']}, not {route!r} of {mp4_sha}")
    refuse(cover['normalSpeed'] is True, 'COVERAGE_NOT_NORMAL_SPEED',
           'the page did not report playing the whole program at normal speed without a gap, seek or skip')
    refuse(cover['coveredSeconds'] >= end and reaches([tuple(span) for span in cover['spans']], end),
           'COVERAGE_INCOMPLETE', f"{cover['coveredSeconds']} s covered; the program needs [0, {end}] s")
    return {'status': 'coverage-verified', 'record': {'path': str(binding.path), 'sha256': binding.sha256},
            'attempt': record['attempt'], 'mp4': record['mp4'], 'route': route, 'programSeconds': program_seconds,
            'coveredSeconds': cover['coveredSeconds'], 'normalSpeed': True, 'capturedAt': record['capturedAt'],
            'meaning': MEANING}


def parser() -> argparse.ArgumentParser:
    """The ``capture`` and ``check`` commands; every argument is required."""
    root = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = root.add_subparsers(dest='command', required=True)
    take, read = commands.add_parser('capture'), commands.add_parser('check')
    take.add_argument('attempt', type=Path)
    take.add_argument('--plan', metavar='NAME.json', help='the plan name the player lists this attempt with, if any')
    read.add_argument('file', type=Path)
    for command, flag, kind in ((take, '--player', str), (take, '--output', Path), (read, '--record-sha256', str),
                                (read, '--mp4-sha', str), (read, '--route', str), (read, '--seconds', float)):
        command.add_argument(flag, required=True, type=kind)
    return root


def main(argv: list[str] | None = None) -> int:
    """Print one JSON line; exit 0 when it held, 1 on a named refusal (``code``), 2 on any other error."""
    args, code = parser().parse_args(argv), 0
    try:
        if args.command == 'check':
            result = check(CoverageBinding(args.file, args.record_sha256), args.mp4_sha, args.route, args.seconds)
        else:
            record = capture(args.attempt, args.player, args.output, args.plan)
            sha = file_hash(args.output, RECORD_LIMIT)
            result = {'status': 'captured', 'record': {'path': str(args.output), 'sha256': sha}, 'mp4': record['mp4'],
                      'route': record['route'], 'coverage': record['coverage'], 'meaning': MEANING}
    except CoverageRefused as error:
        result, code = {'status': 'refused', 'code': error.code, 'message': str(error)}, 1
    except (OSError, RuntimeError, ValueError) as error:
        result, code = {'status': 'error', 'error': f'{type(error).__name__}: {error}'[:1000]}, 2
    print(json.dumps(result), flush=True)
    return code


if __name__ == '__main__':
    sys.exit(main())

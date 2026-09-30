"""A generated local status page (P3b-14): static HTML from one status snapshot, never a second source of truth.

``render_page`` turns one full status read (``native_budget_status.production_status(..., full=True)`` with
P3b-13's coordination blocks) into a self-contained page: a run header, one card per output and a footer naming
the source of truth. Every value is ``html.escape``d and None prints "unknown". The page loads nothing: inline
CSS, one inline script that shows the STALE banner once the page is older than 3 x its refresh, and a meta
refresh only in watch mode. ``write_page`` writes it atomically, only outside the budget authority, and only
over a file that is already a status page (``MARKER``). No engine code reads a page back: ``write_page``'s
check of an existing file's first bytes is the only read, and it reads the marker alone.

The status shape is provisional until M-110 builds ``native_budget_coordination`` (W3-D11): the page reads the
names in ``tests/fixtures/status_page_input.json``. ``run_page`` (one snapshot or ``--watch``) is M-111's stage B.
"""
from __future__ import annotations

import html
import math
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from studio import native_budget_store
from studio.native_budget_status_page_style import (COMPACT_FIELDS, CSS, FOOTER, PLAYED_BASIS, STALE_SCRIPT, STALE_TEXT,
                                                    TOKEN_COLUMNS, VERDICTS)

MARKER = '<!-- sniper-status-page v1 -->'
REFRESH_SECONDS = (5, 300)
INSIDE_AUTHORITY = 'status-page --out must not be inside the budget authority'
FOREIGN_FILE = 'status-page --out names an existing file that is not a status page; choose a new path'


@dataclass(frozen=True)
class PageMeta:
    """The page stamp: whose batch, when it was generated, how often it refreshes, and any final banner.

    Attributes:
        batch_id: The batch the snapshot read.
        generated_epoch: Wall time of the snapshot (seconds since the epoch); the STALE script compares it.
        refresh_seconds: The watch interval, 5 to 300; STALE shows after 3 x this.
        snapshot_elapsed: The batch's elapsed seconds at the snapshot.
        watch: True only while a watcher regenerates the page (adds the meta refresh).
        banner: A final or error banner (``BANNERS``, formatted by the caller), or None.
    """

    batch_id: str
    generated_epoch: float
    refresh_seconds: int
    snapshot_elapsed: float
    watch: bool
    banner: str | None

    def __post_init__(self) -> None:
        """Refuse a stamp the page would print or script wrongly."""
        low, high = REFRESH_SECONDS
        if type(self.refresh_seconds) is not int or not low <= self.refresh_seconds <= high:
            raise ValueError(f'refresh_seconds is an integer from {low} to {high}')
        if not all(isinstance(value, (int, float)) and math.isfinite(value)
                   for value in (self.generated_epoch, self.snapshot_elapsed)):
            raise ValueError('generated_epoch and snapshot_elapsed are finite numbers')


def _text(value: object) -> str:
    """One escaped value; None is "unknown"."""
    return 'unknown' if value is None else html.escape(str(value), quote=True)


def _clock(seconds: float | None) -> str:
    """Seconds as [-]m:ss; None is "unknown"."""
    if seconds is None:
        return 'unknown'
    whole = round(abs(seconds))
    return f"{'-' if seconds < 0 else ''}{whole // 60}:{whole % 60:02d}"


def _count(value: int | None) -> str:
    """A token count with thousands separators; None is "unknown" (never 0)."""
    return 'unknown' if value is None else f'{value:,}'


def _utc(epoch: float) -> str:
    """An epoch time as UTC."""
    return datetime.fromtimestamp(epoch, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')


def _items(fragments: list[str]) -> str:
    """Escaped fragments as a list, or "none"."""
    return f"<ul class=\"plain\">{''.join(f'<li>{item}</li>' for item in fragments)}</ul>" if fragments else 'none'


def _session(row: dict) -> str:
    """One director session: host, slots, open or ended, host thread declared or not, slot source, strays."""
    ended = 'open' if row['endedElapsed'] is None \
        else f"ended at {_clock(row['endedElapsed'])} by {_text(row['endedBy'])}"
    thread = {True: 'declared', False: 'not declared'}.get(row['hostThreadKnown'], 'unknown')
    return (f"{_text(row['session'])} ({_text(row['host'])}): {_text(row['active'])}/{_text(row['slots'])} slots, "
            f"{ended}; host thread {thread}; slots from {_text(row['slotsSource'])}; strays {_text(row['strays'])}")


def _director(row: dict) -> str:
    """Director liveness (advisory only)."""
    advice = f"<br>{_text(row['advice'])}" if row['advice'] is not None else ''
    return (f"{_text(row['state'])} (session {_text(row['session'])}); last action at "
            f"{_clock(row['lastActionElapsed'])}; silent {_clock(row['silentSeconds'])}{advice}")


def _header(status: dict, run: dict) -> str:
    """The run header: batch, governance and its limitations, sessions, director, quarantined, unresolved, SLA."""
    held = [f"{_text(row['taskId'])} (session {_text(row['session'])}): {_text(row['reason'])}"
            for row in run['quarantined']]
    unresolved = [f"{_text(row['taskId'])} (session {_text(row['session'])}): {_text(row['reason'])}"
                  for row in run['unresolved']]
    misses = (f"encoded: {_text(', '.join(status['slaMisses']) or 'none')}; visible hand-off: "
              f"{_text(', '.join(status['production']['visibleSlaMisses']) or 'none')}")
    facts = (('Governance', f"{_text(run['governance']['mode'])}: {_text(run['governance']['source'])}"),
             ('Limitations', _items([_text(text) for text in run['governance']['limitations']])),
             ('Sessions', _items([_session(row) for row in run['sessions']])), ('Director', _director(run['director'])),
             ('Quarantined', _items(held)), ('Unresolved', _items(unresolved)), ('SLA misses', misses))
    rows = ''.join(f'<dt>{name}</dt><dd>{value}</dd>' for name, value in facts)
    return (f"<header class=\"run\"><h1>Batch {_text(status['batchId'])}</h1><p class=\"meta\">"
            f"{_text(status['status'])} · {_text(status['phase'])} · elapsed {_clock(status['elapsedSeconds'])}</p>"
            f'<dl class="facts">{rows}</dl></header>')


def _bar(kind: str, value: float | None, budget: float | None) -> str:
    """One horizontal bar of ``value`` over the output's counted budget; empty when either is unknown."""
    if value is None or budget is None or budget <= 0:
        return f'<div class="bar {kind}" title="unknown"></div>'
    return f'<div class="bar {kind}"><span style="width: {min(max(value / budget, 0.0), 1.0) * 100:.1f}%"></span></div>'


def _clock_bars(clock: dict) -> str:
    """Counted time against the output's budget (counted + remaining), and the excluded wait drawn apart."""
    counted, remaining = clock['countedSeconds'], clock['remainingSeconds']
    budget = None if counted is None or remaining is None else counted + remaining
    excluded = clock['excludedRenderWaitSeconds']
    return (f"<h3>Clock ({_text(clock['policy'])})</h3><div class=\"small\">counted {_clock(counted)} of "
            f"{_clock(budget)}, {_clock(remaining)} left</div>{_bar('counted', counted, budget)}"
            f"<div class=\"small\">excluded render wait {_clock(excluded)} (+{_clock(clock['uncertainSeconds'])} "
            f"uncertain), not counted</div>{_bar('excluded', excluded, budget)}")


def _at(label: str, row: dict | None, absent: str) -> str:
    """``label at m:ss`` when the moment was recorded, ``absent`` when not, "unknown" when the row is unknown."""
    if row is None:
        return 'unknown'
    return absent if row['at'] is None else f"{label} at {_clock(row['at'])}"


def _heard(name: str, row: dict) -> str:
    """How playing or listening is known (never a claim that a person watched), by whom and when."""
    basis = PLAYED_BASIS.get(row['basis'], row['basis'])
    return f"{name}: {_text(basis)}" + ('' if row['by'] is None else f" by {_text(row['by'])}") \
        + ('' if row['at'] is None else f" at {_clock(row['at'])}")


def _chips(review: dict) -> str:
    """The four review states, kept apart: ready, shown, played/listened, editorially approved."""
    ready, approved, heard = review['ready'], review['editoriallyApproved'], review['playedListened']
    label = _text(ready['label']) if ready is not None else ''
    verdict = VERDICTS.get(approved['verdict'], approved['verdict']) if approved is not None else ''
    chips = (f"Ready: {_at(label, ready, 'no MP4 yet')}", f"Shown: {_at('shown', review['shown'], 'not shown')}",
             f"{_heard('Played', heard['played'])}; {_heard('listened', heard['listened'])}",
             f"Approved: {_at(_text(verdict), approved, 'not yet')}")
    return f"<ul class=\"chips\">{''.join(f'<li>{chip}</li>' for chip in chips)}</ul>"


def _tokens(tokens: dict) -> str:
    """Tokens by role and for the team; unknown stays unknown, with the team's reasons."""
    head = ''.join(f'<th>{label}</th>' for _key, label in TOKEN_COLUMNS)
    rows = [(role, row['totals'], '') for role, row in tokens['roles'].items()]
    rows.append(('team', tokens['team']['totals'], ' class="team"'))
    body = ''.join(f'<tr{attrs}><td>{_text(role)}</td>'
                   + ''.join(f'<td data-label="{label}">{_count(totals[key])}</td>' for key, label in TOKEN_COLUMNS)
                   + '</tr>'
                   for role, totals, attrs in rows)
    because = '; '.join(_text(reason) for reason in tokens['team']['unknownBecause'])
    return (f'<table><thead><tr><th>Role</th>{head}</tr></thead><tbody>{body}</tbody></table>'
            f"<p class=\"small\">{_text(tokens['note'])}{' Unknown because: ' + because if because else ''}</p>")


def _card(clip_id: str, state: str, block: dict) -> str:
    """One output: the compact line, the clock, the review chips, findings by owner, tokens by role, next."""
    compact = block['compact']
    line = ' · '.join(f'{label} {_text(compact[key])}' for key, label in COMPACT_FIELDS)
    findings = ', '.join(f'{_text(owner)} {_text(count)}' for owner, count in compact['findings'].items()) or 'none'
    return (f'<article class="card"><h2>{_text(clip_id)} <span class="state">{_text(state)}</span></h2>'
            f"<p class=\"line\">{line}</p>{_clock_bars(block['clock'])}{_chips(block['review'])}"
            f"<h3>Findings by owner</h3><p>{findings}</p><h3>Tokens by role</h3>{_tokens(block['tokensByRole'])}"
            f"<p><strong>Next:</strong> {_text(block['nextAction'])}</p>"
            f"<p class=\"note\">{_text(block['identityNote'])}</p></article>")


def render_page(status: dict, meta: PageMeta) -> str:
    """The whole page for one full status read (P3b-13's compact and full shapes; provisional, W3-D11).

    Raises:
        KeyError: The status lacks a name the page reads (the shape M-110 must meet).
    """
    cards = ''.join(_card(clip_id, row['production']['state'], row['production']['coordination'])
                    for clip_id, row in status['clips'].items())
    stale = STALE_TEXT.format(window=3 * meta.refresh_seconds, refresh=meta.refresh_seconds, batch=meta.batch_id)
    footer = FOOTER.format(utc=_utc(meta.generated_epoch), elapsed=_clock(meta.snapshot_elapsed), batch=meta.batch_id)
    return '\n'.join((
        MARKER, '<!DOCTYPE html>', '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f'<meta http-equiv="refresh" content="{meta.refresh_seconds}">' if meta.watch else '',
        f'<title>Sniper status: {_text(meta.batch_id)}</title><style>{CSS}</style></head>',
        f'<body data-generated-epoch="{float(meta.generated_epoch)!r}" data-refresh-seconds="{meta.refresh_seconds}">',
        f'<div class="banner stale" id="stale" hidden>{_text(stale)}</div>',
        '' if meta.banner is None else f'<div class="banner final">{_text(meta.banner)}</div>',
        _header(status, status['production']['coordination']), f'<main class="outputs">{cards}</main>',
        f'<footer>{_text(footer)}</footer><script>{STALE_SCRIPT}</script></body></html>', ''))


def _inside(path: Path, root: Path) -> bool:
    """Whether ``path``, as given or with every link resolved, is ``root`` or under it."""
    roots = {root.absolute(), root.resolve()}
    return any(candidate == top or top in candidate.parents
               for candidate in (path, path.resolve()) for top in roots)


def _is_page(path: Path) -> bool:
    """Whether an existing ``path`` is a regular file starting with ``MARKER`` (reads only those bytes).

    A folder, FIFO, socket or device is never a page and is never opened (a FIFO would block the read).
    """
    if not path.is_file():
        return False
    marker = MARKER.encode()
    try:
        with path.open('rb') as handle:
            return handle.read(len(marker)) == marker
    except OSError:
        return False


def write_page(path: Path, text: str) -> None:
    """Atomically replace ``path`` with a rendered page: a temporary file beside it, fsync, ``os.replace``.

    Raises:
        ValueError: ``path`` is relative, its folder does not exist, it is inside the budget authority, it names an
            existing file that is not a status page, or ``text`` is not a rendered page.
        OSError: The write failed (disk full, permissions); the previous page is left intact.
    """
    if not path.is_absolute() or not path.parent.is_dir():
        raise ValueError('status-page --out is an absolute path in an existing folder')
    if _inside(path, native_budget_store.default_root()):
        raise ValueError(INSIDE_AUTHORITY)
    if (path.exists() or path.is_symlink()) and not _is_page(path):
        raise ValueError(FOREIGN_FILE)
    if not text.startswith(MARKER + '\n'):
        raise ValueError('write_page writes only a page render_page made')
    descriptor, temporary = tempfile.mkstemp(prefix='.status-page-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(text.encode('utf-8'))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)   # gone after a replace; after a failure, the old page stays

"""A generated local status page (P3b-14): static HTML from one status snapshot, never a second source of truth.

``render_page`` turns one full status read (``native_budget_status.production_status(..., full=True)`` with
P3b-13's coordination blocks) into a self-contained page: a run header, one card per output and a footer naming
the source of truth. Every value is ``html.escape``d. None prints "unknown", a null block too (its fields print
"unknown"; a missing key is a shape error, KeyError). Every card carries the declared-identity note from the
constant, whatever the status holds. The page loads nothing: inline CSS, one inline script that shows the STALE
banner once the page is older than 3 x its refresh, and a meta refresh only in watch mode. ``write_page``
(``native_budget_status_page_write``, re-exported here) writes it atomically, never inside the budget authority
and only over a file that is already a status page (``MARKER``). No engine code reads a page back.

The status shape is provisional until M-110 builds ``native_budget_coordination`` (W3-D11): the page reads the
names in ``tests/fixtures/status_page_input.json``. ``run_page`` (one snapshot or ``--watch``) is M-111's stage B.
"""
from __future__ import annotations

import html
import math
from dataclasses import dataclass
from datetime import datetime, timezone

from studio.native_budget_status_page_style import (COMPACT_FIELDS, CSS, DECLARED_NOTE, FOOTER, PLAYED_BASIS,
                                                    STALE_SCRIPT, STALE_TEXT, THREAD_KNOWN, TOKEN_COLUMNS, VERDICTS)
from studio.native_budget_status_page_write import FOREIGN_FILE, INSIDE_AUTHORITY, MARKER, write_page

REFRESH_SECONDS = (5, 300)
TEAM_ROW = ' class="team"'
__all__ = ['FOREIGN_FILE', 'INSIDE_AUTHORITY', 'MARKER', 'PageMeta', 'render_page', 'write_page']


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
        """Refuse a stamp the page would print or script wrongly (a bool is not a number here)."""
        low, high = REFRESH_SECONDS
        if type(self.refresh_seconds) is not int or not low <= self.refresh_seconds <= high:
            raise ValueError(f'refresh_seconds is an integer from {low} to {high}')
        if not all(type(value) in (int, float) and math.isfinite(value)
                   for value in (self.generated_epoch, self.snapshot_elapsed)):
            raise ValueError('generated_epoch and snapshot_elapsed are finite numbers')


def _text(value: object) -> str:
    """One escaped value; None is "unknown"."""
    return 'unknown' if value is None else html.escape(str(value), quote=True)


def _field(row: dict | None, key: str) -> object:
    """``row[key]``; a null row gives None ("unknown"). A missing key is a shape error (KeyError)."""
    return None if row is None else row[key]


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


def _items(fragments: list[str] | None) -> str:
    """Escaped fragments as a list; "none" when empty, "unknown" when the list itself is unknown."""
    if fragments is None:
        return 'unknown'
    return f"<ul class=\"plain\">{''.join(f'<li>{item}</li>' for item in fragments)}</ul>" if fragments else 'none'


def _names(values: list | None) -> str:
    """Escaped names joined; "none" when empty, "unknown" when the list is unknown (an unknown name too)."""
    return 'unknown' if values is None else ', '.join(_text(value) for value in values) or 'none'


def _session(row: dict | None) -> str:
    """One director session: host, slots, open or ended, host thread declared or not, slot source, strays."""
    ended, by = _field(row, 'endedElapsed'), _field(row, 'endedBy')
    state = 'unknown' if row is None else 'open' if ended is None else f'ended at {_clock(ended)} by {_text(by)}'
    return (f"{_text(_field(row, 'session'))} ({_text(_field(row, 'host'))}): {_text(_field(row, 'active'))}/"
            f"{_text(_field(row, 'slots'))} slots, {state}; host thread {THREAD_KNOWN[_field(row, 'hostThreadKnown')]}"
            f"; slots from {_text(_field(row, 'slotsSource'))}; strays {_text(_field(row, 'strays'))}")


def _director(row: dict | None) -> str:
    """Director liveness (advisory only)."""
    advice = _field(row, 'advice')
    return (f"{_text(_field(row, 'state'))} (session {_text(_field(row, 'session'))}); last action at "
            f"{_clock(_field(row, 'lastActionElapsed'))}; silent {_clock(_field(row, 'silentSeconds'))}"
            + ('' if advice is None else f'<br>{_text(advice)}'))


def _held(rows: list | None) -> list[str] | None:
    """Quarantined or unresolved executions: task, session, why."""
    if rows is None:
        return None
    return [f"{_text(_field(row, 'taskId'))} (session {_text(_field(row, 'session'))}): "
            f"{_text(_field(row, 'reason'))}" for row in rows]


def _header(status: dict, run: dict | None) -> str:
    """The run header: batch, governance and its limitations, sessions, director, quarantined, unresolved, SLA."""
    governance, sessions = _field(run, 'governance'), _field(run, 'sessions')
    limits = _field(governance, 'limitations')
    misses = (f"encoded: {_names(status['slaMisses'])}; visible hand-off: "
              f"{_names(_field(status['production'], 'visibleSlaMisses'))}")
    facts = (('Governance', f"{_text(_field(governance, 'mode'))}: {_text(_field(governance, 'source'))}"),
             ('Limitations', _items(None if limits is None else [_text(text) for text in limits])),
             ('Sessions', _items(None if sessions is None else [_session(row) for row in sessions])),
             ('Director', _director(_field(run, 'director'))),
             ('Quarantined', _items(_held(_field(run, 'quarantined')))),
             ('Unresolved', _items(_held(_field(run, 'unresolved')))), ('SLA misses', misses))
    rows = ''.join(f'<dt>{name}</dt><dd>{value}</dd>' for name, value in facts)
    return (f"<header class=\"run\"><h1>Batch {_text(status['batchId'])}</h1><p class=\"meta\">"
            f"{_text(status['status'])} · {_text(status['phase'])} · elapsed {_clock(status['elapsedSeconds'])}</p>"
            f'<dl class="facts">{rows}</dl></header>')


def _bar(kind: str, value: float | None, budget: float | None) -> str:
    """One horizontal bar of ``value`` over the output's counted budget; none drawn when either is unknown."""
    if value is None or budget is None or budget <= 0:
        return ''
    return f'<div class="bar {kind}"><span style="width: {min(max(value / budget, 0.0), 1.0) * 100:.1f}%"></span></div>'


def _clock_bars(clock: dict | None) -> str:
    """Counted time against the output's budget (counted + remaining), and the excluded wait drawn apart."""
    counted, remaining = _field(clock, 'countedSeconds'), _field(clock, 'remainingSeconds')
    budget = None if counted is None or remaining is None else counted + remaining
    excluded = _field(clock, 'excludedRenderWaitSeconds')
    return (f"<h3>Clock ({_text(_field(clock, 'policy'))})</h3><div class=\"small\">counted {_clock(counted)} of "
            f"{_clock(budget)}, {_clock(remaining)} left</div>{_bar('counted', counted, budget)}"
            f"<div class=\"small\">excluded render wait {_clock(excluded)} "
            f"(+{_clock(_field(clock, 'uncertainSeconds'))} uncertain), not counted</div>"
            f"{_bar('excluded', excluded, budget)}")


def _at(label: str, row: dict | None, absent: str) -> str:
    """``label at m:ss`` when the moment was recorded, ``absent`` when not, "unknown" when the row is unknown."""
    if row is None:
        return 'unknown'
    return absent if row['at'] is None else f"{label} at {_clock(row['at'])}"


def _heard(name: str, row: dict | None) -> str:
    """How playing or listening is known (never a claim that a person watched), by whom and when."""
    basis, by, at = _field(row, 'basis'), _field(row, 'by'), _field(row, 'at')
    shown = None if basis is None else PLAYED_BASIS[basis]   # an unlisted basis is a shape error, never printed raw
    return f'{name}: {_text(shown)}' + ('' if by is None else f' by {_text(by)}') \
        + ('' if at is None else f' at {_clock(at)}')


def _chips(review: dict | None) -> str:
    """The four review states, kept apart: ready, shown, played/listened, editorially approved."""
    ready, approved = _field(review, 'ready'), _field(review, 'editoriallyApproved')
    heard = _field(review, 'playedListened')
    verdict = _field(approved, 'verdict')
    chips = (f"Ready: {_at(_text(_field(ready, 'label')), ready, 'no MP4 yet')}",
             f"Shown: {_at('shown', _field(review, 'shown'), 'not shown')}",
             f"{_heard('Played', _field(heard, 'played'))}; {_heard('listened', _field(heard, 'listened'))}",
             f"Approved: {_at(_text(None if verdict is None else VERDICTS[verdict]), approved, 'not yet')}")
    return f"<ul class=\"chips\">{''.join(f'<li>{chip}</li>' for chip in chips)}</ul>"


def _token_row(role: str, totals: dict | None, attrs: str) -> str:
    """One table row: a role's four counts (unknown stays unknown)."""
    cells = ''.join(f'<td data-label="{label}">{_count(_field(totals, key))}</td>' for key, label in TOKEN_COLUMNS)
    return f'<tr{attrs}><td>{_text(role)}</td>{cells}</tr>'


def _tokens(tokens: dict | None) -> str:
    """Tokens by role and for the team; unknown stays unknown, with the team's reasons."""
    if tokens is None:
        return '<p>unknown</p>'
    roles, team = tokens['roles'], tokens['team']
    rows = [_token_row('each role', None, '')] if roles is None \
        else [_token_row(role, _field(row, 'totals'), '') for role, row in roles.items()]
    because = _field(team, 'unknownBecause')
    reasons = ' Unknown because: unknown' if because is None \
        else (' Unknown because: ' + '; '.join(_text(reason) for reason in because) if because else '')
    head = ''.join(f'<th>{label}</th>' for _key, label in TOKEN_COLUMNS)
    return (f"<table><thead><tr><th>Role</th>{head}</tr></thead><tbody>{''.join(rows)}"
            f"{_token_row('team', _field(team, 'totals'), TEAM_ROW)}</tbody></table>"
            f"<p class=\"small\">{_text(tokens['note'])}{reasons}</p>")


def _body(block: dict) -> str:
    """A card's body from its coordination block: compact line, clock, chips, findings, tokens, next action."""
    compact = block['compact']
    line = ' · '.join(f'{label} {_text(_field(compact, key))}' for key, label in COMPACT_FIELDS)
    owners = _field(compact, 'findings')
    findings = 'unknown' if owners is None \
        else ', '.join(f'{_text(owner)} {_text(count)}' for owner, count in owners.items()) or 'none'
    return (f"<p class=\"line\">{line}</p>{_clock_bars(block['clock'])}{_chips(block['review'])}"
            f"<h3>Findings by owner</h3><p>{findings}</p><h3>Tokens by role</h3>{_tokens(block['tokensByRole'])}"
            f"<p><strong>Next:</strong> {_text(block['nextAction'])}</p>")


def _card(clip_id: str, production: dict | None) -> str:
    """One output card; an unknown coordination block prints so. The declared note is always there."""
    block = _field(production, 'coordination')
    body = '<p class="line">coordination unknown</p>' if block is None else _body(block)
    return (f"<article class=\"card\"><h2>{_text(clip_id)} <span class=\"state\">"
            f"{_text(_field(production, 'state'))}</span></h2>{body}"
            f'<p class="note">{_text(DECLARED_NOTE)}</p></article>')


def render_page(status: dict, meta: PageMeta) -> str:
    """The whole page for one full status read (P3b-13's compact and full shapes; provisional, W3-D11).

    Raises:
        KeyError: The status lacks a name the page reads, or holds an unlisted basis or verdict (the shape M-110
            must meet).
    """
    cards = ''.join(_card(clip_id, row['production']) for clip_id, row in status['clips'].items())
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
        _header(status, _field(status['production'], 'coordination')), f'<main class="outputs">{cards}</main>',
        f'<footer>{_text(footer)}</footer><script>{STALE_SCRIPT}</script></body></html>', ''))

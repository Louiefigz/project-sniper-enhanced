"""Declared identities: what the coordinator says an AI execution is, never what a host adapter observed.

In-conversation subagents and the director that launches them carry a ``declared`` handle (P3b-1, M-088).
No host adapter is qualified in this release, so a historical host-shaped handle was declared too, and
nothing here reports "observed" for AI work (``identity_basis``).

A director handle names its host, its Sniper session id, its host thread when known, its slot count and
``hostProcess``: ``None`` until M-099 records the host session process ``{pid, pgid, started}`` (decision
D-E, X40). A subagent handle names its agent (a Claude Code agent id or a Codex agent path) and the 32-hex
launch nonce from its prompt; it carries no thread, slots or process. The key set is closed: every key is
present, and an absent key is refused, never defaulted.

``host_contract.valid_handle`` imports ``valid_declared`` lazily (M-088 patch), because this module imports
``host_contract`` at module level.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from studio.native_budget_schema import AI_POLICY
from studio.production import host_contract
from studio.production.tasks import TaskConflict, TaskRefused

AGENT_PATH = re.compile(r'(/[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}){1,4}')
SESSION = re.compile(r's-[0-9a-f]{16}')
DECLARED_KEYS = frozenset({'type', 'host', 'session', 'agent', 'launch', 'hostThread', 'slots', 'hostProcess'})
PROCESS_KEYS = frozenset({'pid', 'pgid', 'started'})
AGENT_BYTES = 200         # so identity_key stays <= 256 bytes, the TS reviewer sessionId bound
STATUS_BYTES = 128
DIRECTOR_KEY = 'director'  # the agent part of a director's identity key; never a valid agent

# ----------------------------------------------------------------------------------------------------------
# PROVISIONAL DATA TABLE: END_TOOLS, per host and host version (X55).
# The notice a director may quote verbatim as an end observation: the host's notification element and the
# host's literal background-work sentence, a protocol marker whose presence in the note makes the notice
# interim (with its sha256). Rows come only from the M-080a host-surface probe (X30): Claude Code 2.1.281,
# probed 2026-09-29. Codex has no row (not probed), so no Codex end can be quoted. A new host version needs a
# new probe and a new row; only this table changes. What counts as end evidence is M-102's HOST_END_EVIDENCE.
# ----------------------------------------------------------------------------------------------------------
END_TOOLS = {
    'claude-code': {
        '2.1.281': {
            'element': 'task-notification',
            'backgroundWorkSentence': 'This agent stopped with background work of its own still running.',
            'backgroundWorkSentenceSha256': '1ed07a3a96f9b503974e7bffd3323ac6c250e13e7470ae0aed251174e9315cff',
        },
    },
    'codex': {},
}
HEADER_ELEMENTS = ('task-id', 'status', 'summary', 'note')   # one-line elements before a notice's body

DIRECTOR_REFUSAL = ('A declared director handle names a known host, a Sniper session id, its host thread if known, '
                    f"and 2-{AI_POLICY['slotsCeiling']} slots")
SUBAGENT_REFUSAL = (f'A declared subagent handle names its agent id or path (at most {AGENT_BYTES} bytes) and the '
                    '32-hex launch nonce from its prompt')
PARENT_REFUSAL = 'A declared subagent handle is built from its valid declared director handle'


class DeclaredIdentityRefused(TaskRefused):
    """A declared handle does not fit the task, claim or session it is presented for."""


class DeclaredIdentityConflict(TaskConflict):
    """A declared identity already holds other work (one agent works one task at a time)."""


class HostHandleRefused(TaskRefused):
    """A host-shaped handle was given on the command line; no host adapter observed that turn."""


class EndObservationRefused(ValueError):
    """A quoted end observation is not a verbatim notice of a probed host version; the reason names why."""


@dataclass(frozen=True)
class EndObservation:
    """What the host's own notification reported when an agent's turn ended, as the director quoted it.

    Only ``interim == False`` with ``status`` in {completed, killed} may count as G9 (a) evidence (L-A).
    M-102 encodes that rule; this module only parses.

    Attributes:
        tool: The host's notification element, ``END_TOOLS[host][version]['element']``.
        status: The notice's ``<status>``: one line, at most ``STATUS_BYTES`` bytes.
        interim: True iff the notice's note contains that host version's background-work sentence.
        task_id: The notice's ``<task-id>``: the host's id of the agent execution it reports on.
    """

    tool: str
    status: str
    interim: bool
    task_id: str


def _matches(pattern: re.Pattern, value: object) -> bool:
    """True when ``value`` is a string that ``pattern`` matches in full."""
    return type(value) is str and pattern.fullmatch(value) is not None


def _line(value: object, limit: int) -> bool:
    """A non-empty single-line string without NUL whose canonical encoding fits ``limit`` bytes."""
    return type(value) is str and value.splitlines() == [value] and '\0' not in value \
        and host_contract.encoded_length(value) <= limit


def valid_agent(value: object) -> bool:
    """Whether ``value`` names one agent: a Claude Code ``agentId`` (``HOST_TOKEN``) or a Codex ``AGENT_PATH``.

    Returns:
        True when its canonical encoding fits ``AGENT_BYTES``; the literal ``director`` is refused so
        ``identity_key`` never confuses a subagent with its director.
    """
    if type(value) is not str or value == DIRECTOR_KEY or host_contract.encoded_length(value) > AGENT_BYTES:
        return False
    return _matches(host_contract.HOST_TOKEN, value) or _matches(AGENT_PATH, value)


def _host_process_ok(value: object) -> bool:
    """None, or ``{pid, pgid, started}`` under the process-handle rules without ``type`` (decision D-E)."""
    if value is None:
        return True
    return type(value) is dict and set(value) == PROCESS_KEYS \
        and host_contract.valid_handle({**value, 'type': 'process'})


def _director_ok(value: dict) -> bool:
    """The director variant: no launch, an optional host thread, 2..ceiling slots, an optional host process."""
    thread, slots = value['hostThread'], value['slots']
    return value['launch'] is None and (thread is None or _matches(host_contract.HOST_TOKEN, thread)) \
        and type(slots) is int and 2 <= slots <= AI_POLICY['slotsCeiling'] and _host_process_ok(value['hostProcess'])


def _subagent_ok(value: dict) -> bool:
    """The subagent variant: an agent and a launch nonce; no thread, slots or host process."""
    return valid_agent(value['agent']) and _matches(host_contract.HEX32, value['launch']) \
        and value['hostThread'] is None and value['slots'] is None and value['hostProcess'] is None


def valid_declared(value: object) -> bool:
    """Whether ``value`` is a director (``agent`` None) or subagent handle with exactly ``DECLARED_KEYS``."""
    if type(value) is not dict or set(value) != DECLARED_KEYS or value['type'] != 'declared':
        return False
    if value['host'] not in host_contract.HOSTS or not _matches(SESSION, value['session']):
        return False
    return _director_ok(value) if value['agent'] is None else _subagent_ok(value)


def _is_director(value: object) -> bool:
    """A valid declared director handle."""
    return valid_declared(value) and value['agent'] is None


def director_handle(host: str, session: str, host_thread: str | None, slots: int) -> dict:
    """Build and validate a director handle; ``hostProcess`` starts as None (M-099 fills it, D-E).

    Raises:
        ValueError: An unknown host, a bad session id, a thread that is not a host token, or slots outside
            2 to ``AI_POLICY['slotsCeiling']``.
    """
    handle = {'type': 'declared', 'host': host, 'session': session, 'agent': None, 'launch': None,
              'hostThread': host_thread, 'slots': slots, 'hostProcess': None}
    if not valid_declared(handle):
        raise ValueError(DIRECTOR_REFUSAL)
    return handle


def subagent_handle(director: dict, agent: str, launch: str) -> dict:
    """Build a subagent handle in ``director``'s host and session, with its agent and 32-hex launch nonce.

    Raises:
        ValueError: ``director`` is not a declared director handle, or the agent or nonce is invalid.
    """
    if not _is_director(director):
        raise ValueError(PARENT_REFUSAL)
    handle = {'type': 'declared', 'host': director['host'], 'session': director['session'], 'agent': agent,
              'launch': launch, 'hostThread': None, 'slots': None, 'hostProcess': None}
    if not valid_declared(handle):
        raise ValueError(SUBAGENT_REFUSAL)
    return handle


def _kind(handle: object) -> str:
    """The type of a valid declared, host or process handle; host_contract's ValueError otherwise."""
    if valid_declared(handle):
        return 'declared'
    return host_contract.require_handle(handle)['type']


def identity_key(handle: dict) -> str:
    """The one identity string for attach uniqueness, reviewer checks, roster labels and status.

    Returns:
        ``declared:<host>:<session>:<agent or "director">``, ``host:<host>:<thread>`` (turn ignored) or
        ``process:<pid>:<pgid>:<started>``. A director's ``hostProcess`` never changes its key.

    Raises:
        ValueError: The handle is not valid.
    """
    kind = _kind(handle)
    if kind == 'declared':
        agent = DIRECTOR_KEY if handle['agent'] is None else handle['agent']
        return f"declared:{handle['host']}:{handle['session']}:{agent}"
    if kind == 'host':
        return f"host:{handle['host']}:{handle['thread']}"
    return f"process:{handle['pid']}:{handle['pgid']}:{handle['started']}"


def identity_basis(handle: dict | None) -> str:
    """How an identity is known; nothing is "observed" for AI work.

    Returns:
        ``'declared'`` for declared and historical host handles (no host adapter exists in this release,
        so a host-shaped handle was declared too), ``'process-observed'`` for a process handle and
        ``'none'`` for None.

    Raises:
        ValueError: The handle is not valid.
    """
    if handle is None:
        return 'none'
    return 'process-observed' if _kind(handle) == 'process' else 'declared'


def registered_identity(handle: object) -> bool:
    """For section results: a declared subagent handle, or a historical host handle with a non-null turn."""
    if valid_declared(handle):
        return handle['agent'] is not None
    return host_contract.valid_handle(handle) and handle['type'] == 'host' and handle['turn'] is not None


def _format(host: object, version: object) -> dict:
    """The recorded notice format of one probed host version, or the named refusal."""
    versions = END_TOOLS[host] if host in host_contract.HOSTS else {}
    row = versions.get(version) if type(version) is str else None
    if row is None:
        raise EndObservationRefused(f'No end-observation format is recorded for host {host!r} version {version!r}: '
                                    'the M-080a host probe must cover this host version first')
    return row


def _header_element(line: str) -> tuple[str, str] | None:
    """(name, value) of a one-line header element such as ``<status>killed</status>``, else None."""
    for name in HEADER_ELEMENTS:
        opening, closing = f'<{name}>', f'</{name}>'
        if line.startswith(opening) and line.endswith(closing) and len(line) >= len(opening) + len(closing):
            return name, line[len(opening):len(line) - len(closing)]
    return None


def _notice_header(text: object, element: str) -> dict | None:
    """The header elements of one verbatim ``<element>`` notice (each at most once), or None.

    The header is the run of one-line ``HEADER_ELEMENTS`` after the opening tag; the body after it (the
    agent's result, usage) is not read, so an agent's own words can never supply a status or note.
    """
    lines = text.strip().splitlines() if type(text) is str else []
    if len(lines) < 3 or lines[0] != f'<{element}>' or lines[-1] != f'</{element}>':
        return None
    header = {}
    for line in lines[1:-1]:
        row = _header_element(line)
        if row is None:
            break
        if row[0] in header:
            return None
        header[row[0]] = row[1]
    return header


def parse_end_observation(text: str, host: str, version: str) -> EndObservation:
    """Parse the host's verbatim notice that an agent's turn ended, as the director quoted it.

    Only ``interim == False`` with ``status`` in {completed, killed} may count as G9 (a) evidence (L-A).
    M-102 encodes that rule; this function only parses.

    Args:
        text: The host's notification, verbatim: ``<task-notification>`` ... ``</task-notification>`` for
            Claude Code 2.1.281, with one-line ``<task-id>`` and ``<status>`` elements and an optional note.
        host: The task's host (``host_contract.HOSTS``).
        version: The host version the session recorded; it must have an ``END_TOOLS`` row.

    Returns:
        The observation: the element, the status, whether the note marks the notice interim, the task id.

    Raises:
        EndObservationRefused: No format is recorded for that host version, or the text is not one notice.
    """
    row = _format(host, version)
    element = row['element']
    header = _notice_header(text, element)
    if header is None or not _matches(host_contract.HOST_TOKEN, header.get('task-id')) \
            or not _line(header.get('status'), STATUS_BYTES) or '<' in header['status']:
        raise EndObservationRefused(f"--end-observation is the host's verbatim <{element}> notice: one "
                                    f'<task-id>, one <status> of one line and at most {STATUS_BYTES} bytes, '
                                    'and its note, each on its own line')
    interim = row['backgroundWorkSentence'] in header.get('note', '')
    return EndObservation(element, header['status'], interim, header['task-id'])

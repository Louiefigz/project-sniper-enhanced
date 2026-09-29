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

import json
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
# PROVISIONAL DATA TABLE: END_TOOLS (P3b-1 [host-observed 09-28]).
# The host tools whose answer a director may quote as an end observation. The owner fills this table at
# M-102 from the M-080a host-surface probe record (PROBE.json, X30), which may change these tool or event
# names; only this table changes. It lists what may be quoted, not what counts as end evidence: that is
# M-102's HOST_END_EVIDENCE, holding only the events the probe proved (G9).
# ----------------------------------------------------------------------------------------------------------
END_TOOLS = {
    'claude-code': ('agent-notification', 'TaskStop'),
    'codex': ('wait_agent', 'list_agents', 'interrupt_agent'),
}

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


@dataclass(frozen=True)
class EndObservation:
    """What the host's own tool reported when the agent's turn ended, as the director quoted it.

    Attributes:
        tool: One of ``END_TOOLS[host]``.
        status: The host tool's own words: one line, at most ``STATUS_BYTES`` bytes.
    """

    tool: str
    status: str


def _matches(pattern: re.Pattern, value: object) -> bool:
    """True when ``value`` is a string that ``pattern`` matches in full."""
    return type(value) is str and pattern.fullmatch(value) is not None


def _line(value: object, limit: int) -> bool:
    """A non-empty single-line string without NUL whose canonical encoding fits ``limit`` bytes."""
    return type(value) is str and value.splitlines() == [value] and '\0' not in value \
        and host_contract.encoded_length(value) <= limit


def valid_agent(value: object) -> bool:
    """Whether ``value`` names one agent: a Claude Code agent id or a Codex agent path.

    Args:
        value: A ``host_contract.HOST_TOKEN`` (Claude Code ``agentId``) or an ``AGENT_PATH`` such as
            ``/root/author_q1``.

    Returns:
        True when its canonical encoding is at most ``AGENT_BYTES`` bytes. The literal ``director`` is
        refused so ``identity_key`` never confuses a subagent with its director.
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
    """Whether ``value`` is a well-formed declared handle.

    Args:
        value: A candidate handle with exactly ``DECLARED_KEYS``.

    Returns:
        True for a director (``agent`` is None) or a subagent handle of a known host and a Sniper session.
    """
    if type(value) is not dict or set(value) != DECLARED_KEYS or value['type'] != 'declared':
        return False
    if value['host'] not in host_contract.HOSTS or not _matches(SESSION, value['session']):
        return False
    return _director_ok(value) if value['agent'] is None else _subagent_ok(value)


def _is_director(value: object) -> bool:
    """A valid declared director handle."""
    return valid_declared(value) and value['agent'] is None


def director_handle(host: str, session: str, host_thread: str | None, slots: int) -> dict:
    """Build and validate a director handle; ``hostProcess`` starts as None (M-099 fills it).

    Args:
        host: One of ``host_contract.HOSTS``.
        session: A Sniper session id (``SESSION``).
        host_thread: The director's host thread when known, else None.
        slots: The session's AI slots, 2 to ``AI_POLICY['slotsCeiling']``.

    Returns:
        The declared director handle.

    Raises:
        ValueError: The handle would be invalid.
    """
    handle = {'type': 'declared', 'host': host, 'session': session, 'agent': None, 'launch': None,
              'hostThread': host_thread, 'slots': slots, 'hostProcess': None}
    if not valid_declared(handle):
        raise ValueError(DIRECTOR_REFUSAL)
    return handle


def subagent_handle(director: dict, agent: str, launch: str) -> dict:
    """Build a subagent handle in the director's host and session.

    Args:
        director: A valid declared director handle.
        agent: The subagent's agent id or path (``valid_agent``).
        launch: The 32-hex launch nonce the director put in the subagent's prompt.

    Returns:
        The declared subagent handle.

    Raises:
        ValueError: ``director`` is not a declared director handle, or the handle would be invalid.
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

    Args:
        handle: A valid declared, host or process handle.

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

    Args:
        handle: A valid handle, or None.

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
    """Whether a section result may name this identity.

    Args:
        handle: Any value.

    Returns:
        True for a declared subagent handle, or a historical host handle with a non-null turn.
    """
    if valid_declared(handle):
        return handle['agent'] is not None
    return host_contract.valid_handle(handle) and handle['type'] == 'host' and handle['turn'] is not None


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    """A JSON object whose keys are distinct: a repeated key would make the quoted report ambiguous."""
    if len({key for key, _ in pairs}) != len(pairs):
        raise ValueError('A JSON object repeats a key')
    return dict(pairs)


def _end_refusal(host: str) -> ValueError:
    """The one refusal for a malformed end observation, naming the tools of ``host``."""
    tools = ', '.join(END_TOOLS[host]) if host in host_contract.HOSTS else 'none (unknown host)'
    return ValueError(f'--end-observation is {{"tool": one of {tools}, "status": "<the host tool\'s own words, '
                      f'one line, at most {STATUS_BYTES} bytes>"}}')


def parse_end_observation(text: str, host: str) -> EndObservation:
    """Parse the director's quote of the host tool that reported an agent's end.

    Args:
        text: JSON ``{"tool": ..., "status": ...}`` with exactly those keys.
        host: The task's host; ``tool`` must be one of ``END_TOOLS[host]``.

    Returns:
        The observation, exactly as quoted.

    Raises:
        ValueError: The text, tool, status or host does not fit.
    """
    try:
        raw = json.loads(text, object_pairs_hook=_unique_object)
    except ValueError as error:
        raise _end_refusal(host) from error
    if host not in host_contract.HOSTS or type(raw) is not dict or set(raw) != {'tool', 'status'} \
            or type(raw['tool']) is not str or raw['tool'] not in END_TOOLS[host] \
            or not _line(raw['status'], STATUS_BYTES):
        raise _end_refusal(host)
    return EndObservation(raw['tool'], raw['status'])

"""Typed contract between production tasks and the operator's AI host: handles, events, capabilities.

This module is schema only. It contains no provider client, starts no process and
calls no host: an adapter outside Sniper's commands (none is built in this release)
would report what the host did, and these types decide whether that report is well
formed. Capabilities carry the §6 gate's observations per host build: supported,
unsupported or unproven, with evidence. ``governance`` turns them into what Sniper
may claim: ``unattended`` AI deadlines need absolute expiry and director enrolment,
which neither host supports (2026-09-27 gate), so the best available mode is
``supervised``: the coordinator, while alive, interrupts an exact turn and confirms
its terminal state; otherwise ``record-only``. Every host child starts from a clean
environment (``CHILD_ENVIRONMENT``): an inherited provider key silently switches
Claude Code to API-key billing.

Handles name exactly one execution: a local process by PID, process group and exact
start time (PID reuse cannot match), or a host turn by host, thread and turn id.
Usage is the host's cumulative token count for one turn; an absent field is
unknown, never zero, and cached input is a subset of input, never added to it.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass

HOSTS = ('codex', 'claude-code')
HOST_TOKEN = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}')
CATEGORY = re.compile(r'[a-z0-9][a-z0-9-]{0,63}')
SHA256 = re.compile(r'[0-9a-f]{64}')
USAGE_FIELDS = ('inputTokens', 'outputTokens', 'cachedInputTokens', 'reasoningTokens')
MAX_RECEIPTS = 8
# The conformance items of ORCHESTRATION-DESIGN-REVIEW §6 as the 2026-09-27 host gate named them,
# plus its two decisions: absolute AI expiry, and enrolment (governance) of the running director.
CAPABILITIES = ('subscriptionIdentityWithoutApiFallback', 'launchIdempotencyCallerSessionId',
                'attachExclusiveWhileLive', 'knownHostConcurrency', 'exactChildHandle', 'eventReplayAfterDisconnect',
                'interruptWithTerminalConfirmation', 'toolCleanupAfterCooperativeInterrupt',
                'toolCleanupAfterHostProcessKilled', 'nestedSubagentCleanup', 'coordinatorDeathDelayedRestart',
                'separatedUsageAttribution', 'absoluteAiExpiry', 'directorEnrollment')
VERDICTS = ('supported', 'unsupported', 'unproven')
GATE_VERDICTS = {'PASS': 'supported', 'FAIL': 'unsupported', 'UNPROVEN': 'unproven'}
# Supervised: the coordinator, while alive, interrupts an exact turn and sees its terminal state.
SUPERVISED_NEEDS = ('exactChildHandle', 'interruptWithTerminalConfirmation')
UNATTENDED_NEEDS = (*SUPERVISED_NEEDS, 'launchIdempotencyCallerSessionId', 'eventReplayAfterDisconnect',
                    'toolCleanupAfterCooperativeInterrupt', 'toolCleanupAfterHostProcessKilled',
                    'nestedSubagentCleanup', 'coordinatorDeathDelayedRestart', 'absoluteAiExpiry', 'directorEnrollment')
MODES = ('unattended', 'supervised', 'declared', 'record-only')
# A host child starts from exactly these variables: an inherited provider key silently switches Claude
# to API-key billing, and a host-session variable would bind the child to the operator's session.
CHILD_ENVIRONMENT = ('HOME', 'USER', 'LOGNAME', 'SHELL', 'TMPDIR', 'LANG', 'PATH')
EVENT_TYPES = ('accepted', 'started', 'usage', 'cancel-acknowledged', 'completed', 'failed', 'interrupted', 'lost')
TERMINAL_EVENT_TYPES = ('completed', 'failed', 'interrupted')
EVENT_KEYS = frozenset({'type', 'taskId', 'epoch', 'token', 'handle', 'sequence', 'receipts', 'failure', 'usage'})
HEX32 = re.compile(r'[0-9a-f]{32}')
MAX_COUNT = 10 ** 15      # token counts, byte sizes: bounded so a row's encoded size is bounded
MAX_PID = 2 ** 31


def encoded_length(value: str) -> int:
    """Bytes a string occupies inside the authority's canonical JSON (non-ASCII escaped), quotes excluded."""
    return len(json.dumps(value)) - 2


def clip_text(value: str, limit: int = 512) -> str:
    """The longest prefix whose canonical encoding fits ``limit`` bytes (escapes counted, never split)."""
    total, kept = 0, []
    for char in value:
        size = encoded_length(char)
        if total + size > limit:
            break
        kept.append(char)
        total += size
    return ''.join(kept)


def _text(value: object, limit: int) -> bool:
    """A non-empty single-line string whose canonical encoding fits ``limit`` bytes."""
    return type(value) is str and bool(value) and encoded_length(value) <= limit and '\n' not in value \
        and '\0' not in value


def _count(value: object) -> bool:
    """A bounded nonnegative integer (booleans excluded)."""
    return type(value) is int and 0 <= value <= MAX_COUNT


def valid_handle(value: object) -> bool:
    """A process handle {type, pid, pgid, started}, a host handle {type, host, thread, turn} or a declared handle."""
    if type(value) is not dict:
        return False
    if value.get('type') == 'process':
        return set(value) == {'type', 'pid', 'pgid', 'started'} and all(
            type(value[key]) is int and 0 < value[key] <= MAX_PID for key in ('pid', 'pgid')) \
            and _text(value['started'], 64)
    if value.get('type') == 'declared':
        from studio.production.declared_identity import valid_declared  # lazy: that module imports this one
        return valid_declared(value)
    return value.get('type') == 'host' and set(value) == {'type', 'host', 'thread', 'turn'} \
        and value['host'] in HOSTS and _token(value['thread']) and (value['turn'] is None or _token(value['turn']))


def _token(value: object) -> bool:
    """An opaque host identifier."""
    return type(value) is str and HOST_TOKEN.fullmatch(value) is not None


def require_handle(value: object) -> dict:
    """Return a copy of a valid handle or raise ValueError."""
    if not valid_handle(value):
        raise ValueError('A handle is a process {pid, pgid, started}, a host {host, thread, turn} or a declared '
                         '{host, session, agent, launch, hostThread, slots, hostProcess}')
    return dict(value)


def process_handle(pid: int, pgid: int, started: str) -> dict:
    """The exact identity of one local process (PID reuse changes ``started``)."""
    return require_handle({'type': 'process', 'pid': pid, 'pgid': pgid, 'started': started})


def host_handle(host: str, thread: str, turn: str | None) -> dict:
    """The exact identity of one host turn."""
    return require_handle({'type': 'host', 'host': host, 'thread': thread, 'turn': turn})


def valid_receipt(value: object) -> bool:
    """One immutable artifact: its path, SHA-256 and byte size (None when not measured)."""
    return type(value) is dict and set(value) == {'path', 'sha256', 'bytes'} and _text(value['path'], 1024) \
        and type(value['sha256']) is str and SHA256.fullmatch(value['sha256']) is not None \
        and (value['bytes'] is None or _count(value['bytes']))


def valid_receipts(value: object) -> bool:
    """A bounded list of distinct artifact receipts."""
    return type(value) is list and len(value) <= MAX_RECEIPTS and all(map(valid_receipt, value)) \
        and len({(row['path'], row['sha256']) for row in value}) == len(value)


def valid_failure(value: object) -> bool:
    """A failure category slug and a bounded detail."""
    return type(value) is dict and set(value) == {'category', 'detail'} and type(value['category']) is str \
        and CATEGORY.fullmatch(value['category']) is not None and type(value['detail']) is str \
        and encoded_length(value['detail']) <= 512


def valid_usage(value: object) -> bool:
    """Cumulative host token counts; None fields are unknown; cached input never exceeds input."""
    if type(value) is not dict or set(value) != set(USAGE_FIELDS):
        return False
    if not all(item is None or _count(item) for item in value.values()):
        return False
    cached, total = value['cachedInputTokens'], value['inputTokens']
    return cached is None or total is None or cached <= total


def merge_usage(old: dict | None, new: dict) -> dict:
    """Cumulative reports merge field by field to the larger known value: replay never lowers a count."""
    if not valid_usage(new):
        raise ValueError('Usage must name every token field (null when unknown); cached input is part of input')
    if old is None:
        return dict(new)
    merged = {key: max((value for value in (old[key], new[key]) if value is not None), default=None)
              for key in USAGE_FIELDS}
    if not valid_usage(merged):
        raise ValueError('Merged usage reports more cached input than input')
    return merged


@dataclass(frozen=True)
class HostCapabilities:
    """What one host build was observed to do: a verdict, evidence and caveat per capability."""

    host: str
    version: str
    verdicts: dict
    concurrency: int | None

    def supports(self, capability: str) -> bool:
        """True only for a capability observed to hold."""
        return self.verdicts[capability]['verdict'] == 'supported'


def _verdict_ok(row: object) -> bool:
    """One capability verdict; supported and unsupported are observations and cite evidence."""
    if type(row) is not dict or set(row) != {'verdict', 'evidence', 'caveat'} or row['verdict'] not in VERDICTS:
        return False
    evidence = row['evidence']
    return type(evidence) is list and len(evidence) <= 16 and all(_text(item, 256) for item in evidence) \
        and (bool(evidence) or row['verdict'] == 'unproven') \
        and (row['caveat'] is None or _text(row['caveat'], 512))


def parse_capabilities(raw: object) -> HostCapabilities:
    """Validate one host's capability record: every capability named, with its verdict and evidence."""
    if type(raw) is not dict or set(raw) != {'host', 'version', 'capabilities', 'concurrency'}:
        raise ValueError('A capability record has host, version, capabilities and concurrency')
    verdicts = raw['capabilities']
    if raw['host'] not in HOSTS or not _text(raw['version'], 64) or type(verdicts) is not dict \
            or set(verdicts) != set(CAPABILITIES) or not all(map(_verdict_ok, verdicts.values())):
        raise ValueError('A capability record names a known host and version and gives every capability a '
                         'supported, unsupported or unproven verdict (observed verdicts cite evidence)')
    concurrency, known = raw['concurrency'], verdicts['knownHostConcurrency']['verdict'] == 'supported'
    if (concurrency is None) == known or not (concurrency is None or (_count(concurrency) and concurrency > 0)):
        raise ValueError('A host concurrency is given exactly when it was observed')
    return HostCapabilities(raw['host'], raw['version'], {key: dict(row) for key, row in verdicts.items()},
                            concurrency)


def governance(capabilities: HostCapabilities | None) -> dict:
    """What Sniper may claim for AI work on this host; anything not observed to hold is not enforced.

    ``interruptCleansUp``: an interrupt's terminal confirmation also ends the turn's tools.
    ``endCleansUp``: a turn seen ended for any reason (including host death) left no tools.
    """
    if capabilities is None:
        return {'host': None, 'version': None, 'mode': 'record-only', 'unsupported': [], 'unproven': list(CAPABILITIES),
                'interruptCleansUp': False, 'endCleansUp': False}
    names = {verdict: sorted(name for name, row in capabilities.verdicts.items() if row['verdict'] == verdict)
             for verdict in ('unsupported', 'unproven')}
    mode = 'unattended' if all(map(capabilities.supports, UNATTENDED_NEEDS)) else \
        'supervised' if all(map(capabilities.supports, SUPERVISED_NEEDS)) else 'record-only'
    interrupt = capabilities.supports('toolCleanupAfterCooperativeInterrupt')
    return {'host': capabilities.host, 'version': capabilities.version, 'mode': mode, **names,
            'interruptCleansUp': interrupt,
            'endCleansUp': interrupt and capabilities.supports('toolCleanupAfterHostProcessKilled')}


def environment_problem(environment: dict) -> str | None:
    """Why an environment is not a clean host-child environment (only CHILD_ENVIRONMENT names), or None."""
    extra = sorted(name for name in environment if name not in CHILD_ENVIRONMENT)
    return f'a host child starts from a clean environment; remove {", ".join(extra[:8])}' if extra else None


@dataclass(frozen=True)
class HostEvent:
    """One host report about one claimed task, bound to the claim it was launched with."""

    type: str
    task_id: str
    epoch: int
    token: str
    handle: dict
    sequence: int
    receipts: tuple
    failure: dict | None
    usage: dict | None

    @property
    def terminal(self) -> bool:
        """Completed, failed and interrupted end the execution; an acknowledgement does not."""
        return self.type in TERMINAL_EVENT_TYPES


def parse_event(raw: object) -> HostEvent:
    """Validate one host event against the closed schema, or raise ValueError."""
    if type(raw) is not dict or set(raw) != EVENT_KEYS or raw['type'] not in EVENT_TYPES:
        raise ValueError('A host event has exactly the fields ' + ', '.join(sorted(EVENT_KEYS)))
    if type(raw['taskId']) is not str or not _count(raw['epoch']) or raw['epoch'] < 1 \
            or type(raw['token']) is not str or HEX32.fullmatch(raw['token']) is None or not _count(raw['sequence']):
        raise ValueError('A host event names its task, claim epoch, claim token and sequence')
    if not valid_handle(raw['handle']) or raw['handle']['type'] != 'host':
        raise ValueError('A host event carries the exact host handle')
    if not valid_receipts(raw['receipts']) or (raw['receipts'] and raw['type'] != 'completed'):
        raise ValueError('Only a completed event carries artifact receipts')
    if (raw['failure'] is not None) != (raw['type'] == 'failed') or \
            (raw['failure'] is not None and not valid_failure(raw['failure'])):
        raise ValueError('A failed event, and only a failed event, carries a failure category')
    if raw['usage'] is not None and not valid_usage(raw['usage']):
        raise ValueError('Host usage names every token field; unknown counts are null')
    return HostEvent(raw['type'], raw['taskId'], raw['epoch'], raw['token'], dict(raw['handle']),
                     raw['sequence'], tuple(raw['receipts']), raw['failure'], raw['usage'])


def finite_seconds(value: object) -> bool:
    """A finite nonnegative number of seconds, bounded so its encoding is bounded (booleans excluded)."""
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= MAX_COUNT

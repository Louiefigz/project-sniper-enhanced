"""Local-only ASR defaults and explicit, invocation-scoped paid admission.

Credentials and provider environment variables are configuration, not spending
authorization. Paid operation requires the two exact CLI arguments below after
the user explicitly authorizes that invocation; no automatic paid fallback.
"""
from __future__ import annotations

import argparse
import os
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Mapping

PROVIDER_ENV = "SNIPER_TRANSCRIBE_PROVIDER"
EXECUTION_MODE_ENV = "SNIPER_EXECUTION_MODE"
LOCAL_PROVIDER = "local-whisper"
DEEPGRAM_PROVIDER = "deepgram"
VALID_PROVIDERS = {LOCAL_PROVIDER, DEEPGRAM_PROVIDER}
POLICY = "local-only-unless-explicit-paid-asr-v1"


class AsrPolicyError(RuntimeError):
    """ASR requested a malformed or unauthorized spending policy."""


@dataclass(frozen=True)
class AsrInvocation:
    """Explicit CLI choices, not a value read from environment or credentials."""

    provider: str
    authorize_paid_asr: str | None = None


_ACTIVE: ContextVar[AsrInvocation | None] = ContextVar("asr_invocation", default=None)


def _validate(value: AsrInvocation) -> None:
    """Require exact paired provider/authorization choices for any paid call."""
    if (type(value) is not AsrInvocation or not isinstance(value.provider, str)
            or value.provider not in VALID_PROVIDERS):
        raise AsrPolicyError(f"{PROVIDER_ENV} must be local-whisper|deepgram")
    expected = DEEPGRAM_PROVIDER if value.provider == DEEPGRAM_PROVIDER else None
    if value.authorize_paid_asr != expected:
        raise AsrPolicyError("Paid ASR is not authorized: explicitly use --provider deepgram "
                             "--authorize-paid-asr deepgram only after user approval")


def transcription_provider(environ: Mapping[str, str] | None = None) -> str:
    """Default local even with API keys; environment can never authorize paid ASR."""
    active = _ACTIVE.get()
    if active is not None:
        _validate(active)
        return active.provider
    env = os.environ if environ is None else environ
    provider = env.get(PROVIDER_ENV, LOCAL_PROVIDER)
    if not isinstance(provider, str) or provider not in VALID_PROVIDERS:
        raise AsrPolicyError(f"{PROVIDER_ENV} must be local-whisper|deepgram")
    invocation = AsrInvocation(provider)
    _validate(invocation)
    return invocation.provider


@contextmanager
def use_asr_invocation(value: AsrInvocation) -> Iterator[None]:
    """Limit explicit paid authority to this one invocation, including async work."""
    _validate(value)
    token = _ACTIVE.set(value)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def require_paid_asr() -> None:
    """Guard actual paid sinks, including manually imported helper functions."""
    active = _ACTIVE.get()
    if active is None or active.provider != DEEPGRAM_PROVIDER:
        raise AsrPolicyError("Paid ASR is not authorized by this invocation")
    _validate(active)


def paid_deepgram_client() -> Any:
    """Do not import a paid SDK or read a credential before explicit admission."""
    require_paid_asr()
    from deepgram import AsyncDeepgramClient
    key = os.environ.get("DEEPGRAM_API_KEY")
    if not key:
        raise AsrPolicyError("Explicit paid Deepgram invocation requires DEEPGRAM_API_KEY")
    return AsyncDeepgramClient(api_key=key)


def add_asr_arguments(parser: argparse.ArgumentParser) -> None:
    """Separate provider selection from affirmative, per-invocation paid consent."""
    parser.add_argument("--provider", choices=sorted(VALID_PROVIDERS), default=None,
                        help="ASR provider (default local-whisper; never paid fallback)")
    parser.add_argument("--authorize-paid-asr", choices=[DEEPGRAM_PROVIDER], default=None,
                        help="Explicit paid-ASR authorization for this invocation only")


def invocation_from_options(options: argparse.Namespace) -> AsrInvocation:
    """An explicit authorization flag also requires an explicit matching provider."""
    provider, authorization = options.provider, options.authorize_paid_asr
    if authorization is not None and provider != DEEPGRAM_PROVIDER:
        raise AsrPolicyError("--authorize-paid-asr requires explicit --provider deepgram")
    selected = transcription_provider() if provider is None else provider
    result = AsrInvocation(selected, authorization)
    _validate(result)
    return result


def child_asr_arguments() -> list[str]:
    """Forward explicit authority as arguments, never as an inherited env flag."""
    provider = transcription_provider()
    if provider == LOCAL_PROVIDER:
        return ["--provider", LOCAL_PROVIDER]
    require_paid_asr()
    return ["--provider", DEEPGRAM_PROVIDER, "--authorize-paid-asr", DEEPGRAM_PROVIDER]


def transcription_environment(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """No key discovery or paid credential forwarding in the local child lane."""
    env = dict(os.environ if environ is None else environ)
    provider = transcription_provider(env)
    env[PROVIDER_ENV] = provider
    if provider == LOCAL_PROVIDER:
        env.pop("DEEPGRAM_API_KEY", None)
    return env


async def run_asr_cli(main: Callable[[], Any]) -> None:
    """Wrap existing distinct worker CLIs without changing their media semantics."""
    parser = argparse.ArgumentParser(add_help=False)
    add_asr_arguments(parser)
    options, remaining = parser.parse_known_args(sys.argv[1:])
    invocation = invocation_from_options(options)
    previous = sys.argv
    sys.argv = [previous[0], *remaining]
    try:
        with use_asr_invocation(invocation):
            await main()
    finally:
        sys.argv = previous

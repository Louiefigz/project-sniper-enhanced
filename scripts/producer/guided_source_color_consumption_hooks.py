"""Optional actual lossy-call/token transport; no CLI or receipt authority.

Only existing runner calls execute here. None paths retain their previous
dispatch; installed tools, ownership, deadlines and media qualification remain
the original caller's responsibility. Command metadata is held before guards.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from guided_presenter_read_fingerprint import hold_read_metadata, same_read_metadata
from guided_source_color_consumption import SourceColorPictureConsumption
from guided_source_color_consumption_records import (
    command, cut_arguments, cut_request, master_arguments, master_request,
)
from guided_source_color_consumption_publication import assert_publication, prepare_publication


@dataclass
class _Invocation:
    """Private local original arguments; never caller-provided serialized authority."""

    kind: str
    recorder: SourceColorPictureConsumption
    values: tuple
    original: object
    guard: Callable | None
    token: object = None
    argv: tuple | None = None


def _arguments(value: _Invocation) -> tuple:
    """Re-read actual typed command objects, not a silently refreshed request copy."""
    return cut_arguments(value.values) if value.kind == "cut" else master_arguments(value.values[0])


def _check(value: _Invocation) -> None:
    """Preserve original job/spec/guard/recorder identity across every callback."""
    if not same_read_metadata(_arguments(value), value.original):
        raise RuntimeError("source-color picture original command arguments changed")
    SourceColorPictureConsumption.assert_metadata(value.recorder)


def capture_options(options: object) -> Callable[[], None] | None:
    """Hold original options/recorder before setup callbacks; None keeps legacy behavior."""
    recorder = options.picture_consumption
    if recorder is None:
        return None

    def current() -> tuple:
        """Only typed original option scalars and function/capability identities are compared."""
        return (id(options), tuple(vars(options)), options.work_dir, options.proxy_scale,
                id(options.before_encode), id(options.picture_consumption))

    original = hold_read_metadata(current())

    def check() -> None:
        """Never adopt options or a new recorder after an earlier source callback."""
        if not same_read_metadata(current(), original):
            raise RuntimeError("source-color original cut options changed")
        SourceColorPictureConsumption.assert_metadata(recorder)

    check()
    return check


def check_master_inputs(value: _Invocation | None) -> None:
    """Close the original top-level spec around observations and receipt publication."""
    if value is not None:
        _check(value)


def observe_master_consumption(value: _Invocation | None, picture: object) -> None:
    """Join the actual existing PictureSource object only after its own observation returns."""
    if value is not None:
        _check(value)
        SourceColorPictureConsumption.observe_master_picture(value.recorder, picture)
        _check(value)


def finish_master_consumption(value: _Invocation | None, picture: object, proof: dict) -> None:
    """Complete only after the existing successful audio-only packet-copy verifier."""
    if value is not None:
        _check(value)
        SourceColorPictureConsumption.complete_master_copy(value.recorder, picture, proof)
        _check(value)


def check_master_publication(value: _Invocation | None, picture: object, proof: dict) -> None:
    """No later receipt construction may replace the original held command or copy proof."""
    if value is not None:
        _check(value)
        SourceColorPictureConsumption.assert_copy(value.recorder, picture, proof)
        assert_publication(value.recorder)


def prepare_master_publication(value: _Invocation | None, path: str, payload: dict) -> None:
    """Join the original top-level output before the ordinary audio publisher writes."""
    if value is not None:
        _check(value)
        prepare_publication(value.recorder, (path, payload, master_request(value.values[0])))


def capture_cut(values: tuple) -> _Invocation | None:
    """Capture the actual segment/job/output/frames tuple before command construction."""
    recorder = values[1].picture_consumption
    if recorder is None:
        return None
    SourceColorPictureConsumption.assert_metadata(recorder)
    return _Invocation("cut", recorder, values, hold_read_metadata(cut_arguments(values)), values[1].before_encode)


def capture_master(spec: object, guard: Callable | None) -> _Invocation | None:
    """Hold mutable MasterSpec before filter-building probes or original callbacks."""
    recorder = spec.picture_consumption
    if recorder is None:
        return None
    SourceColorPictureConsumption.assert_metadata(recorder)
    return _Invocation("master", recorder, (spec,), hold_read_metadata(master_arguments(spec)), guard)


def _begin(value: _Invocation, argv: list[str], guard: Callable | None) -> None:
    """Retain exact argument bytes before the original pre-native callback."""
    _check(value)
    if value.token is not None or value.guard is not guard:
        raise RuntimeError("source-color picture invocation/guard was replayed or replaced")
    value.argv = command(argv)
    if guard is not None:
        guard()
    _check(value)
    request = cut_request(value.values) if value.kind == "cut" else master_request(value.values[0])
    value.token = SourceColorPictureConsumption.begin(value.recorder, value.kind, request, value.argv)
    _check(value)
    if command(argv) != value.argv:
        raise RuntimeError("source-color picture argv changed before actual native call")


def run_picture_command(value: _Invocation, argv: list[str], runtime: tuple) -> object:
    """Record success only around the existing actual runner and original postguard."""
    guard, runner = runtime
    try:
        _begin(value, argv, guard)
        result = runner(argv)
        if value.kind == "master" and (type(result.returncode) is not int or result.returncode != 0):
            raise RuntimeError("source-color master picture native encode failed")
        if guard is not None:
            guard()
        _check(value)
        if command(argv) != value.argv:
            raise RuntimeError("source-color picture argv changed during actual native call")
        SourceColorPictureConsumption.native_completed(value.recorder, value.token)
        _check(value)
        if command(argv) != value.argv:
            raise RuntimeError("source-color picture argv changed during original completion callback")
        return result
    except BaseException:
        SourceColorPictureConsumption.failed(value.recorder)
        raise


def finish_cut_part(value: _Invocation, clamp: Callable[[], int]) -> int:
    """Keep video-copy remux completion distinct from the lossy command boundary."""
    try:
        _check(value)
        frames = clamp()
        _check(value)
        SourceColorPictureConsumption.part_completed(value.recorder, value.token, frames)
        _check(value)
        return frames
    except BaseException:
        SourceColorPictureConsumption.failed(value.recorder)
        raise

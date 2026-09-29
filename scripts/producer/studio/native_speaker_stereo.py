"""Per-word speech-band left and right levels for speaker observations (P2-06).

The levels come from ``audit.dialogue_consistency._window_rms``. That function designs its 120-3400 Hz
band-pass at ``SAMPLE_RATE`` (8000 Hz). Any other sample rate would move the band without an error, so
every entry point refuses it by name.

``lrDb`` is left minus right. It is null wherever the audio gives no left-right cue (E-S1):
- the whole source is mono, silent, dead on one channel, or dual mono (identical channels);
- one word has a dead channel (``_interval_balance``'s per-window rule, applied to the word);
- one word has no active speech-band audio.

Every such case yields a named limit sentence (``stereo_limits``). A channel level below
``SILENCE_FLOOR_DBFS`` is digital silence, and it is recorded as null rather than as the filter's
numeric floor.
"""
from __future__ import annotations

import numpy as np

from audit.dialogue_consistency import (ACTIVE_CHANNEL_DBFS, DEAD_CHANNEL_DBFS, SAMPLE_RATE, _active, _db,
                                        _window_rms)

ACTIVE_WORD_DBFS = -48.0        # the activity floor dialogue_consistency._interval_balance uses
SILENCE_FLOOR_DBFS = -120.0     # below this a channel level is digital silence and is recorded as null
IDENTICAL_CHANNELS_DB = 40.0    # left minus right this far below the louder channel: dual mono
MONO_LIMIT = 'Mono source: there is no left-right cue, so lrDb is null for every word.'
SILENT_LIMIT = 'No active speech-band audio in the source: there is no left-right cue, so lrDb is null for every word.'
DEAD_LIMIT = ('Dead channel (speech-band left {left:.1f} dBFS, right {right:.1f} dBFS): there is no left-right '
              'cue, so lrDb is null for every word.')
DUAL_MONO_LIMIT = ('Identical channels (dual mono: left minus right is {gap:.1f} dB below the louder channel): there '
                   'is no left-right cue, so lrDb is null for every word.')
DEAD_WORDS_LIMIT = ('Dead channel on source words {words} (one channel below -52 dBFS while the other is above '
                    '-35 dBFS): lrDb is null for those words.')
QUIET_WORDS_LIMIT = 'No active speech-band audio (below -48 dBFS) on source words {words}: lrDb is null for those words.'


def _require_rate(rate: int) -> None:
    """Refuse any sample rate but the one the speech-band filter is designed at."""
    if type(rate) is not int or rate != SAMPLE_RATE:
        raise ValueError(f'Speaker observation audio must be decoded at {SAMPLE_RATE} Hz, the rate _window_rms '
                         f'designs its 120-3400 Hz band-pass at; got {rate!r} Hz')


def _channels(samples: np.ndarray) -> np.ndarray:
    """Mono or stereo samples as a finite float64 (count, channels) array."""
    audio = samples.reshape(-1, 1) if isinstance(samples, np.ndarray) and samples.ndim == 1 else samples
    valid = isinstance(audio, np.ndarray) and audio.ndim == 2 and audio.shape[1] in (1, 2) and len(audio) > 0 \
        and (np.issubdtype(audio.dtype, np.integer) or np.issubdtype(audio.dtype, np.floating))
    if not valid or not np.all(np.isfinite(audio)):
        raise ValueError('Speaker observation audio must be a nonempty finite mono or stereo sample array')
    return audio.astype(np.float64)


def _band_rms(audio: np.ndarray, size: int) -> np.ndarray:
    """``_window_rms`` per channel. Its filter state is shaped for two channels, and each channel is
    filtered independently, so a mono signal goes through as two identical columns and keeps one."""
    if audio.shape[1] == 2:
        return _window_rms(audio, size)
    return _window_rms(np.repeat(audio, 2, axis=1), size)[:, :1]


def stereo_cue(samples: np.ndarray, rate: int) -> str | None:
    """Why the whole source gives no left-right cue, or None when it gives one.

    The dead-channel rule is ``_global_balance``'s: over active half-second windows, one channel is below
    DEAD_CHANNEL_DBFS while the other is above ACTIVE_CHANNEL_DBFS. Dual mono means the speech-band level
    of left minus right is at least IDENTICAL_CHANNELS_DB below the louder channel.

    Args:
        samples: Source audio at 8000 Hz, mono or stereo.
        rate: The samples' rate; anything but 8000 Hz is refused.

    Returns:
        The limit sentence (mono, silent, dead channel or dual mono), or None.
    """
    _require_rate(rate)
    audio = _channels(samples)
    if audio.shape[1] == 1:
        return MONO_LIMIT
    rms = _window_rms(audio, rate // 2)
    active = _active(rms)
    if not np.any(active):
        return SILENT_LIMIT
    left, right = (float(value) for value in _db(np.sqrt(np.mean(np.square(rms[active]), axis=0))))
    if min(left, right) < DEAD_CHANNEL_DBFS and max(left, right) > ACTIVE_CHANNEL_DBFS:
        return DEAD_LIMIT.format(left=left, right=right)
    side = _band_rms(audio[:, :1] - audio[:, 1:], rate // 2)[active]
    gap = max(left, right) - float(_db(np.sqrt(np.mean(np.square(side)))))
    return DUAL_MONO_LIMIT.format(gap=gap) if gap >= IDENTICAL_CHANNELS_DB else None


def _word_levels(audio: np.ndarray, word: dict, rate: int) -> list[float]:
    """Per-channel speech-band RMS in dBFS over one word's exact sample span.

    When the audio allows, the filter starts one span earlier. That earlier window only settles the
    filter state and is discarded, so the word's own window is measured with settled state.
    """
    low = round(word['start'] * rate)
    high = min(len(audio), max(low + 1, round(word['end'] * rate)))
    if low >= high:
        raise ValueError(f"Source word {word['sourceWord']} lies beyond the decoded audio")
    span = high - low
    before = span if low >= span else 0
    return [float(value) for value in _db(_band_rms(audio[low - before:high], span)[1 if before else 0])]


def _shown(level: float) -> float | None:
    """A channel level as recorded: null below SILENCE_FLOOR_DBFS (digital silence)."""
    return None if level < SILENCE_FLOOR_DBFS else round(level, 2)


def _dead(left: float | None, right: float | None) -> bool:
    """``_interval_balance``'s dead-channel rule on recorded levels (null counts as silence)."""
    levels = [-np.inf if value is None else value for value in (left, right)]
    return min(levels) < DEAD_CHANNEL_DBFS and max(levels) > ACTIVE_CHANNEL_DBFS


def stereo_rows(samples: np.ndarray, words: list[dict], rate: int) -> list[dict]:
    """Per retained word: speech-band left and right levels and their difference (left minus right).

    Args:
        samples: Source audio at 8000 Hz; mono (count,) or (count, 1), or stereo (count, 2).
        words: Retained ``{sourceWord, text, start, end}`` rows.
        rate: The samples' rate. Any rate but 8000 Hz is refused by name.

    Returns:
        ``{sourceWord, start, end, leftDb, rightDb, lrDb, active}`` rows. A mono source has no channel
        levels. ``lrDb`` is None when the source gives no cue, or when the word is inactive or has a dead
        channel; ``stereo_limits`` names each case.

    Raises:
        ValueError: Another sample rate, malformed audio, or a word beyond the decoded audio.
    """
    _require_rate(rate)
    audio = _channels(samples)
    usable = stereo_cue(audio, rate) is None
    rows = []
    for word in words:
        levels = _word_levels(audio, word, rate)
        left, right = (_shown(levels[0]), _shown(levels[1])) if len(levels) == 2 else (None, None)
        active = max(levels) >= ACTIVE_WORD_DBFS
        cue = len(levels) == 2 and usable and active and not _dead(left, right)
        rows.append({'sourceWord': word['sourceWord'], 'start': word['start'], 'end': word['end'],
                     'leftDb': left, 'rightDb': right, 'lrDb': round(levels[0] - levels[1], 2) if cue else None,
                     'active': active})
    return rows


def _spans(words: list[int]) -> str:
    """Ascending word indexes as runs: ``3-5, 9``."""
    runs: list[list[int]] = []
    for word in words:
        if runs and word == runs[-1][1] + 1:
            runs[-1][1] = word
        else:
            runs.append([word, word])
    return ', '.join(str(first) if first == last else f'{first}-{last}' for first, last in runs)


def stereo_limits(samples: np.ndarray, rows: list[dict], rate: int) -> list[str]:
    """The limit sentences for every null ``lrDb`` in ``rows``.

    Args:
        samples: The same audio ``stereo_rows`` measured.
        rows: ``stereo_rows``' result.
        rate: 8000.

    Returns:
        The source-level limit when the source gives no cue. Otherwise one sentence naming the words with a
        dead channel and one naming the inactive words, each present only when it applies.
    """
    cue = stereo_cue(samples, rate)
    if cue:
        return [cue]
    dead = [row['sourceWord'] for row in rows if row['active'] and _dead(row['leftDb'], row['rightDb'])]
    quiet = [row['sourceWord'] for row in rows if not row['active']]
    limits = []
    if dead:
        limits.append(DEAD_WORDS_LIMIT.format(words=_spans(dead)))
    if quiet:
        limits.append(QUIET_WORDS_LIMIT.format(words=_spans(quiet)))
    return limits

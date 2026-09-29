"""Per-word speech-band left and right levels for speaker observations (P2-06).

The levels come from ``audit.dialogue_consistency._window_rms``, which designs its 120-3400 Hz band-pass at
``SAMPLE_RATE`` (8000 Hz). Any other sample rate would move the band without an error, so every entry point
refuses it by name. A mono, silent or dead-channel source gives no left-right cue: ``lrDb`` is null for every
word, and ``stereo_cue`` returns the limit sentence the record carries.
"""
from __future__ import annotations

import numpy as np

from audit.dialogue_consistency import (ACTIVE_CHANNEL_DBFS, DEAD_CHANNEL_DBFS, SAMPLE_RATE, _active, _db,
                                        _window_rms)

ACTIVE_WORD_DBFS = -48.0   # the activity floor dialogue_consistency._interval_balance uses
MONO_LIMIT = 'Mono source: there is no left-right cue, so lrDb is null for every word.'
SILENT_LIMIT = 'No active speech-band audio in the source: there is no left-right cue, so lrDb is null for every word.'
DEAD_LIMIT = ('Dead channel (speech-band left {left:.1f} dBFS, right {right:.1f} dBFS): there is no left-right '
              'cue, so lrDb is null for every word.')


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


def stereo_cue(samples: np.ndarray, rate: int) -> str | None:
    """Why the source gives no left-right cue (mono, silent or a dead channel), or None when it gives one.

    The dead-channel rule is ``dialogue_consistency._global_balance``'s: over active half-second windows,
    one channel is below DEAD_CHANNEL_DBFS while the other is above ACTIVE_CHANNEL_DBFS.
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
    return None


def _band_rms(audio: np.ndarray, size: int) -> np.ndarray:
    """``_window_rms`` per channel. Its filter state is shaped for two channels, and each channel is
    filtered independently, so a mono source goes through as two identical columns and keeps one."""
    if audio.shape[1] == 2:
        return _window_rms(audio, size)
    return _window_rms(np.repeat(audio, 2, axis=1), size)[:, :1]


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


def stereo_rows(samples: np.ndarray, words: list[dict], rate: int) -> list[dict]:
    """Per retained word: speech-band left and right levels and their difference (left minus right).

    Args:
        samples: Source audio at 8000 Hz; mono (count,) or (count, 1), or stereo (count, 2).
        words: Retained ``{sourceWord, text, start, end}`` rows.
        rate: The samples' rate. Any rate but 8000 Hz is refused by name.

    Returns:
        ``{sourceWord, start, end, leftDb, rightDb, lrDb, active}`` rows. A mono source has no channel
        levels. Mono, silent or dead-channel audio gives ``lrDb: None``; ``stereo_cue`` names that limit.

    Raises:
        ValueError: Another sample rate, malformed audio, or a word beyond the decoded audio.
    """
    _require_rate(rate)
    audio = _channels(samples)
    usable = stereo_cue(audio, rate) is None
    rows = []
    for word in words:
        levels = _word_levels(audio, word, rate)
        stereo = len(levels) == 2
        rows.append({'sourceWord': word['sourceWord'], 'start': word['start'], 'end': word['end'],
                     'leftDb': round(levels[0], 2) if stereo else None,
                     'rightDb': round(levels[1], 2) if stereo else None,
                     'lrDb': round(levels[0] - levels[1], 2) if stereo and usable else None,
                     'active': max(levels) >= ACTIVE_WORD_DBFS})
    return rows

"""Windowed, sample-aligned stereo PCM comparison for audio QC.

Inputs are floating PCM in full-scale units, already decoded and aligned by the
caller. This performs no file reads, resampling, lag fitting or gain correction.
RMS activity is an engineering proxy, not speech recognition or listening review.
Audio working buffers cover one second; the report grows with window count.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np


@dataclass(frozen=True)
class PCMThresholds:
    """Conservative screening thresholds; failures require investigation."""

    active_reference_dbfs: float = -50.0
    minimum_rms_ratio: float = 0.85
    maximum_rms_ratio: float = 1.15
    minimum_correlation: float = 0.98
    minimum_snr_db: float = 20.0
    maximum_quiet_error_dbfs: float = -60.0

    def __post_init__(self) -> None:
        """Reject nonfinite or contradictory thresholds instead of weakening QC."""
        values = asdict(self).values()
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
            raise ValueError('PCM thresholds must be finite numbers')
        valid = (
            self.maximum_quiet_error_dbfs <= self.active_reference_dbfs < 0
            and 0 < self.minimum_rms_ratio <= 1 <= self.maximum_rms_ratio
            and 0 < self.minimum_correlation <= 1 and self.minimum_snr_db > 0
        )
        if not valid:
            raise ValueError('PCM threshold ranges are invalid')


@dataclass(frozen=True)
class PCMComparisonConfig:
    """The caller explicitly declares sample count, rate and decoder padding."""

    expected_samples: int
    sample_rate: int
    maximum_decoder_padding: int
    thresholds: PCMThresholds = field(default_factory=PCMThresholds)

    def __post_init__(self) -> None:
        """Require exact integer counts and an exact half-second hop."""
        counts = (self.expected_samples, self.sample_rate, self.maximum_decoder_padding)
        if any(type(value) is not int for value in counts):
            raise ValueError('PCM sample counts, rate and padding bound must be integers')
        if self.expected_samples <= 0 or self.sample_rate <= 0 or self.sample_rate % 2:
            raise ValueError('Positive sample count and positive even sample rate required')
        if self.maximum_decoder_padding < 0 or not isinstance(self.thresholds, PCMThresholds):
            raise ValueError('Explicit nonnegative padding bound and PCM thresholds required')


def validate_array(array: np.ndarray, label: str) -> None:
    """Require finite floating stereo PCM, including any decoder padding."""
    if not isinstance(array, np.ndarray) or array.ndim != 2 or array.shape[1] != 2:
        raise ValueError(f'{label} must be a two-channel NumPy array')
    if not np.issubdtype(array.dtype, np.floating):
        raise ValueError(f'{label} must use floating PCM in full-scale units')
    for start in range(0, len(array), 480000):
        if not np.isfinite(array[start:start + 480000]).all():
            raise ValueError(f'{label} contains nonfinite PCM samples')


def validate_inputs(reference: np.ndarray, candidate: np.ndarray,
                    config: PCMComparisonConfig) -> int:
    """Reject truncation and excess padding without trimming away mismatches."""
    validate_array(reference, 'Reference')
    validate_array(candidate, 'Candidate')
    if len(reference) != config.expected_samples:
        raise ValueError('Reference sample count differs from the declared count')
    padding = len(candidate) - config.expected_samples
    if not 0 <= padding <= config.maximum_decoder_padding:
        raise ValueError('Candidate is truncated or exceeds the declared decoder padding bound')
    return padding


def signal_sums(reference: np.ndarray, candidate: np.ndarray) -> dict:
    """Calculate energy terms on a bounded slice using float64 arithmetic."""
    reference = np.asarray(reference, dtype=np.float64)
    candidate = np.asarray(candidate, dtype=np.float64)
    try:
        with np.errstate(over='raise', invalid='raise'):
            error = candidate - reference
            sums = {
                'reference': float(np.sum(reference * reference)),
                'candidate': float(np.sum(candidate * candidate)),
                'error': float(np.sum(error * error)),
                'cross': float(np.sum(reference * candidate)),
                'count': reference.size,
            }
    except FloatingPointError as error:
        raise ValueError('PCM arithmetic overflowed; measurements are unavailable') from error
    if not all(math.isfinite(value) for value in sums.values()):
        raise ValueError('PCM measurements are nonfinite')
    return sums


def metrics(sums: dict) -> dict:
    """Return JSON-safe RMS, zero-lag normalized correlation and SNR values."""
    reference, candidate, error = sums['reference'], sums['candidate'], sums['error']
    correlation = None
    if reference > 0 and candidate > 0:
        denominator = math.sqrt(reference) * math.sqrt(candidate)
        correlation = max(-1.0, min(1.0, sums['cross'] / denominator))
    snr = None
    if reference > 0 and error > 0:
        snr = 10 * (math.log10(reference) - math.log10(error))
    measured = {
        'referenceRms': math.sqrt(reference / sums['count']),
        'candidateRms': math.sqrt(candidate / sums['count']),
        'errorRms': math.sqrt(error / sums['count']),
        'rmsRatio': math.sqrt(candidate) / math.sqrt(reference) if reference > 0 else None,
        'correlation': correlation, 'snrDb': snr,
        'snrInfinite': reference > 0 and error == 0,
    }
    if any(isinstance(value, float) and not math.isfinite(value) for value in measured.values()):
        raise ValueError('Derived PCM metrics are nonfinite')
    return measured


def active_failures(measured: dict, thresholds: PCMThresholds) -> list[str]:
    """Require level, waveform and error checks to pass independently."""
    ratio, correlation, snr = (measured[key] for key in ('rmsRatio', 'correlation', 'snrDb'))
    checks = [
        (ratio is not None and thresholds.minimum_rms_ratio <= ratio
         <= thresholds.maximum_rms_ratio, 'active-rms-ratio-outside-bound'),
        (correlation is not None and correlation >= thresholds.minimum_correlation,
         'active-correlation-below-bound-or-undefined'),
        (measured['snrInfinite'] or snr is not None and snr >= thresholds.minimum_snr_db,
         'active-snr-below-bound-or-undefined'),
    ]
    return [reason for passed, reason in checks if not passed]


def channel_window(reference: np.ndarray, candidate: np.ndarray,
                   thresholds: PCMThresholds) -> dict:
    """Distinguish reference-active content from quiet-window error screening."""
    measured = metrics(signal_sums(reference, candidate))
    active = measured['referenceRms'] >= 10 ** (thresholds.active_reference_dbfs / 20)
    if active:
        failures = active_failures(measured, thresholds)
    else:
        limit = 10 ** (thresholds.maximum_quiet_error_dbfs / 20)
        failures = [] if measured['errorRms'] <= limit else ['quiet-error-rms-above-bound']
    return {**measured, 'activity': 'reference-active' if active else 'quiet',
            'passed': not failures, 'failures': failures}


def window_starts(config: PCMComparisonConfig) -> list[int]:
    """Use one-second windows at half-second hops, plus complete tail coverage."""
    final_start = max(0, config.expected_samples - config.sample_rate)
    starts = list(range(0, final_start + 1, config.sample_rate // 2))
    if starts[-1] != final_start:
        starts.append(final_start)
    return starts


def global_metrics(reference: np.ndarray, candidate: np.ndarray,
                   config: PCMComparisonConfig) -> dict:
    """Compute whole-program context without allocating a whole-program copy."""
    totals = dict(reference=0.0, candidate=0.0, error=0.0, cross=0.0, count=0)
    for start in range(0, config.expected_samples, config.sample_rate):
        stop = min(start + config.sample_rate, config.expected_samples)
        values = signal_sums(reference[start:stop], candidate[start:stop])
        for key, value in values.items():
            totals[key] += value
    if not all(math.isfinite(value) for value in totals.values()):
        raise ValueError('Whole-program PCM measurements overflowed')
    return metrics(totals)


def compare_pcm(reference: np.ndarray, candidate: np.ndarray,
                config: PCMComparisonConfig) -> dict:
    """Measure aligned decoded PCM; never claim perceptual or container approval."""
    padding = validate_inputs(reference, candidate, config)
    windows = []
    for start in window_starts(config):
        stop = min(start + config.sample_rate, config.expected_samples)
        channels = [channel_window(reference[start:stop, channel], candidate[start:stop, channel],
                                   config.thresholds) for channel in range(2)]
        windows.append({
            'startSample': start, 'endSample': stop,
            'startSeconds': start / config.sample_rate, 'endSeconds': stop / config.sample_rate,
            'shortWindow': stop - start < config.sample_rate,
            'channels': channels, 'passed': all(row['passed'] for row in channels),
        })
    active = sum(row['activity'] == 'reference-active' for w in windows for row in w['channels'])
    failed = [index for index, window in enumerate(windows) if not window['passed']]
    return {
        'schemaVersion': 1, 'status': 'local-signal-checks-failed' if failed else 'local-signal-checks-pass',
        'passed': not failed, 'expectedSamples': config.expected_samples, 'sampleRate': config.sample_rate,
        'decodedPaddingSamples': padding, 'maximumDecoderPaddingSamples': config.maximum_decoder_padding,
        'windowSeconds': 1.0, 'hopSeconds': 0.5, 'finalWindowMayUseShorterHop': True,
        'thresholds': asdict(config.thresholds), 'activeChannelWindows': active,
        'quietChannelWindows': len(windows) * 2 - active, 'activeEvidenceAvailable': active > 0,
        'failedWindowCount': len(failed), 'failedWindowIndices': failed,
        'globalMetrics': global_metrics(reference, candidate, config), 'windows': windows,
        'alignment': 'Zero lag; no resampling, shifting or gain fitting',
        'activityDefinition': 'Reference RMS threshold per channel; not semantic voice detection',
        'scope': 'Decoded PCM comparison only; codec/container/padding metadata need separate verification',
        'humanListeningApproved': False, 'perceptualQualityApproved': False,
    }

"""Admit the actual qualified AAC donor and precheck its float master without DSP."""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from audio.aac_peak_candidates import effective_reuse_profile
from audio.audio_mix_delivery import measure_delivery
from audio.mastering_profile import MasteringProfile
from audio.native_aac_encoding import require_native_aac_policy
from audio.program_audio_clock import exact_float_audio_clock
from audit.audio_quality import check_audio_program_quality
from audit.audit_checks import FAIL, PASS, WARN
from cut_preview_io import bound_json, file_hash, write_new
from producer_config import MASTERING_POLICY_VERSION

if TYPE_CHECKING:
    from audio.native_dialogue_delivery import NativeDialogueDelivery
    from audio.native_master_preparation import NativeMasterPreparation

LOGGER = logging.getLogger(__name__)
DONOR_STATUS = 'audio-donor-checked-awaiting-picture'


@dataclass(frozen=True)
class AdmittedAudioDonor:
    """Exact receipt, master, encoded candidate and reconstructed effective profile."""

    prior: dict
    path: Path
    sha256: str
    master: Path
    candidate: Path
    profile: MasteringProfile
    aac_policy: dict


def admit_audio_donor(path: Path, premaster: tuple[Path, str], samples: int,
                      profile: MasteringProfile) -> AdmittedAudioDonor:
    """Share all prior-reuse policy, correction history, source and artifact checks."""
    if file_hash(premaster[0]) != premaster[1]:
        raise RuntimeError('Native donor premaster changed')
    sha = file_hash(path)
    prior = bound_json(path, sha)
    required = {'masteringFilter', 'masteringNote', 'masteringPolicyVersion', 'masterSha256'}
    if not required.issubset(prior):
        raise ValueError('Native dialogue reuse receipt is incomplete or malformed')
    effective = effective_reuse_profile(prior, profile)
    policy = require_native_aac_policy(prior, profile)
    master, candidate = path.parent / 'program-master.wav', path.parent / 'candidate.mp4'
    if prior.get('status') != 'audio-qualified' or prior.get('inputPremasterSha256') != premaster[1] \
            or prior.get('masteringPolicyVersion') != MASTERING_POLICY_VERSION \
            or prior.get('audioClock', {}).get('presentedSamples') != samples \
            or file_hash(master) != prior.get('masterSha256') \
            or file_hash(candidate) != prior.get('candidateSha256'):
        raise RuntimeError('Native dialogue reuse lacks unchanged input, policy or encoded bytes')
    return AdmittedAudioDonor(prior, path, sha, master, candidate, effective, policy)


def verify_audio_donor(donor: AdmittedAudioDonor) -> None:
    """Retain each exact input through measurement and final encoded qualification."""
    if file_hash(donor.path) != donor.sha256 or file_hash(donor.master) != donor.prior['masterSha256'] \
            or file_hash(donor.candidate) != donor.prior['candidateSha256']:
        raise RuntimeError('Native prior audio authority changed during reuse')


def prepare_audio_donor(request: NativeMasterPreparation, prior: Path,
                        tools: tuple[str, str]) -> tuple[Path, str]:
    """Measure the admitted donor master before picture, with zero mastering or AAC work."""
    request.directory.mkdir(exist_ok=False)
    path = request.directory / 'receipt.json'
    record = {'schemaVersion': 1, 'status': 'incomplete', 'humanListeningApproved': False,
              'inputPremasterSha256': request.premaster_sha256, 'samples': request.samples,
              'requestedMasteringProfile': request.profile.receipt(),
              'reviewSections': list(request.review_sections), 'additionalAacEncodes': 0,
              'additionalMasteringPasses': 0}
    try:
        donor = admit_audio_donor(prior, (request.premaster, request.premaster_sha256),
                                  request.samples, request.profile)
        record.update(donorReceipt=str(prior), donorReceiptSha256=donor.sha256,
            output=str(donor.master), masterSha256=donor.prior['masterSha256'],
            candidateSha256=donor.prior['candidateSha256'], masteringProfile=donor.profile.receipt(),
            aacEncodingPolicy=donor.aac_policy,
            premasterClock=exact_float_audio_clock(str(request.premaster), tools[1], request.samples),
            masterClock=exact_float_audio_clock(str(donor.master), tools[1], request.samples),
            masterDelivery=measure_delivery(str(donor.master)))
        plan = {'audioReviewSections': list(request.review_sections)} if request.review_sections else {}
        checks = check_audio_program_quality(str(donor.master), plan)
        record['audioQuality'] = [dict(name=row.name, status=row.status, measured=row.measured,
                                      detail=row.detail) for row in checks]
        record['audioReviewRequired'] = any(row.status == WARN for row in checks)
        if not record['masterDelivery']['qualified'] or any(row.status == FAIL for row in checks):
            raise RuntimeError('Early native donor master failed shared audio quality checks')
        verify_audio_donor(donor)
        if file_hash(request.premaster) != request.premaster_sha256:
            raise RuntimeError('Native donor premaster changed')
        record['status'] = DONOR_STATUS
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        record.update(status='failed', error=str(error))
        LOGGER.error('Early native donor preparation failed: %s', error)
        raise
    finally:
        write_new(path, record)
    return path, file_hash(path)


def verify_prepared_donor(request: NativeDialogueDelivery, donor: AdmittedAudioDonor) -> str:
    """Require the early proof to describe this exact donor and current review sections."""
    path, sha = request.prepared_donor
    record = bound_json(path, sha)
    expected = {'status': DONOR_STATUS, 'inputPremasterSha256': request.premaster_sha256,
        'samples': request.samples, 'requestedMasteringProfile': request.profile.receipt(),
        'reviewSections': list(request.review_sections), 'donorReceipt': str(donor.path),
        'donorReceiptSha256': donor.sha256, 'output': str(donor.master),
        'masterSha256': donor.prior['masterSha256'], 'candidateSha256': donor.prior['candidateSha256'],
        'masteringProfile': donor.profile.receipt(), 'aacEncodingPolicy': donor.aac_policy}
    checks = record.get('audioQuality')
    if any(record.get(key) != value for key, value in expected.items()) \
            or record.get('masterDelivery', {}).get('qualified') is not True \
            or not isinstance(checks, list) or not checks \
            or any(not isinstance(row, dict) or row.get('status') not in (PASS, WARN) for row in checks):
        raise RuntimeError('Prepared audio donor differs from current delivery inputs or quality')
    return sha

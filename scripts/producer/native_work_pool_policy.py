"""Host-wide native pool budgets derived from physical RAM and measured owner trees.

Evidence: docs/findings/SHORTS_FULL_RUN_AUDIT_2026_09_27.md and the owner resource
logs it retains (Apple M3 Max, 16 cores, 64 GiB; 2,324 samples; kernel pressure normal
in every sample). Largest sampled owned tree per owner class on the current url-v1
route: pipeline 3.165 GiB (largest single process 1.375 GiB), capture 1.194,
preview-picture 1.186, verification 0.999; ffmpeg-only owners: audio-diagnostic
inspection 0.280, selected-sources 0.270, preview-package 0.170, audio-check 0.150.

Derivation (policy, not an SDK or OS quota; the owner guard enforces it by sampling):
- Aggregate native budget = 50% of physical RAM. Today one job may grow to
  min(16 GiB, 25% of RAM) while admission demands 25% system-wide headroom; the pool
  may hold at most two such allowances in total, leaving at least half of physical
  memory to macOS, the compressor and the operator's applications. 64 GiB -> 32 GiB.
- Qualified heavy reservation = 6 GiB: 1.9x the largest sampled tree (3.165 GiB) and
  2.7x the second batch's final-render peak (2.236 GiB), covering unsampled spikes
  between five-second readings. It is also that owner's guard stop limit.
- Qualified audio reservation = 1 GiB: 3.6x the largest sampled ffmpeg-only tree.
- Five heavy (30 GiB) plus one audio (1 GiB) fit 32 GiB; five independent 16 GiB
  allowances (80 GiB) cannot be admitted because every live, quarantined and legacy
  reservation is summed against the aggregate before a new member is admitted.
- Without a valid host qualification record the pool is exclusive: one member at a
  time across classes, reserving today's min(16 GiB, 25% RAM) — the previous behaviour.
- Disk: each member reserves bytes on its output filesystem. Admission requires live
  free space minus other members' reservations to cover its own plus the existing
  10 GiB reserve. Heavy 3 GiB = 2.6x the largest audited Short attempt directory
  (1.16 GiB, IMG_5954 E preview-v6); audio 1 GiB (prepared WAV/AAC are tens of MB).
- Studio startup (native_work_pool_studio.py) has its own ledger class and slots. Its
  reservations are PROVISIONAL: no Studio startup tree has been measured yet (P1 R-9).
  They are outside policy_identity(), so every committed qualification record stays valid.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field, replace

GIB = 1024 ** 3
LAYOUT = 'native-work-pool-v1'
POOL_CLASSES = ('heavy', 'audio')
AGGREGATE_FRACTION_PERCENT = 50
SINGLE_JOB_FRACTION_PERCENT = 25
SINGLE_JOB_CAP_BYTES = 16 * GIB
RESERVATION_BYTES = {'heavy': 6 * GIB, 'audio': 1 * GIB}
DISK_RESERVATION_BYTES = {'heavy': 3 * GIB, 'audio': 1 * GIB}
DISK_RESERVE_BYTES = 10 * GIB
SLOT_BOUNDS = {'heavy': (2, 5), 'audio': (1, 2)}
STUDIO_CLASS = 'studio'  # a Studio view's startup: its own slots, never a render slot
STUDIO_SLOTS = 2  # provisional
STUDIO_RESERVATION_BYTES = RESERVATION_BYTES['audio']  # 1 GiB, provisional (unmeasured, P1 R-9)
STUDIO_DISK_BYTES = 256 * 1024 ** 2  # provisional (unmeasured, P1 R-9)
LEDGER_CLASSES = (*POOL_CLASSES, STUDIO_CLASS)  # every class a member record may carry
QUEUE_SECONDS = 600
HOST_IDENTITY_TIMEOUT_SECONDS = 3  # bounds one sysctl read; the queue clock's poll bound counts it
MEASURED_EVIDENCE = {
    'source': 'SHORTS_FULL_RUN_AUDIT_2026_09_27 owner resource logs',
    'samples': 2324, 'largestHeavyTreeBytes': int(3.165 * GIB),
    'largestAudioClassTreeBytes': int(0.280 * GIB),
    'largestShortAttemptDirectoryBytes': 1215844 * 1024,
}
HOST_KEYS = ('machdep.cpu.brand_string', 'hw.physicalcpu', 'hw.logicalcpu',
             'hw.memsize', 'kern.osproductversion', 'kern.osversion')


class PoolPolicyError(RuntimeError):
    """Host identity or pool configuration cannot be established exactly."""


@dataclass(frozen=True)
class PoolMode:
    """The capacity rule one admission decision applies.

    Attributes:
        name: 'exclusive', 'qualified' or 'qualification-session'.
        slots: Per-class slot counts; exclusive mode uses {'*': 1}.
        record: Path/digest of the qualification record or session that was used.
        rejected: Why a present record was not usable (exclusive mode only).
    """

    name: str
    slots: dict = field(default_factory=lambda: {'*': 1})
    record: dict | None = None
    rejected: str | None = None

    @property
    def exclusive(self) -> bool:
        """One member at a time across every class, as before the pool existed."""
        return self.name == 'exclusive'


def policy_identity() -> dict:
    """Constants a qualification was measured under; any change voids the record."""
    return {'layout': LAYOUT, 'aggregateFractionPercent': AGGREGATE_FRACTION_PERCENT,
            'singleJobFractionPercent': SINGLE_JOB_FRACTION_PERCENT,
            'singleJobCapBytes': SINGLE_JOB_CAP_BYTES,
            'reservationBytes': dict(RESERVATION_BYTES),
            'diskReservationBytes': dict(DISK_RESERVATION_BYTES),
            'diskReserveBytes': DISK_RESERVE_BYTES,
            'slotBounds': {key: list(value) for key, value in SLOT_BOUNDS.items()}}


def host_identity() -> dict:
    """Read CPU model, core counts, physical RAM and OS version in one sysctl call."""
    result = subprocess.run(['/usr/sbin/sysctl', '-n', *HOST_KEYS], capture_output=True, text=True, check=True,
                            timeout=HOST_IDENTITY_TIMEOUT_SECONDS, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
    lines = result.stdout.splitlines()
    if result.stderr.strip() or len(lines) != len(HOST_KEYS) or not all(line.strip() for line in lines):
        raise PoolPolicyError('Host identity sysctl output is incomplete')
    try:
        numbers = [int(value) for value in lines[1:4]]
    except ValueError as error:
        raise PoolPolicyError('Host identity counters are not integers') from error
    if min(numbers) <= 0:
        raise PoolPolicyError('Host identity counters must be positive')
    return {'cpuBrand': lines[0].strip(), 'physicalCpus': numbers[0], 'logicalCpus': numbers[1],
            'memsizeBytes': numbers[2], 'osProductVersion': lines[4].strip(),
            'osBuild': lines[5].strip()}


def single_job_bytes(physical: int) -> int:
    """Today's owned-tree allowance: min(16 GiB, 25% of physical RAM)."""
    return min(SINGLE_JOB_CAP_BYTES, physical * SINGLE_JOB_FRACTION_PERCENT // 100)


def aggregate_bytes(physical: int) -> int:
    """Total memory every native reservation together may claim."""
    return physical * AGGREGATE_FRACTION_PERCENT // 100


def feasible_slots(slots: dict, physical: int) -> bool:
    """Require every configured slot to fit its full reservation simultaneously."""
    if set(slots) != set(POOL_CLASSES):
        return False
    for lane, (low, high) in SLOT_BOUNDS.items():
        if type(slots[lane]) is not int or not low <= slots[lane] <= high:
            return False
    total = sum(slots[lane] * RESERVATION_BYTES[lane] for lane in POOL_CLASSES)
    return total <= aggregate_bytes(physical)


def reservation_bytes(mode: PoolMode, lane: str, physical: int,
                      fixed_owned_gib: float | None) -> int:
    """Memory one member reserves; the owner's guard may never stop above it.

    Args:
        mode: The capacity rule used for this admission.
        lane: 'heavy' or 'audio'.
        physical: Measured physical RAM in bytes.
        fixed_owned_gib: An explicit caller ResourcePolicy owned-tree limit, if any.

    Returns:
        Reserved bytes, bounded by today's single-job allowance.
    """
    if fixed_owned_gib is not None:
        return min(int(fixed_owned_gib * GIB), physical * SINGLE_JOB_FRACTION_PERCENT // 100)
    if mode.exclusive:
        return single_job_bytes(physical)
    return RESERVATION_BYTES[lane]


def class_capacity(mode: PoolMode, lane: str) -> int:
    """Slots available to one class (exclusive mode shares its single slot)."""
    return mode.slots['*'] if mode.exclusive else mode.slots[lane]


def queue_key(mode: PoolMode, lane: str) -> str:
    """Tickets compete only with requests for the same capacity."""
    return f'{mode.name}:*' if mode.exclusive else f'{mode.name}:{lane}'


def reserved_policy(resource_policy: object, reservation: int) -> object:
    """Bound the guard's owned-tree and per-process stops by the ledger reservation.

    Args:
        resource_policy: The ResourcePolicy derived for this owner's baseline.
        reservation: Bytes this member reserved against the host budget.

    Returns:
        The same policy when it already stops at or below the reservation.
    """
    if type(reservation) is not int or reservation <= 0:
        raise PoolPolicyError('Native pool member did not report a positive memory reservation')
    limit = reservation / GIB
    if resource_policy.maximum_owned_gib <= limit and resource_policy.maximum_process_gib <= limit * .75:
        return resource_policy
    return replace(resource_policy, maximum_owned_gib=min(resource_policy.maximum_owned_gib, limit),
                   maximum_process_gib=min(resource_policy.maximum_process_gib, limit * .75))

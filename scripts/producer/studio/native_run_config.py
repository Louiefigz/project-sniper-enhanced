"""Explicit native render settings; no historical paths or inherited credentials."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
import math
import os
from typing import Literal
from collections.abc import Callable

from graphics.render_tools import resolve_tools
from native_render_resources import ResourcePolicy, ResourceSnapshot
from native_render_policy import capacity_policy
from native_work_pool_policy import POOL_CLASSES
from stage_timing_context import LINEAGE_VARIABLES, lineage_environment
from studio.native_runtime import digest


@dataclass(frozen=True)
class NativeRunConfig:
    """One bounded local attempt using the existing resource and ownership gates."""

    project: Path
    root: Path
    cli: Path
    command: list[str]
    environment: dict[str, str]
    admission: dict
    sandbox: Path = Path(__file__).with_name('native_localhost_only.sb')
    policy: ResourcePolicy | None = None
    deadline: float = 600
    additional_pins: dict[str, str] = field(default_factory=dict)
    success_status: str = 'rendered-awaiting-output-qc'
    unused_ram_advisory: bool = False
    compressor_admission: Literal['fixed', 'short-headroom'] = 'fixed'
    idle_deadline: float | None = None
    capacity_wait_seconds: float = 0
    lane: str = 'heavy'
    disk_reservation_bytes: int | None = None
    disk_expansion: bool = False
    hard_deadline: dict | None = None
    before_launch: Callable[[], dict | None] | None = None
    serves: tuple[Path, ...] | None = None
    queue_work_seconds: float | None = None
    output_digest_limit: int | None = None

    def __post_init__(self) -> None:
        """Reject invalid metadata before any owner can acquire or launch heavy work."""
        if self.compressor_admission not in {'fixed', 'short-headroom'}:
            raise ValueError('Unknown native compressor admission policy')
        if self.lane not in POOL_CLASSES:
            raise ValueError('Native owner lane must be a pool class')
        if type(self.disk_expansion) is not bool:
            raise ValueError('Native disk expansion must be an explicit boolean')
        if self.disk_reservation_bytes is not None and (
                type(self.disk_reservation_bytes) is not int or self.disk_reservation_bytes < 0):
            raise ValueError('Native disk reservation must be a nonnegative integer')
        if self.policy is not None and not isinstance(self.policy, ResourcePolicy):
            raise ValueError('Native policy must be an explicit ResourcePolicy or capacity-derived default')
        validate_allocation(self.hard_deadline)
        if self.before_launch is not None and (not callable(self.before_launch) or self.hard_deadline is None):
            raise ValueError('A launch callback requires a callable and an inherited production deadline')
        self.validate_admission()
        object.__setattr__(self, 'admission', dict(self.admission))
        if self.hard_deadline is not None:
            object.__setattr__(self, 'hard_deadline', dict(self.hard_deadline))

    def validate_admission(self) -> None:
        """Recheck caller metadata and executable pins at each admission boundary."""
        validate_allocation(self.hard_deadline)
        if self.output_digest_limit is not None and (type(self.output_digest_limit) is not int
                or not 0 < self.output_digest_limit <= 16 * 1024 * 1024):
            raise ValueError('Native JSON result digest limit must be a positive integer of at most 16 MiB')
        for value in (self.deadline, self.idle_deadline, self.queue_work_seconds):
            if value is not None and (type(value) not in (int, float)
                    or not math.isfinite(value) or not 0 < value <= 21600):
                raise ValueError('Native deadlines must be finite, positive and at most six hours')
        if self.deadline is None:
            raise ValueError('Native owner requires an independent deadline')
        if type(self.capacity_wait_seconds) not in (float, int) \
                or not math.isfinite(self.capacity_wait_seconds) or not 0 <= self.capacity_wait_seconds <= 600:
            raise ValueError('Native capacity wait must be between zero and 600 seconds')
        if not isinstance(self.admission, dict):
            raise ValueError('Native admission must be a metadata mapping')
        _validate_output(self.admission.get('output'))
        for name, path in (('sdkSha256', self.cli), ('sandboxSha256', self.sandbox)):
            expected = self.admission.get(name)
            if not isinstance(expected, str) or len(expected) != 64 \
                    or any(character not in '0123456789abcdef' for character in expected):
                raise ValueError(f'Native admission {name} must be a lowercase hexadecimal SHA-256 digest')
            try:
                actual = digest(path)
            except OSError as error:
                raise ValueError(f'Native admission {name} file is unreadable: {path}') from error
            if actual != expected:
                raise ValueError(f'Native admission {name} does not match the current file: {path}')


def _validate_output(value: object) -> None:
    """Require an explicit file destination without restricting shared output formats."""
    if not isinstance(value, str) or not value.strip() or '\x00' in value or value.endswith('/'):
        raise ValueError('Native admission output must be a nonblank absolute file path')
    output = Path(value)
    if not output.is_absolute():
        raise ValueError('Native admission output must be an absolute file path')
    try:
        if not output.parent.is_dir():
            raise ValueError('Native admission output requires an existing parent directory')
        if output.is_symlink() or (output.exists() and not output.is_file()):
            raise ValueError('Native admission output must be a regular file destination, not a directory or symlink')
    except OSError as error:
        raise ValueError('Native admission output path cannot be inspected') from error


def policy_for_baseline(settings: NativeRunConfig, baseline: ResourceSnapshot) -> ResourcePolicy:
    """Derive new capacity budgets or preserve a caller's explicit legacy allowance."""
    if settings.policy is None:
        return capacity_policy(baseline)
    if settings.compressor_admission == 'fixed':
        return settings.policy
    fraction = min(.4, max(.25, (baseline.compressor_bytes + 1024 ** 3) / baseline.physical_bytes))
    return replace(settings.policy, maximum_compressor_fraction=fraction)


def authored_source_hashes(values: dict[str, str]) -> dict[str, str]:
    """Exclude the existing inventory's exact runtime records, never arbitrary hidden JSON."""
    from studio.native_preflight_inputs import runtime_record
    return {name: sha for name, sha in values.items() if not runtime_record(name, True)}


def source_hashes(project: Path) -> dict[str, str]:
    """Bind authored files; the package manifest binds all source/media bytes."""
    from studio.native_preflight_inputs import runtime_record
    return {path.name: digest(path) for path in sorted(project.iterdir())
            if path.is_file() and path.suffix in {'.html', '.js', '.css', '.json'}
            and not runtime_record(path.name, True)}


def local_environment() -> tuple[dict[str, str], dict[str, str]]:
    """Reuse tool resolution with a closed, secret-free child environment."""
    tools = resolve_tools()
    environment = {
        'PATH': ':'.join([str(Path(tools['node']).parent), str(Path(tools['ffmpeg']).parent), '/usr/bin', '/bin']),
        'TMPDIR': '/private/tmp', 'LC_ALL': 'C',
        'HYPERFRAMES_BROWSER_PATH': tools['browser'],
        'HYPERFRAMES_FFMPEG_PATH': tools['ffmpeg'],
        'HYPERFRAMES_FFPROBE_PATH': tools['ffprobe'],
        'PRODUCER_LOW_MEMORY_MODE': 'true', 'PRODUCER_FRAME_DATA_URI_CACHE_LIMIT': '32',
        'PRODUCER_FRAME_DATA_URI_CACHE_BYTES_MB': '64',
        'PRODUCER_EXPERIMENTAL_FAST_CAPTURE': 'false',
        'HYPERFRAMES_EXTRACT_CACHE_MAX_MB': '65536',
        'SNIPER_NATIVE_FRAME_TRANSPORT': 'url-v1',
        'HYPERFRAMES_NO_UPDATE_CHECK': '1', 'HYPERFRAMES_NO_AUTO_INSTALL': '1',
        'HYPERFRAMES_NO_TELEMETRY': '1', 'DO_NOT_TRACK': '1',
    }
    # Keep the explicit installed interpreter across the closed environment.
    # TypeScript's pythonInterpreter validates this root before launching it.
    venv_root = os.environ.get('SNIPER_PYTHON_VENV_ROOT')
    if venv_root is not None:
        environment['SNIPER_PYTHON_VENV_ROOT'] = venv_root
    return tools, environment


def owner_file_pins() -> dict[str, str]:
    """Bind shared supervision code even when a capture adapter omits its pins."""
    studio = Path(__file__).resolve().parent
    files = [studio / name for name in (
        'native_run.py', 'native_owned_processes.py', 'native_measurement_retry.py',
        'native_run_config.py', 'native_run_lifecycle.py', 'native_runtime.py', 'native_workload.py',
        'native_run_admission.py', 'native_queue_accounting.py', 'native_run_disk.py', 'native_export.py',
        'native_run_lease.py',
        'native_digest_memo.py')]  # X132 mi4: every owner digest runs through the memo
    files += list(studio.parent.glob('native_render_*.py'))
    files += list(studio.parent.glob('native_work_*.py'))
    files += list(studio.glob('native_budget_*.py'))
    files += list((studio / 'production').glob('*.py'))
    files += [studio.parent / name for name in (
        'native_work_lease.py', 'headless/durable_files.py', 'cut_preview_io.py')]
    return {str(file): digest(file) for file in files}



def validate_allocation(grant: dict | None) -> None:
    """Require the existing clock allocation shape before entering resource admission."""
    if grant is None:
        return
    keys = {'boot', 'continuousDeadline', 'epochDeadline', 'grantedSeconds', 'cleanupReserveSeconds'}
    if type(grant) is not dict or set(grant) - {'capacityCredit'} != keys or not isinstance(grant['boot'], str) or not grant['boot']:
        raise ValueError('Malformed inherited production deadline')
    if 'capacityCredit' in grant:
        from studio.production.queue_authority import validate_reference
        validate_reference(grant['capacityCredit'])
    values = [grant[key] for key in keys - {'boot'}]
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in values) \
            or grant['grantedSeconds'] <= 0 or not 0 <= grant['cleanupReserveSeconds'] < grant['grantedSeconds']:
        raise ValueError('Invalid inherited production deadline numbers')


def launch_environment(environment: dict[str, str]) -> dict[str, str]:
    """The closed child environment plus only the allowlisted timing lineage of the launch.

    Nothing else from the supervisor's own environment is copied, so an inherited
    credential or arbitrary variable never reaches the child. Lineage already present in
    the closed mapping is replaced, so the child links to the span open at launch (the
    owner's span) and an absent parent or task stays absent. Telemetry only: the child
    never uses these values for admission, ownership or any other decision.
    """
    closed = {name: value for name, value in environment.items() if name not in LINEAGE_VARIABLES}
    return {**closed, **lineage_environment()}

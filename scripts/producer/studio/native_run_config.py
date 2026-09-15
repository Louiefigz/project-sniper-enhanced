"""Explicit native render settings; no historical paths or inherited credentials."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

from graphics.render_tools import resolve_tools
from native_render_resources import ResourcePolicy, ResourceSnapshot
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
    policy: ResourcePolicy = field(default_factory=lambda: ResourcePolicy(
        maximum_owned_gib=4, maximum_process_gib=3, maximum_swap_growth_gib=1))
    deadline: float = 600
    additional_pins: dict[str, str] = field(default_factory=dict)
    success_status: str = 'rendered-awaiting-output-qc'
    unused_ram_advisory: bool = False
    compressor_admission: Literal['fixed', 'short-headroom'] = 'fixed'

    def __post_init__(self) -> None:
        """Reject invalid metadata before any owner can acquire or launch heavy work."""
        if self.compressor_admission not in {'fixed', 'short-headroom'}:
            raise ValueError('Unknown native compressor admission policy')
        self.validate_admission()
        object.__setattr__(self, 'admission', dict(self.admission))

    def validate_admission(self) -> None:
        """Recheck caller metadata and executable pins at each admission boundary."""
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
    """Derive the existing capped Short allowance from the owner's one fresh baseline."""
    if settings.compressor_admission == 'fixed':
        return settings.policy
    fraction = min(.4, max(.25, (baseline.compressor_bytes + 1024 ** 3) / baseline.physical_bytes))
    return replace(settings.policy, maximum_compressor_fraction=fraction)


def source_hashes(project: Path) -> dict[str, str]:
    """Bind authored files; the package manifest binds all source/media bytes."""
    return {path.name: digest(path) for path in sorted(project.iterdir())
            if path.is_file() and path.suffix in {'.html', '.js', '.css', '.json'}}


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
    return tools, environment

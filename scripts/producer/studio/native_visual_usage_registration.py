"""Automatically register checked native visual allocations without reading media."""
from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

from cut_preview_io import MAX_JSON, bound_json, file_hash, real_directory
from studio.native_runtime import REPO, digest

REGISTRATION_FILE = 'visual-usage-registration.json'
FINAL_STATUSES = {'native-short-checked-for-review', 'native-long-checked-for-review'}
TYPESCRIPT_IMPLEMENTATION_FILES = (
    'scripts/producer/visual-plan-usage.ts',
    'schemas/producer/visual-source-policy-v1.json',
    'src/app/api/producer/auto-edit/cut-preview-receipt.ts',
    'src/app/api/producer/auto-edit/stream.ts',
    'src/lib/server/native-visual-usage-receipt.ts',
    'src/lib/server/native-visual-usage-registration.ts',
    'src/lib/server/visual-plan-related-use.ts',
    'src/lib/server/visual-plan-binding.ts',
    'src/lib/server/auto-edit-hash.ts',
    'src/lib/server/atomic-file.ts',
    'src/lib/server/auto-edit-authority-snapshot.ts',
    'src/lib/server/auto-edit-authority.ts',
    'src/lib/server/auto-edit-doctrine.ts',
    'src/lib/server/auto-edit-pipeline-assets.ts',
    'src/lib/server/auto-edit-pipeline-authority.ts',
    'src/lib/server/auto-edit-pipeline-snapshot.ts',
    'src/app/api/producer/auto-edit/initial-authoring-capture.ts',
    'src/app/api/_lib/spawn-python.ts',
    'src/lib/producer/auto-edit-delivery-policy.ts',
    'src/lib/producer/contracts/validation.ts',
    'src/lib/producer/intent-presets.ts',
    'src/lib/producer/short-direction.ts',
    'src/lib/producer/visual-source-policy.ts',
    'src/lib/producer/visual-storytelling.ts',
)
PRODUCER_ROOT = REPO / 'scripts/producer'
PYTHON_ENTRY_FILES = (
    Path(__file__).resolve(),
    PRODUCER_ROOT / 'planner/visual_plan_cli.py',
)


class VisualUsageRegistrationError(RuntimeError):
    """A checked delivery could not enter bounded cross-project usage memory."""


def _json_hash(file: Path) -> str:
    """Hash one small authority without admitting a media-sized read."""
    return file_hash(file, MAX_JSON)


def _module_sources(module: str) -> list[Path]:
    """Resolve one static import plus executable package initializers."""
    parts = module.split('.')
    rows: set[Path] = set()
    for root in (REPO, PRODUCER_ROOT):
        for depth in range(1, len(parts)):
            package = root.joinpath(*parts[:depth], '__init__.py')
            if package.is_file():
                rows.add(package.resolve())
        module_file = root.joinpath(*parts).with_suffix('.py')
        package_file = root.joinpath(*parts, '__init__.py')
        for file in (module_file, package_file):
            if file.is_file():
                rows.add(file.resolve())
    return sorted(rows)


def _imported_modules(file: Path) -> set[str]:
    """Return static modules, including `from package import module` targets."""
    modules: set[str] = set()
    for node in ast.walk(ast.parse(file.read_text(encoding='utf-8'))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f'{node.module}.{alias.name}' for alias in node.names
                           if alias.name != '*')
    return modules


def _python_implementation_files() -> list[Path]:
    """Resolve the deterministic local Python import closure at pin/check time."""
    pending, seen = list(PYTHON_ENTRY_FILES), set()
    while pending:
        file = pending.pop().resolve()
        if file in seen:
            continue
        seen.add(file)
        for module in _imported_modules(file):
            pending.extend(candidate for candidate in _module_sources(module)
                           if candidate not in seen)
    return sorted(seen)


def usage_implementation_files() -> list[Path]:
    """Return the focused registration closure pinned by each export."""
    typescript = [REPO / name for name in TYPESCRIPT_IMPLEMENTATION_FILES]
    return [*typescript, *_python_implementation_files()]


def _exact_request(request: dict) -> dict:
    root = Path(request['output'])
    real_directory(root)
    stored = bound_json(root / 'export-request.json')
    if stored != request:
        raise VisualUsageRegistrationError('Native export request changed before usage registration')
    return stored


def _plan(request: dict) -> tuple[dict, str] | None:
    project = Path(request['project'])
    real_directory(project)
    mode = 'long' if request.get('adapter') == 'native-long' else 'short'
    file = project / ('LONG-PROJECT.json' if mode == 'long' else 'SHORT-PROJECT.json')
    expected = request.get('pins', {}).get(str(file))
    if not isinstance(expected, str):
        raise VisualUsageRegistrationError('Native project plan is absent from export pins')
    value = bound_json(file, expected)
    return (value, mode) if value.get('visualPlan') else None


def _producer_dir(request: dict, plan: dict, mode: str) -> Path:
    reference = plan.get('requestPacket')
    if not isinstance(reference, dict):
        raise VisualUsageRegistrationError('Current native project lacks its request packet')
    packet = Path(reference.get('path', ''))
    expected = reference.get('sha256')
    if not packet.is_absolute() or not isinstance(expected, str):
        raise VisualUsageRegistrationError('Native request packet binding is malformed')
    lane, name = ('native-longform', 'LONG-REQUEST.json') if mode == 'long' \
        else ('native-shorts', 'SHORT-REQUEST.json')
    if packet.name != name or packet.parent.parent.name != 'requests' \
            or packet.parent.parent.parent.name != lane:
        raise VisualUsageRegistrationError('Native request packet is outside its producer lane')
    producer = packet.parent.parent.parent.parent
    real_directory(producer)
    if request['pins'].get(str(packet)) != expected:
        raise VisualUsageRegistrationError('Native request packet is absent from export pins')
    packet_value = bound_json(packet, expected)
    if mode == 'long' and packet_value.get('producerDir') != str(producer):
        raise VisualUsageRegistrationError('Native Long packet producer directory changed')
    return producer


def _check_implementation(request: dict) -> None:
    pins = request.get('pins')
    if not isinstance(pins, dict):
        raise VisualUsageRegistrationError('Native export implementation pins are missing')
    node = request.get('tools', {}).get('node')
    if not isinstance(node, str) or pins.get(node) != digest(Path(node)):
        raise VisualUsageRegistrationError('Pinned native Node runtime changed')
    for file in usage_implementation_files():
        if pins.get(str(file)) != digest(file):
            raise VisualUsageRegistrationError(f'Usage registration implementation changed: {file}')


def _invoke(request: dict, producer: Path, environment: dict[str, str]) -> dict:
    command = [request['tools']['node'], '--import', 'tsx',
        str(REPO / 'scripts/producer/visual-plan-usage.ts'), 'register',
        str(producer), request['project'], request['output']]
    result = subprocess.run(command, cwd=REPO, env=environment, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, check=False)
    if len(result.stdout) + len(result.stderr) > MAX_JSON:
        raise VisualUsageRegistrationError('Usage registration diagnostics exceeded their bound')
    if result.returncode:
        detail = result.stderr.decode('utf-8', errors='replace')[-2048:]
        raise VisualUsageRegistrationError(f'Usage registration command failed: {detail}')
    try:
        value = json.loads(result.stdout.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VisualUsageRegistrationError('Usage registration returned invalid JSON') from error
    if not isinstance(value, dict):
        raise VisualUsageRegistrationError('Usage registration result must be an object')
    return value


def _validated_result(request: dict, producer: Path, result: dict) -> dict:
    registration = result.get('registration')
    receipt_path = result.get('receipt')
    if result.get('status') != 'native-visual-usage-registered' \
            or result.get('humanApprovalClaim') is not False \
            or not isinstance(registration, dict) or not isinstance(receipt_path, str):
        raise VisualUsageRegistrationError('Usage registration result is incomplete')
    root = Path(request['output'])
    file = root / REGISTRATION_FILE
    if registration.get('path') != str(file) or registration.get('sha256') != _json_hash(file):
        raise VisualUsageRegistrationError('Usage registration sidecar identity is invalid')
    sidecar = bound_json(file, registration['sha256'])
    receipt = sidecar.get('receipt')
    delivery = sidecar.get('delivery')
    receipt_file = Path(receipt_path)
    usage_dir = producer / '.sniper-visual-usage'
    if receipt_file.parent != usage_dir or receipt_file.suffix != '.json':
        raise VisualUsageRegistrationError('Usage receipt is outside bounded project memory')
    real_directory(usage_dir)
    project = result.get('project')
    expected = (sidecar.get('status') == result['status']
        and sidecar.get('humanApprovalClaim') is False
        and sidecar.get('producerDir') == str(producer)
        and sidecar.get('projectDir') == request['project']
        and sidecar.get('exportDir') == request['output']
        and isinstance(receipt, dict) and receipt.get('path') == receipt_path
        and receipt.get('digest') == result.get('digest')
        and receipt.get('sha256') == _json_hash(receipt_file)
        and isinstance(project, dict) and sidecar.get('projectId') == project.get('projectId')
        and isinstance(delivery, dict)
        and delivery.get('path') == str(root / 'delivery.json')
        and delivery.get('sha256') == _json_hash(root / 'delivery.json'))
    if not expected:
        raise VisualUsageRegistrationError('Usage registration sidecar differs from checked delivery')
    return result


def _register_completed_visual_usage(
    request: dict,
    environment: dict[str, str],
) -> dict | None:
    """Register a current visual plan after final QC; legacy projects are unchanged."""
    exact = _exact_request(request)
    planned = _plan(exact)
    if planned is None:
        return None
    plan, mode = planned
    delivery = bound_json(Path(exact['output']) / 'delivery.json')
    if delivery.get('status') not in FINAL_STATUSES:
        raise VisualUsageRegistrationError('Usage registration requires final checked delivery')
    producer = _producer_dir(exact, plan, mode)
    _check_implementation(exact)
    return _validated_result(exact, producer, _invoke(exact, producer, environment))


def register_completed_visual_usage(
    request: dict,
    environment: dict[str, str],
) -> dict | None:
    """Expose one specific failure type to the native completion boundary."""
    try:
        return _register_completed_visual_usage(request, environment)
    except VisualUsageRegistrationError:
        raise
    except Exception as error:
        raise VisualUsageRegistrationError(str(error)) from error

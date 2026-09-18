"""Python-AST persistence primitives with bounded pathlib value tracking."""
from __future__ import annotations

import ast
import re

WRITE_MODE = re.compile(r"[wax+]")
OS_MUTATORS = {
    "link", "makedirs", "mkdir", "open", "remove", "removedirs", "rename",
    "replace", "rmdir", "symlink", "truncate", "unlink",
}
SHUTIL_MUTATORS = {
    "copy", "copy2", "copyfile", "copyfileobj", "copytree", "move",
}
TEMP_MUTATORS = {
    "NamedTemporaryFile", "SpooledTemporaryFile", "mkdtemp", "mkstemp",
}
PATH_MUTATORS = {
    "hardlink_to", "mkdir", "open", "rename", "replace", "rmdir",
    "symlink_to", "touch", "unlink", "write_bytes", "write_text",
}
PROCESS_CALLS = {
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "subprocess.Popen",
    "subprocess.run",
}
SUPPORTED_MODULES = {
    "os", "shutil", "tempfile", "json", "pathlib", "subprocess",
}


def _call_name(call: ast.Call) -> str:
    target = call.func
    if isinstance(target, ast.Name):
        return target.id
    parts: list[str] = []
    while isinstance(target, ast.Attribute):
        parts.append(target.attr)
        target = target.value
    if isinstance(target, ast.Name):
        parts.append(target.id)
    return ".".join(reversed(parts))


def _constant_mode(call: ast.Call) -> str | None:
    value: object | None = call.args[1] if len(call.args) > 1 else None
    for keyword in call.keywords:
        if keyword.arg == "mode":
            value = keyword.value
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    return None


def _os_open_writes(call: ast.Call) -> bool:
    if len(call.args) < 2:
        return True
    flags = ast.unparse(call.args[1])
    writers = ("O_WRONLY", "O_RDWR", "O_CREAT", "O_TRUNC", "O_APPEND")
    if any(token in flags for token in writers):
        return True
    return "O_RDONLY" not in flags


def _target_names(value: ast.AST) -> set[str]:
    if isinstance(value, ast.Name):
        return {value.id}
    if isinstance(value, (ast.Tuple, ast.List)):
        return set().union(*(_target_names(item) for item in value.elts))
    return set()


def _root_name(value: ast.AST) -> str | None:
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.Attribute):
        return _root_name(value.value)
    if isinstance(value, ast.Call):
        return _root_name(value.func)
    if isinstance(value, ast.Subscript):
        return _root_name(value.value)
    return None


class PythonPersistenceModel:
    """Resolve imported filesystem APIs and statically evident Path values."""

    def __init__(self, tree: ast.AST):
        self.modules: dict[str, str] = {}
        self.direct: dict[str, str] = {}
        self.path_constructors: set[str] = set()
        self.path_vars: set[str] = set()
        self._imports(tree)
        self._path_values(tree)

    def _module_aliases(self, aliases: list[ast.alias]) -> None:
        for alias in aliases:
            if alias.name in SUPPORTED_MODULES:
                self.modules[alias.asname or alias.name] = alias.name

    def _direct_aliases(self, node: ast.ImportFrom) -> None:
        if node.module not in SUPPORTED_MODULES:
            return
        for alias in node.names:
            local = alias.asname or alias.name
            if node.module == "pathlib" and alias.name == "Path":
                self.path_constructors.add(local)
            if node.module != "pathlib":
                self.direct[local] = f"{node.module}.{alias.name}"

    def _register_import(self, node: ast.AST) -> None:
        if isinstance(node, ast.Import):
            self._module_aliases(node.names)
            return
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            self._direct_aliases(node)

    def _imports(self, tree: ast.AST) -> None:
        for node in ast.walk(tree):
            self._register_import(node)

    def _path_expression(self, value: ast.AST) -> bool:
        if isinstance(value, ast.Name):
            return value.id in self.path_vars
        if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Div):
            return self._path_expression(value.left)
        if isinstance(value, ast.Attribute):
            return self._path_expression(value.value)
        if isinstance(value, ast.Call):
            name = _call_name(value)
            root = name.split(".", 1)[0]
            is_pathlib = self.modules.get(root) == "pathlib" \
                and name == f"{root}.Path"
            return root in self.path_constructors \
                or root in self.path_vars or is_pathlib
        return False

    def _annotated_paths(self, node: ast.AST) -> set[str]:
        if isinstance(node, ast.arg) and node.annotation is not None:
            annotation = ast.unparse(node.annotation)
            valid = annotation in self.path_constructors \
                or annotation.endswith(".Path")
            return {node.arg} if valid else set()
        if isinstance(node, ast.AnnAssign) and node.annotation is not None:
            annotation = ast.unparse(node.annotation)
            valid = annotation in self.path_constructors \
                or annotation.endswith(".Path")
            return _target_names(node.target) if valid else set()
        return set()

    def _assigned_paths(self, node: ast.AST) -> set[str]:
        if isinstance(node, ast.Assign) and self._path_expression(node.value):
            return set().union(*(
                _target_names(target) for target in node.targets))
        valid = (
            isinstance(node, ast.AnnAssign)
            and node.value is not None
            and self._path_expression(node.value)
        )
        return _target_names(node.target) if valid else set()

    def _propagate_paths(self, tree: ast.AST) -> bool:
        before = len(self.path_vars)
        for node in ast.walk(tree):
            self.path_vars.update(self._assigned_paths(node))
        return len(self.path_vars) != before

    def _path_values(self, tree: ast.AST) -> None:
        for node in ast.walk(tree):
            self.path_vars.update(self._annotated_paths(node))
        for _pass in range(4):
            if not self._propagate_paths(tree):
                break

    def _canonical(self, call: ast.Call) -> str | None:
        name = _call_name(call)
        if name == "open":
            return name
        if name in self.direct:
            return self.direct[name]
        root, _, remainder = name.partition(".")
        module = self.modules.get(root)
        return f"{module}.{remainder}" if module and remainder else None

    def _canonical_mutator(
        self,
        canonical: str,
        call: ast.Call,
    ) -> str | None:
        if canonical == "open":
            mode = _constant_mode(call)
            return canonical if mode and WRITE_MODE.search(mode) else None
        module, _, leaf = canonical.rpartition(".")
        if module == "os" and leaf in OS_MUTATORS:
            if leaf == "open" and not _os_open_writes(call):
                return None
            return canonical
        if module == "shutil" and leaf in SHUTIL_MUTATORS:
            return canonical
        if module == "tempfile" and leaf in TEMP_MUTATORS:
            return canonical
        return canonical if canonical == "json.dump" else None

    def mutator(self, call: ast.Call) -> str | None:
        name = _call_name(call)
        canonical = self._canonical(call)
        if canonical is not None:
            return self._canonical_mutator(canonical, call)
        if not isinstance(call.func, ast.Attribute):
            return None
        leaf = call.func.attr
        root = _root_name(call.func.value)
        if (leaf not in PATH_MUTATORS
                or root not in self.path_vars | self.path_constructors):
            return None
        if leaf == "open":
            mode = _constant_mode(call)
            return name if mode and WRITE_MODE.search(mode) else None
        return name


def _persistence_row(
    node: ast.AST,
    model: PythonPersistenceModel,
) -> tuple[str, int] | None:
    if not isinstance(node, ast.Call):
        return None
    callee = model.mutator(node)
    return (callee, node.lineno) if callee else None


def python_persistence_rows(
    path: str,
    text: str,
) -> list[tuple[str, int]]:
    """Return canonical mutator name and line for one parsed Python source."""
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError as exc:
        raise RuntimeError(f"persistence audit cannot parse Python: {path}") from exc
    model = PythonPersistenceModel(tree)
    rows = []
    for node in ast.walk(tree):
        row = _persistence_row(node, model)
        if row is not None:
            rows.append(row)
    return rows


def python_process_rows(
    path: str,
    text: str,
) -> list[tuple[str, int]]:
    """Return direct child-process boundaries from one parsed Python source."""
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError as exc:
        raise RuntimeError(
            f"side-effect audit cannot parse Python: {path}") from exc
    model = PythonPersistenceModel(tree)
    rows = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        canonical = model._canonical(node)
        if canonical in PROCESS_CALLS \
                or (canonical is not None and canonical.startswith("os.spawn")) \
                or canonical in {"os.popen", "os.system"}:
            rows.append((str(canonical), node.lineno))
    return rows

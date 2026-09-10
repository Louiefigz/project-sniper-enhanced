#!/usr/bin/env python3
"""Dependency-free validator for Project Sniper's closed producer schemas."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA_DIR = Path(__file__).resolve().parents[3] / "schemas" / "producer"
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")


class SchemaValidationError(ValueError):
    """A document violates its selected producer schema."""


def _load_schema(name: str) -> dict[str, Any]:
    if "/" in name or "\\" in name or not name.endswith(".schema.json"):
        raise SchemaValidationError(f"invalid schema name {name!r}")
    path = SCHEMA_DIR / name
    if not path.is_file():
        raise SchemaValidationError(f"unknown schema {name!r}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SchemaValidationError(f"schema {name!r} is not an object")
    return value


def _pointer(root: dict[str, Any], fragment: str) -> dict[str, Any]:
    value: Any = root
    for raw in fragment.removeprefix("#/").split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or key not in value:
            raise SchemaValidationError(f"unresolved schema pointer {fragment}")
        value = value[key]
    if not isinstance(value, dict):
        raise SchemaValidationError(f"schema pointer {fragment} is not an object")
    return value


def _resolve(ref: str, root: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if ref.startswith("#/"):
        return _pointer(root, ref), root
    if "#" in ref:
        name, fragment = ref.split("#", 1)
        external = _load_schema(name)
        target = _pointer(external, f"#/{fragment.removeprefix('/')}")
        return target, external
    external = _load_schema(ref)
    return external, external


def _fail(path: str, message: str) -> None:
    raise SchemaValidationError(f"{path}: {message}")


def _json_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return (isinstance(value, (int, float))
                and not isinstance(value, bool) and math.isfinite(value))
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    raise SchemaValidationError(f"unsupported schema type {expected!r}")


def _try_validate(schema: dict[str, Any], value: Any,
                  root: dict[str, Any], path: str) -> bool:
    try:
        _validate(schema, value, root, path)
        return True
    except SchemaValidationError:
        return False


def _compositions(schema: dict[str, Any], value: Any,
                  root: dict[str, Any], path: str) -> None:
    if "allOf" in schema:
        for item in schema["allOf"]:
            _validate(item, value, root, path)
    if "oneOf" in schema:
        count = sum(_try_validate(item, value, root, path)
                    for item in schema["oneOf"])
        if count != 1:
            _fail(path, f"must match exactly one oneOf branch; matched {count}")
    if "not" in schema and _try_validate(schema["not"], value, root, path):
        _fail(path, "matches a forbidden schema")
    if "if" in schema:
        branch = "then" if _try_validate(schema["if"], value, root, path) else "else"
        if branch in schema:
            _validate(schema[branch], value, root, path)


def _object(schema: dict[str, Any], value: dict[str, Any],
            root: dict[str, Any], path: str) -> None:
    required = schema.get("required", [])
    missing = [key for key in required if key not in value]
    if missing:
        _fail(path, f"missing required fields {missing}")
    properties = schema.get("properties", {})
    additional = schema.get("additionalProperties", True)
    for key, item in value.items():
        if key in properties:
            _validate(properties[key], item, root, f"{path}.{key}")
            continue
        if additional is False:
            _fail(path, f"unsupported field {key!r}")
        if isinstance(additional, dict):
            _validate(additional, item, root, f"{path}.{key}")
    names = schema.get("propertyNames")
    if isinstance(names, dict):
        for key in value:
            _validate(names, key, root, f"{path} property name")
    if len(value) < schema.get("minProperties", 0):
        _fail(path, "has too few properties")
    if "maxProperties" in schema and len(value) > schema["maxProperties"]:
        _fail(path, "has too many properties")


def _array(schema: dict[str, Any], value: list[Any],
           root: dict[str, Any], path: str) -> None:
    if len(value) < schema.get("minItems", 0):
        _fail(path, "has too few items")
    if "maxItems" in schema and len(value) > schema["maxItems"]:
        _fail(path, "has too many items")
    if schema.get("uniqueItems"):
        keys = [json.dumps(item, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False) for item in value]
        if len(set(keys)) != len(keys):
            _fail(path, "items are not unique")
    items = schema.get("items")
    if isinstance(items, dict):
        for index, item in enumerate(value):
            _validate(items, item, root, f"{path}[{index}]")


def _string(schema: dict[str, Any], value: str, path: str) -> None:
    if len(value) < schema.get("minLength", 0):
        _fail(path, "is shorter than minLength")
    if "maxLength" in schema and len(value) > schema["maxLength"]:
        _fail(path, "is longer than maxLength")
    if "pattern" in schema and re.search(schema["pattern"], value) is None:
        _fail(path, "does not match pattern")
    if schema.get("format") == "uuid" and UUID_RE.fullmatch(value) is None:
        _fail(path, "is not a UUID")
    if schema.get("format") == "date-time":
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            _fail(path, "is not an ISO date-time")
    if schema.get("format") == "date":
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            _fail(path, "is not an ISO date")


def _validate(schema: dict[str, Any], value: Any,
              root: dict[str, Any], path: str) -> None:
    if "$ref" in schema:
        target, target_root = _resolve(schema["$ref"], root)
        _validate(target, value, target_root, path)
        return
    _compositions(schema, value, root, path)
    if "const" in schema and value != schema["const"]:
        _fail(path, f"must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        _fail(path, f"is not in enum {schema['enum']!r}")
    expected = schema.get("type")
    if expected is not None:
        options = [expected] if isinstance(expected, str) else expected
        if not any(_json_type(value, option) for option in options):
            _fail(path, f"must have type {options!r}")
    if isinstance(value, dict):
        _object(schema, value, root, path)
        return
    if isinstance(value, list):
        _array(schema, value, root, path)
        return
    if isinstance(value, str):
        _string(schema, value, path)
        return
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            _fail(path, f"is less than minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            _fail(path, f"is greater than maximum {schema['maximum']}")


def validate_document(schema_name: str, document: Any) -> Any:
    """Validate and return a document against one repository schema."""
    schema = _load_schema(schema_name)
    _validate(schema, document, schema, "$")
    return document


def schema_manifest(names: list[str]) -> dict[str, Any]:
    """Return exact schema-byte identities for cross-language checks."""
    rows = []
    for name in sorted(names):
        path = SCHEMA_DIR / name
        data = path.read_bytes()
        rows.append({"schema": name, "sha256": hashlib.sha256(data).hexdigest()})
    return {"schemaVersion": 1, "schemas": rows}


def _batch_row(index: int, row: object) -> dict[str, Any]:
    try:
        if not isinstance(row, dict):
            raise SchemaValidationError("case must be an object")
        validate_document(row["schema"], row["document"])
        return {"index": index, "valid": True}
    except (KeyError, SchemaValidationError) as exc:
        return {"index": index, "valid": False, "error": str(exc)}


def _batch(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise SchemaValidationError("batch payload must be an array")
    results = []
    for index, row in enumerate(payload):
        results.append(_batch_row(index, row))
    return results


def _command_result(
    args: argparse.Namespace, payload: Any, parser: argparse.ArgumentParser,
) -> Any:
    if args.manifest is not None:
        return schema_manifest(args.manifest)
    if args.batch:
        return _batch(payload)
    if args.schema:
        return validate_document(args.schema, payload)
    parser.error("--schema, --batch, or --manifest is required")


def main() -> int:
    """Validate one document, a batch, or emit a selected schema manifest."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema")
    parser.add_argument("--batch", action="store_true")
    parser.add_argument("--manifest", nargs="*")
    args = parser.parse_args()
    payload = json.load(sys.stdin) if args.manifest is None else None
    result = _command_result(args, payload, parser)
    json.dump(result, sys.stdout, sort_keys=True, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, json.JSONDecodeError, SchemaValidationError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from error

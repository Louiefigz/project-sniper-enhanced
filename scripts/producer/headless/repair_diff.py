"""Exact JSON-pointer diff used to prove mechanical repair scope."""

from __future__ import annotations


def _pointer_token(value: object) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def _dict_diff(first: dict, second: dict, path: str) -> list[str]:
    changed = []
    for key in sorted(set(first) | set(second)):
        child = f"{path}/{_pointer_token(key)}"
        if key not in first or key not in second:
            changed.append(child)
            continue
        changed.extend(_diff(first[key], second[key], child))
    return changed


def _list_diff(first: list, second: list, path: str) -> list[str]:
    if len(first) != len(second):
        return [path or "/"]
    changed = []
    for index, pair in enumerate(zip(first, second)):
        changed.extend(_diff(pair[0], pair[1], f"{path}/{index}"))
    return changed


def _diff(first: object, second: object, path: str = "") -> list[str]:
    if type(first) is not type(second):
        return [path or "/"]
    if type(first) is dict:
        return _dict_diff(first, second, path)
    if type(first) is list:
        return _list_diff(first, second, path)
    return [] if first == second else [path or "/"]


def changed_pointers(first: object, second: object) -> tuple[str, ...]:
    """Return canonical changed JSON pointers in deterministic order."""
    return tuple(_diff(first, second))

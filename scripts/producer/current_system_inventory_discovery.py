"""Bounded hidden-authority literal discovery for the P0 inventory."""
from __future__ import annotations

import re


def _strings(value: object, label: str) -> tuple[str, ...]:
    if (type(value) is not list or not value
            or any(type(item) is not str or not item for item in value)
            or len(set(value)) != len(value)):
        raise RuntimeError(f"{label} must be unique nonempty strings")
    return tuple(value)


def _string_mapping(
    value: object,
    label: str,
    allow_empty: bool = False,
) -> dict[str, str]:
    if type(value) is not dict or (not allow_empty and not value):
        qualifier = "" if allow_empty else "nonempty "
        raise RuntimeError(f"{label} must be a {qualifier}object")
    result: dict[str, str] = {}
    for key, item in value.items():
        if (type(key) is not str or not key
                or type(item) is not str or not item):
            raise RuntimeError(f"{label} must map nonempty strings")
        result[key] = item
    return result


def _hidden_literals(
    sources: dict[str, str],
    prefixes: tuple[str, ...],
) -> set[str]:
    alternatives = "|".join(
        re.escape(prefix) + r"[A-Za-z0-9_.${}-]*" for prefix in prefixes)
    pattern = re.compile(
        rf"""(?P<quote>["'`])(?P<token>(?:{alternatives}))(?P=quote)""")
    return {
        match.group("token")
        for text in sources.values()
        for match in pattern.finditer(text)
    }


def verify_authority_discovery(
    value: object,
    sources: dict[str, str],
    artifact_tokens: dict[str, set[str]],
) -> tuple[int, int]:
    """Require every bounded hidden literal to have exactly one disposition."""
    if type(value) is not dict or set(value) != {
            "literalPrefixes", "artifactBindings", "backlog",
            "pathBoundaryEvidence", "persistenceDispositionEvidence"}:
        raise RuntimeError("authorityDiscovery is malformed")
    prefixes = _strings(
        value["literalPrefixes"], "authorityDiscovery.literalPrefixes")
    bindings = _string_mapping(
        value["artifactBindings"], "authorityDiscovery.artifactBindings")
    backlog = _string_mapping(
        value["backlog"], "authorityDiscovery.backlog", allow_empty=True)
    evidence = value["pathBoundaryEvidence"]
    if type(evidence) is not str or not evidence:
        raise RuntimeError("authorityDiscovery.pathBoundaryEvidence is malformed")
    persistence = value["persistenceDispositionEvidence"]
    if type(persistence) is not str or not persistence:
        raise RuntimeError(
            "authorityDiscovery.persistenceDispositionEvidence is malformed")
    if set(bindings).intersection(backlog):
        raise RuntimeError("authority discovery token has two dispositions")
    unknown_ids = sorted(set(bindings.values()) - set(artifact_tokens))
    if unknown_ids:
        raise RuntimeError(
            f"authority discovery names absent artifacts: {unknown_ids}")
    unbound = sorted(
        token for token, artifact_id in bindings.items()
        if token not in {
            item.strip("\"'`") for item in artifact_tokens[artifact_id]
        })
    if unbound:
        raise RuntimeError(
            f"authority discovery bypasses artifact tokens: {unbound}")
    actual = _hidden_literals(sources, prefixes)
    declared = set(bindings).union(backlog)
    if actual != declared:
        missing = sorted(actual - declared)
        stale = sorted(declared - actual)
        raise RuntimeError(
            "authority literal discovery drift; "
            f"undisposed={missing}, absent={stale}")
    return len(actual), len(backlog)

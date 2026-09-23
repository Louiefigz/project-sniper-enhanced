"""Bind every authored native design to catalog, reference or bounded custom evidence.

This checks identities, coverage and freshness, not visual similarity. The
existing independent plan/pixel reviews still judge the recorded rationale.
"""
from __future__ import annotations

import hashlib
import copy
import json
import re
import sys
from pathlib import Path

from cross_runtime_canonical_json import canonical_compact_json
from graphics.visual_source_policy import ROOT, policy


def require(condition: object, message: str) -> None:
    """Raise a source-specific admission error."""
    if not condition:
        raise ValueError(f"Visual source policy: {message}")


def subject_hash(subject: object) -> str:
    """Use the same canonical subject digest as the TypeScript caller."""
    return hashlib.sha256(canonical_compact_json(subject).encode()).hexdigest()


def carry_scene_source_choice(before: dict, after: dict, change: str) -> None:
    """Preserve source selection through an exact scoped edit, never quality approval.

    The treatment handler already checks the operation's target and old value.
    Recheck current source evidence and forbid changing executable composition,
    selected source, element membership or design decisions. Plan/review hashes
    still change; rendering must pass its independent readiness admission.
    """
    if before['composition']['type'] == 'catalog':
        return
    expected = copy.deepcopy(before)
    expected['version'] += 1
    require(change in {'variable', 'timing'}, 'unsupported scoped source update')
    if change == 'timing':
        expected['timing'] = after['timing']
    else:
        expected['composition']['variables'] = after['composition']['variables']
        require(len(expected['elements']) == len(after['elements']), 'scene membership changed')
        for old, new in zip(expected['elements'], after['elements']):
            old['values'] = new['values']
    require(subject_hash(expected) == subject_hash(after),
            'scoped edit changed source selection or scene structure')
    targets = [row['elementId'] for row in before['elements']]
    subject = lambda value: {key: item for key, item in value.items() if key != 'visualSources'}
    validate_visual_sources(before.get('visualSources'), subject(before), targets)
    after['visualSources']['subjectSha256'] = subject_hash(subject(after))
    validate_visual_sources(after['visualSources'], subject(after), targets)


def pin(value: object, read_bytes: bool = True) -> bytes:
    """Read exact local evidence; never accept a label in place of source bytes."""
    require(isinstance(value, dict), "source evidence must be a file pin")
    file = Path(str(value.get("path", "")))
    require(file.is_absolute() and file.is_file() and not file.is_symlink()
            and file.resolve() == file, "source evidence needs a canonical regular file")
    require(not read_bytes or file.stat().st_size <= 16 * 1024 * 1024, "source evidence is too large")
    data = file.read_bytes() if read_bytes else b""
    digest = hashlib.sha256(data).hexdigest() if read_bytes else streamed_hash(file)
    require(digest == value.get("sha256"), "source evidence changed")
    require(value["sha256"] not in policy()["retired"].values(), "retired templates cannot be relabeled")
    return data


def streamed_hash(file: Path) -> str:
    """Hash a reference video without loading the whole recording into memory."""
    before = file.stat()
    digest = hashlib.sha256()
    with file.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    after = file.stat()
    require(all(getattr(before, field) == getattr(after, field) for field in
                ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")),
            "reference changed during source verification")
    return digest.hexdigest()


def text(value: object, field: str) -> None:
    """Require a bounded human explanation."""
    require(isinstance(value, str) and 12 <= len(value.strip()) <= 8000,
            f"{field} needs a specific explanation")


def catalog_item(value: object) -> dict:
    """Authenticate the item's identity and exact upstream source snapshot."""
    require(isinstance(value, dict), "catalog selection must be an object")
    index = json.loads((ROOT / "vendor/hyperframes-catalog/catalog-index.json").read_text())
    item = next((row for row in index if row["name"] == value.get("id")), None)
    require(item is not None, "catalog ID is not in the upstream snapshot")
    folder = "compositions/components" if item["type"] == "component" else "compositions"
    file = ROOT / "vendor/hyperframes-catalog" / folder / f"{item['name']}.html"
    require(file.is_file() and not file.is_symlink(), "catalog source is missing; it is not a custom-work gap")
    require(hashlib.sha256(file.read_bytes()).hexdigest() == value.get("sourceSha256"),
            "catalog source/version does not match the inspected snapshot")
    return item


def _catalog(decision: dict) -> None:
    """Catalog decisions name inspected sources and explain their actual use."""
    items = decision.get("catalog")
    require(isinstance(items, list) and 1 <= len(items) <= 64, "catalog sources are required")
    ids = [catalog_item(item)["name"] for item in items]
    require(len(ids) == len(set(ids)), "duplicate catalog sources")
    text(decision.get("configuration"), "catalog configuration/composition")


def _reference(decision: dict, request: dict) -> None:
    """Only a reference selected for this request can authorize its design."""
    reference = decision.get("reference")
    pin(reference, read_bytes=False)
    require(reference in request.get("selectedReferences", []),
            "reference is not explicitly selected in the current request")
    text(decision.get("adaptation"), "reference adaptation")


def _custom(decision: dict) -> None:
    """Require an inspected upstream gap, not missing setup or a search miss."""
    require(decision.get("gapType") in {"missing-capability", "quality-failure"},
            "custom requires a capability or quality gap")
    for field in ("query", "gap", "scope"):
        text(decision.get(field), f"custom {field}")
    inspected = decision.get("inspected")
    require(isinstance(inspected, list) and 1 <= len(inspected) <= 32,
            "custom needs inspected closest catalog alternatives")
    for alternative in inspected:
        catalog_item(alternative)
        text(alternative.get("limitation"), "inspected alternative limitation")



def native_catalog_bindings(subject: object) -> dict[str, dict]:
    """Bind actual mounted native files; a catalog label cannot license a built-in design."""
    if not isinstance(subject, dict) or "canvas" not in subject:
        return {}
    bindings = {}
    for row in subject.get("catalogFiles", []):
        require(isinstance(row, dict) and re.fullmatch(r"compositions/[a-z0-9][a-z0-9-]*\.html", str(row.get("file", ""))),
                "invalid native catalog file binding")
        pin(row)
        catalog_item({"id": row.get("catalogId"), "sourceSha256": row.get("sourceSha256")})
        markup = (subject.get("extension") or {}).get("markup", "")
        require(f'data-composition-src="{row["file"]}"' in markup, "catalog file must be mounted in the authored scene")
        require(row["file"] not in bindings, "duplicate native catalog file")
        bindings[row["file"]] = row
    return bindings


def native_catalog_decision(row: dict, subject: object, bindings: dict) -> None:
    """Catalog-mounted files need corresponding catalog decisions, not relabeled custom."""
    if not isinstance(subject, dict) or "canvas" not in subject:
        return
    selected = {item.get("id") for item in row.get("catalog", [])}
    for target in row["targets"]:
        if target in bindings:
            require(row["route"] == "catalog" and bindings[target]["catalogId"] in selected,
                    "native catalog decision must name the actual mounted source")
        elif row["route"] == "catalog":
            require(target == "scene-extension" and bindings and selected <= {item["catalogId"] for item in bindings.values()},
                    "built-in native designs need reference/custom evidence; mount an actual catalog component instead")


def validate_visual_sources(receipt: object, subject: object, targets: list[str]) -> dict:
    """Require exact authored-subject coverage and current source evidence."""
    require(isinstance(receipt, dict), "visualSources evidence is required; migrate this project")
    require(receipt.get("schemaVersion") == 1 and receipt.get("policyVersion") == policy()["policyVersion"],
            "project predates the current source policy")
    require(receipt.get("subjectSha256") == subject_hash(subject), "authored design changed; renew source decisions")
    request = json.loads(pin(receipt.get("request")))
    require(isinstance(request, dict), "request evidence must be a JSON object")
    rows = receipt.get("decisions")
    require(isinstance(rows, list) and len(rows) <= 512, "invalid source decisions")
    bindings = native_catalog_bindings(subject)
    seen: list[str] = []
    for row in rows:
        require(isinstance(row, dict), "invalid source decision")
        members = row.get("targets")
        require(isinstance(members, list) and members and all(isinstance(x, str) for x in members),
                "each source decision needs actual authored targets")
        seen.extend(members)
        text(row.get("reason"), "selection reason")
        route = row.get("route")
        native_catalog_decision(row, subject, bindings)
        require(route in {"catalog", "reference", "custom"}, "unknown source route")
        if route == "catalog":
            _catalog(row)
        elif route == "reference":
            _reference(row, request)
        else:
            _custom(row)
    require(len(seen) == len(set(seen)) and set(seen) == set(targets),
            "source decisions omit, duplicate or invent authored targets")
    return {"policyVersion": policy()["policyVersion"], "subjectSha256": receipt["subjectSha256"],
            "targets": sorted(targets), "sourceEvidenceChecked": True, "visualQualityApproved": False}


def main() -> None:
    """Shared offline JSON bridge for TypeScript; no tools or rendering invoked."""
    value = json.load(sys.stdin)
    print(json.dumps(validate_visual_sources(value.get("receipt"), value["subject"], value["targets"])))


if __name__ == "__main__":
    main()

"""Explicit AssetRecord, bundle-member, and sandbox admission for scenes."""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone

from graphics.asset_governance import AssetUse, admit_asset
from graphics.scene_contract import SceneContractError, canonical_json
from graphics.scene_package_contract import ResolvedScenePackage
from headless.external_media_probe import admit_external_media

_PROBE_MIMES = {
    "image/png", "image/jpeg", "image/webp", "image/svg+xml",
    "audio/wav", "audio/mpeg", "video/mp4", "video/quicktime",
    "font/ttf", "font/otf",
}


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise SceneContractError(
            "publication evaluatedAt must be an RFC3339 timestamp")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise SceneContractError("publication evaluatedAt is invalid") from exc
    if parsed.tzinfo is None:
        raise SceneContractError("publication evaluatedAt needs a timezone")
    return parsed.astimezone(timezone.utc)


def _snapshot_store(path: str | None, required: bool) -> str | None:
    if not required and path is None:
        return None
    if not isinstance(path, str) or not os.path.isabs(path) \
            or os.path.normpath(path) != path or os.path.realpath(path) != path \
            or os.path.islink(path) or not os.path.isdir(path):
        raise SceneContractError(
            "asset media snapshot store must be a canonical real directory")
    return path


def _dependencies(resolved: ResolvedScenePackage) -> dict[str, dict]:
    rows = [row for row in resolved.scene["dependencies"]
            if row["kind"] == "asset"]
    indexed = {row["id"]: row for row in rows}
    if len(indexed) != len(rows):
        raise SceneContractError("scene asset dependency IDs are not unique")
    return indexed


def _package_assets(resolved: ResolvedScenePackage) -> dict[str, dict]:
    rows = resolved.package["assets"]
    indexed = {}
    paths: set[str] = set()
    members: set[str] = set()
    for row in rows:
        ident = row["record"]["assetId"]
        path, member = row["blobPath"], row["bundleMember"]
        if ident in indexed or path in paths \
                or member is not None and member in members:
            raise SceneContractError(
                "scene package asset IDs, blobs, and members must be unique")
        indexed[ident] = row
        paths.add(path)
        if member is not None:
            members.add(member)
    return indexed


def _project_member(resolved: ResolvedScenePackage,
                    package_asset: dict, dependency: dict) -> str:
    member = package_asset["bundleMember"]
    if not isinstance(member, str):
        raise SceneContractError(
            "project asset requires an explicit bundle member")
    files = resolved.source_contract["bundleFiles"]
    matches = [row for row in files
               if row["path"] == member
               and row["sha256"] == dependency["sha256"]
               and row["sizeBytes"] == package_asset["record"]["sizeBytes"]]
    if len(matches) != 1:
        raise SceneContractError(
            "asset does not bind exactly one named bundle member")
    return member


def _catalog_member(resolved: ResolvedScenePackage,
                    package_asset: dict, dependency: dict) -> None:
    if package_asset["bundleMember"] is not None:
        raise SceneContractError(
            "catalog assets cannot claim project bundle members")
    bindings = resolved.source_contract["assetBindings"]
    source = package_asset["record"]["provenance"]["source"]
    matches = [row for row in bindings
               if all(row.get(key) == dependency[key]
                      for key in ("kind", "id", "sha256"))
               and row.get("sourcePath") == source
               and row.get("sizeBytes")
               == package_asset["record"]["sizeBytes"]]
    if len(matches) != 1:
        raise SceneContractError(
            "catalog asset does not bind exactly one resolved selector")
    return None


def _member(resolved: ResolvedScenePackage,
            package_asset: dict, dependency: dict) -> str | None:
    if resolved.scene["composition"]["type"] == "project":
        return _project_member(resolved, package_asset, dependency)
    return _catalog_member(resolved, package_asset, dependency)


def _probe(package_asset: dict, store: str) -> tuple[dict, str]:
    record = package_asset["record"]
    if record["mime"] not in _PROBE_MIMES:
        raise SceneContractError(
            f"asset MIME {record['mime']} has no released sandbox probe")
    receipt = admit_external_media(package_asset["blobPath"], store)
    snapshot = receipt.get("snapshot")
    decoded = receipt.get("decoded")
    if not isinstance(snapshot, dict) or not isinstance(decoded, dict) \
            or snapshot.get("sha256") != record["sha256"] \
            or snapshot.get("sizeBytes") != record["sizeBytes"] \
            or decoded.get("decoded") is not True:
        raise SceneContractError(
            "external-media sandbox receipt does not bind AssetRecordV1")
    digest = hashlib.sha256(canonical_json(receipt)).hexdigest()
    return receipt, digest


def _admit_one(resolved: ResolvedScenePackage, package_asset: dict,
               dependency: dict, store: str) -> dict:
    record = package_asset["record"]
    if record["sha256"] != dependency["sha256"]:
        raise SceneContractError(
            "AssetRecordV1 hash differs from scene dependency")
    context = resolved.package["publicationContext"]
    admission = admit_asset(
        record, package_asset["blobPath"],
        AssetUse(context["use"], context["platform"],
                 _timestamp(context["evaluatedAt"])))
    if admission.sha256 != dependency["sha256"] \
            or admission.size_bytes != record["sizeBytes"]:
        raise SceneContractError(
            "asset byte admission differs from scene dependency")
    member = _member(resolved, package_asset, dependency)
    probe, probe_hash = _probe(package_asset, store)
    value = {
        "assetId": admission.asset_id, "sha256": admission.sha256,
        "sizeBytes": admission.size_bytes, "mime": admission.mime,
        "bundleMember": member, "attribution": admission.attribution,
        "recordHash": hashlib.sha256(canonical_json(record)).hexdigest(),
        "externalMediaReceiptHash": probe_hash,
        "externalMediaReceipt": probe,
    }
    return {**value, "admissionHash": hashlib.sha256(
        canonical_json(value)).hexdigest()}


def admit_package_assets(resolved: ResolvedScenePackage,
                         snapshot_store: str | None) -> list[dict]:
    """Admit every and only scene asset through rights, bytes, and sandbox."""
    dependencies = _dependencies(resolved)
    assets = _package_assets(resolved)
    if set(assets) != set(dependencies):
        raise SceneContractError(
            "scene package AssetRecords differ from scene dependencies")
    store = _snapshot_store(snapshot_store, bool(assets))
    if store is None:
        return []
    return [_admit_one(
        resolved, assets[ident], dependencies[ident], store)
        for ident in sorted(assets)]

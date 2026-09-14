/** Origin adapters preserve caller declarations and cannot manufacture publication approval. */
import assert from "node:assert/strict";
import { existsSync, writeFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { parseAssetRecordV1 } from "@/lib/producer/contracts/asset-record";
import { writeNativeAssetOrigin } from "../native-short-asset-origin";
import { readNativeAssetOrigin } from "../native-short-asset-use-origins";
import { withAssetUse } from "./_native-short-asset-use-fixture";

test("origin writer preserves unresolved rights and freezes the exact supplied source", () => withAssetUse(f => {
  const { origin: prior, ...asset } = f.input.assets[0];
  assert.ok(prior);
  const receipt = f.receipts.get(asset.file)!;
  const file = path.join(f.directory, "new-origin.json");
  const bound = writeNativeAssetOrigin({ asset, record: receipt.record, acquisition: receipt.acquisition }, file);
  assert.deepEqual(readNativeAssetOrigin(bound).record, receipt.record);
  assert.equal(readNativeAssetOrigin(bound).record.publicationDisposition, "needs-review");
  assert.throws(() => writeNativeAssetOrigin({ asset: bound, record: receipt.record,
    acquisition: receipt.acquisition }, path.join(f.directory, "rebind.json")), /exact unbound/);
  assert.equal(existsSync(path.join(f.directory, "rebind.json")), false);
  writeFileSync(file, "changed evidence");
  assert.throws(() => readNativeAssetOrigin(bound), /changed/);
}));

test("changed media cannot receive a matching-looking origin receipt", () => withAssetUse(f => {
  const asset = { ...f.input.assets[0], origin: undefined }, receipt = f.receipts.get(asset.file)!;
  writeFileSync(asset.path, "different frozen bytes");
  const destination = path.join(f.directory, "not-written.json");
  assert.throws(() => writeNativeAssetOrigin({ asset, record: receipt.record,
    acquisition: receipt.acquisition }, destination), /exact unbound/);
  assert.equal(existsSync(destination), false);
}));

test("large source opt-in preserves the default shared asset limit", () => withAssetUse(f => {
  const record = { ...f.receipts.get(f.input.assets[0].file)!.record, sizeBytes: 10 * 1024 ** 3 };
  assert.throws(() => parseAssetRecordV1(record), /sizeBytes/);
  assert.equal(parseAssetRecordV1(record, { maxSizeBytes: 64 * 1024 ** 3 }).sizeBytes, record.sizeBytes);
  for (const maxSizeBytes of [Infinity, 0, 1.5, 65 * 1024 ** 3]) {
    assert.throws(() => parseAssetRecordV1(record, { maxSizeBytes }), /bounded/);
  }
}));

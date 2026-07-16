import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { lookupProducerManifest } from "../producer-manifest";

function manifest(filePath: string, id: string): void {
  writeFileSync(filePath, JSON.stringify({ sources: [{ id }] }));
}

const root = mkdtempSync(path.join(os.tmpdir(), "sniper-manifest-authority-"));
const producer = path.join(root, "producer");
const source = path.join(root, "source");
mkdirSync(producer);
mkdirSync(source);

try {
  const first = path.join(source, "alpha.json");
  const second = path.join(source, "beta.json");
  manifest(first, "alpha");
  manifest(second, "beta");
  const ambiguous = lookupProducerManifest(producer);
  assert.equal(ambiguous.path, null);
  assert.match(ambiguous.error ?? "", /ambiguous asset manifests/);

  writeFileSync(path.join(producer, "base.fingerprint.json"), JSON.stringify({
    manifestPath: second,
  }));
  const recorded = lookupProducerManifest(producer);
  assert.equal(recorded.path, second);
  assert.equal(recorded.transcriptsDir, source);

  writeFileSync(path.join(producer, "base.fingerprint.json"), JSON.stringify({
    manifestPath: path.join(source, "gone.json"),
  }));
  const gone = lookupProducerManifest(producer);
  assert.equal(gone.path, null);
  assert.match(gone.error ?? "", /manifest is gone/);

  writeFileSync(path.join(producer, "base.fingerprint.json"), "{");
  const malformed = lookupProducerManifest(producer);
  assert.equal(malformed.path, null);
  assert.match(malformed.error ?? "", /not valid JSON/);
} finally {
  rmSync(root, { recursive: true, force: true });
}

console.log("producer-manifest.test.ts: all assertions passed");

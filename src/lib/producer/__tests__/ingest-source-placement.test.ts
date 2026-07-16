import assert from "node:assert/strict";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  truncateSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  prepareIngestTarget,
  type IngestTarget,
  type SourceCopyProgress,
} from "../../../app/api/producer/ingest/target";

function freshTarget(root: string, inputPath: string): IngestTarget {
  return {
    ingestInput: inputPath,
    manifestDir: path.join(root, "source"),
    outDir: path.join(root, "producer"),
    projectRoot: root,
    fresh: true,
  };
}

async function run(): Promise<void> {
  const sandbox = mkdtempSync(path.join(os.tmpdir(), "sniper-ingest-placement-"));
  try {
  const input = path.join(sandbox, "input.mp4");
  writeFileSync(input, Buffer.alloc(512 * 1024, 7));
  const copiedRoot = path.join(sandbox, "copied-project");
  mkdirSync(copiedRoot);
  const progress: SourceCopyProgress[] = [];
  const copied = await prepareIngestTarget(
    freshTarget(copiedRoot, input),
    (event) => progress.push(event),
    new AbortController().signal,
  );
  assert.equal(copied.placement, "copied");
  assert.deepEqual(
    readFileSync(path.join(copiedRoot, "source", "input.mp4")),
    readFileSync(input),
  );
  assert.equal(progress.at(-1)?.copiedBytes, progress.at(-1)?.totalBytes);
  assert.equal(existsSync(path.join(copiedRoot, "project.json")), true);

  const cancelledRoot = path.join(sandbox, "cancelled-project");
  const largeInput = path.join(sandbox, "cancel-me.mp4");
  mkdirSync(cancelledRoot);
  writeFileSync(largeInput, Buffer.alloc(8 * 1024 * 1024, 3));
  const aborter = new AbortController();
  await assert.rejects(
    prepareIngestTarget(freshTarget(cancelledRoot, largeInput), () => aborter.abort(), aborter.signal),
    (error: unknown) => (error as Error).name === "AbortError",
  );
  assert.equal(existsSync(path.join(cancelledRoot, "source")), false);
  assert.equal(existsSync(path.join(cancelledRoot, "project.json")), false);
  assert.deepEqual(readdirSync(cancelledRoot), []);

  const referencedRoot = path.join(sandbox, "referenced-project");
  const sparseInput = path.join(sandbox, "over-limit.mp4");
  mkdirSync(referencedRoot);
  writeFileSync(sparseInput, "");
  truncateSync(sparseInput, 2 * 1024 * 1024 * 1024 + 1);
  const referenced = await prepareIngestTarget(
    freshTarget(referencedRoot, sparseInput),
    () => assert.fail("referenced sources must not report copied bytes"),
    new AbortController().signal,
  );
  assert.equal(referenced.placement, "referenced");
  assert.equal(JSON.parse(readFileSync(path.join(referencedRoot, "project.json"), "utf8")).sourceMode, "referenced");
  assert.equal(existsSync(path.join(referencedRoot, "source", "over-limit.mp4")), false);
  } finally {
    rmSync(sandbox, { recursive: true, force: true });
  }
}

run()
  .then(() => console.log("ingest-source-placement.test.ts: all assertions passed"))
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });

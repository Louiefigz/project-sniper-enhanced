import assert from "node:assert/strict";
import { runCutRepairExecution } from
  "@/app/api/producer/ai-edit/cut-repair-execute-runner";
import {
  producerAuthorityPaths,
  writeAuthorityObjectSync,
} from "@/lib/server/producer-authority-files";
import {
  bootstrapRevisionFixture,
  cleanRevisionFixture,
} from "@/lib/server/__tests__/_producer-revision-fixture";

const directive = {
  schemaVersion: 1 as const,
  operation: "cut.restoreSpeech" as const,
  mode: "execute" as const,
  packageHash: "a".repeat(64),
  target: {
    phrase: "the exact clipped phrase",
    occurrence: 1,
  },
};

async function run(): Promise<void> {
  const fixture = bootstrapRevisionFixture();
  try {
    await assert.rejects(
      runCutRepairExecution(
        fixture.producer, "/missing/manifest.json", directive),
      /ENOENT/,
    );
    const paths = producerAuthorityPaths(fixture.producer);
    const incomplete = writeAuthorityObjectSync(
      paths.objects.cutRepairs,
      { schemaVersion: 1, kind: "cut-repair-execution-package" },
    );
    await assert.rejects(
      runCutRepairExecution(
        fixture.producer,
        "/missing/manifest.json",
        { ...directive, packageHash: incomplete.hash },
      ),
      /execution package is not closed/,
    );
  } finally {
    cleanRevisionFixture(fixture.root);
  }
}

run()
  .then(() => console.log("p2-cut-repair-execute-admission tests passed"))
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });

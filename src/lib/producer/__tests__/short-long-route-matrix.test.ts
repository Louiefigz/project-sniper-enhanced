import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  parseShortLongRouteMatrixV1,
  renderShortLongRouteMatrixMarkdown,
} from "../contracts/short-long-route-matrix";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../..");
const contractPath = path.join(
  root,
  "docs/producer/command-driven-editing/contracts/short-long-route-matrix-v1.json",
);
const docPath = path.join(
  root,
  "docs/producer/command-driven-editing/12_SHORT_LONG_EXECUTABLE_MATRIX.md",
);
const raw = JSON.parse(fs.readFileSync(contractPath, "utf8")) as unknown;
const matrix = parseShortLongRouteMatrixV1(raw);

function routeFiles(directory: string): string[] {
  const result: string[] = [];
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const absolute = path.join(directory, entry.name);
    if (entry.isDirectory()) result.push(...routeFiles(absolute));
    else if (entry.isFile() && entry.name === "route.ts") {
      result.push(path.relative(root, absolute));
    }
  }
  return result.sort();
}

const registeredRoutes = matrix.routeGroups
  .flatMap((group) => group.routes)
  .sort();
assert.equal(
  new Set(registeredRoutes).size,
  registeredRoutes.length,
  "each production route must have exactly one short/long disposition",
);
assert.deepEqual(
  registeredRoutes,
  routeFiles(path.join(root, matrix.routeRoot)),
  "new or removed producer routes require an explicit short/long disposition",
);

for (const workflow of matrix.workflows) {
  for (const entrypoint of workflow.entrypoints) {
    assert.equal(
      fs.existsSync(path.join(root, entrypoint)),
      true,
      `${workflow.workflowId} entrypoint does not exist: ${entrypoint}`,
    );
  }
}
for (const [matrixId, evidencePaths] of Object.entries(matrix.evidence)) {
  for (const evidencePath of evidencePaths) {
    assert.equal(
      fs.existsSync(path.join(root, evidencePath)),
      true,
      `${matrixId} evidence does not exist: ${evidencePath}`,
    );
  }
}

assert.deepEqual(
  matrix.workflows
    .filter((workflow) =>
      workflow.short.status === "released"
      || workflow.longform.status === "released")
    .map((workflow) => workflow.workflowId),
  ["range-karaoke-captions", "project-custom-motion"],
);
assert.equal(
  matrix.workflows.find(
    (workflow) => workflow.workflowId === "continuous-subject-reframe",
  )?.short.status,
  "unsupported",
);
assert.equal(
  matrix.workflows.find(
    (workflow) => workflow.workflowId === "non-ripple-word-repair",
  )?.longform.status,
  "unqualified",
);
const wordRepair = matrix.workflows.find(
  (workflow) => workflow.workflowId === "non-ripple-word-repair",
);
assert.match(wordRepair?.short.behavior ?? "", /bounded P2 contract/);
assert.match(wordRepair?.longform.behavior ?? "", /normalized VFR/);
assert.ok(
  [...(wordRepair?.short.blockers ?? []), ...(wordRepair?.longform.blockers ?? [])]
    .every((blocker) => !blocker.includes("Independent aligner deployment")
      && !blocker.includes("phase-demo evidence")),
  "the generated matrix must distinguish passed bounded P2 exits from open product gates",
);

assert.equal(
  fs.readFileSync(docPath, "utf8"),
  renderShortLongRouteMatrixMarkdown(matrix),
  "generated short/long documentation drifted from executable matrix",
);

const missingBlocker = structuredClone(raw) as {
  workflows: Array<{ short: { status: string; blockers: string[] } }>;
};
missingBlocker.workflows[2].short.blockers = [];
assert.throws(
  () => parseShortLongRouteMatrixV1(missingBlocker),
  /must explain its blocking gates/,
);

console.log("short/long route matrix tests passed");

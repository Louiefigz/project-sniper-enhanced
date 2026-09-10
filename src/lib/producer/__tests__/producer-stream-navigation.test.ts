import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const source = (relative: string): string => readFileSync(path.join(process.cwd(), relative), "utf8");
const route = source("src/app/api/producer/ingest/route.ts");
const target = source("src/app/api/producer/ingest/target.ts");
const launch = source("src/components/producer/auto-edit-launch.tsx");
const page = source("src/app/(tools)/producer/page.tsx");

assert.doesNotMatch(target, /cpSync\(/, "source placement must not block the SSE response with cpSync");
assert.match(route, /source_copy_progress/);
assert.match(route, /prepareIngestTarget\(/);
assert.match(route, /cancel: stop/);
assert.match(route, /terminateProcessTree\(live\.proc\)/);
assert.match(route, /maxDuration = 1800/,
  "ingest route must outlive the bounded 1,200-second decode plus overhead");
assert.ok(
  route.indexOf("guardProjectMutation({") < route.indexOf("resolveIngestTarget("),
  "a writer lease must precede fresh project creation",
);

assert.match(launch, /new AbortController\(\)/);
assert.match(launch, /signal: controller\.signal/);
assert.match(launch, /activeRef\.current\?\.abort\(\)/);
assert.match(launch, /!controller\.signal\.aborted && mountedRef\.current/);
assert.match(page, /openRequestRef\.current\?\.abort\(\)/);
assert.match(page, /controller\.signal\.aborted \|\| openRequestRef\.current !== controller/);

console.log("producer-stream-navigation.test.ts: all assertions passed");

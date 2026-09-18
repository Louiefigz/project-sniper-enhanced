import path from "node:path";
import {
  runPalmierNativeEdit as runNativeImplementation,
  type NativeRunnerDependencies,
} from "../../../app/api/producer/ai-edit/palmier-native-runner";

function governedDependencies(
  dependencies: NativeRunnerDependencies,
): NativeRunnerDependencies {
  return {
    ...dependencies,
    capability: dependencies.capability ?? (() => null),
    captureAuthority: (input, _parent, hash) => {
      const captureId = `test-${hash.slice(0, 12)}`;
      const nativeInputPath = path.join(input.dir, `${captureId}-native-input.json`);
      return {
        schemaVersion: 1, requestHash: hash, captureId, nativeInputPath,
        ctx: {
          dir: input.dir, scope: "produced", planPath: nativeInputPath,
          manifestPath: path.join(input.dir, "asset_manifest.json"), transcriptsDir: input.dir,
          doctrine: {
            runId: captureId, doctrineHash: "d".repeat(64),
            snapshotPath: path.join(input.dir, "doctrine-lock.json"),
            files: {
              "SKILL.md": path.join(process.cwd(), ".claude/skills/producer/SKILL.md"),
              "FAILURE_LEDGER.md": path.join(process.cwd(), "scripts/producer/docs/findings/FAILURE_LEDGER.md"),
              "plan_lint.py": path.join(process.cwd(), "scripts/producer/plan_lint.py"),
            },
          },
          pipeline: {
            schemaVersion: 1, runId: captureId, digest: "e".repeat(64),
            snapshotRoot: process.cwd(), lockPath: path.join(input.dir, "pipeline-lock.json"), files: [],
          },
        },
      };
    },
    finalizeAuthority: (capture, input, parent) => ({
      schemaVersion: 1,
      requestHash: capture.requestHash,
      captureId: capture.captureId,
      nativeInput: {
        path: capture.nativeInputPath, hash: "f".repeat(64),
        requestTextHash: capture.requestHash, lanes: [...input.scope.lanes],
        parent: { projectId: parent.projectId, timelineId: parent.timelineId,
          fingerprint: parent.fingerprint },
        nativePlanHash: "a".repeat(64),
      },
      ctx: capture.ctx,
    }),
    bindAuthority: () => {},
  };
}

export function runTestPalmierNativeEdit(
  input: Parameters<typeof runNativeImplementation>[0],
  dependencies: NativeRunnerDependencies,
  options: Parameters<typeof runNativeImplementation>[2] = {},
) {
  return runNativeImplementation(
    input,
    governedDependencies(dependencies),
    options,
  );
}

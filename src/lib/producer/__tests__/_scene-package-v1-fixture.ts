import type { SceneSpecV1 } from "../contracts/scene-spec";

export const fixtureHash = (value: string): string => value.repeat(64);

export function fireSparklesScene(
  bundleHash = fixtureHash("b"),
): SceneSpecV1 {
  const variables = {
    leftTitle: "Blue card with deterministic fire",
    rightTitle: "Change only this card",
    leftColor: "#0B5FFF",
    seed: 424242,
    fireIntensity: 1,
    sparkleCount: 22,
  };
  return {
    schemaVersion: 1,
    sceneId: "scene-045",
    version: 1,
    timing: {
      startFrame: 1350,
      endFrameExclusive: 1530,
      fps: { numerator: "30", denominator: "1" },
      timelineMapHash: fixtureHash("a"),
    },
    canvas: { width: 1920, height: 1080 },
    renderMode: "overlay-alpha",
    composition: {
      type: "project",
      bundleId: "fire-sparkles-cards",
      bundleHash,
      entry: "compositions/full.html",
      variables,
    },
    elements: [
      {
        elementId: "left-blue-card",
        role: "information-card",
        exposedProperties: ["leftTitle", "leftColor"],
        values: {
          leftTitle: variables.leftTitle,
          leftColor: variables.leftColor,
        },
      },
      {
        elementId: "seeded-fire",
        role: "decorative-fire",
        exposedProperties: ["seed", "fireIntensity"],
        values: {
          seed: variables.seed,
          fireIntensity: variables.fireIntensity,
        },
      },
      {
        elementId: "right-copy",
        role: "information-card",
        exposedProperties: ["rightTitle"],
        values: { rightTitle: variables.rightTitle },
      },
      {
        elementId: "seeded-sparkles",
        role: "decorative-sparkles",
        exposedProperties: ["seed", "sparkleCount"],
        values: {
          seed: variables.seed,
          sparkleCount: variables.sparkleCount,
        },
      },
    ],
    renderUnits: [
      {
        unitId: "unit-left",
        elementIds: ["left-blue-card", "seeded-fire"],
        zIndex: 10,
        entry: "compositions/unit-left.html",
        compositeMode: "normal",
        palmierGranularity: "unit",
      },
      {
        unitId: "unit-right",
        elementIds: ["right-copy", "seeded-sparkles"],
        zIndex: 20,
        entry: "compositions/unit-right.html",
        compositeMode: "normal",
        palmierGranularity: "unit",
      },
    ],
    captionPolicy: "suppress-overlap",
    dependencies: [],
    provenance: {
      origin: "operator",
      requestId: "request-fire-sparkles",
    },
  };
}

export function treatmentEnvelope(action: unknown) {
  return {
    schemaVersion: 1,
    batchId: "40000000-0000-4000-8000-000000000001",
    requestId: "20000000-0000-4000-8000-000000000001",
    idempotencyKey: "30000000-0000-4000-8000-000000000001",
    stage: "treatment",
    atomic: true,
    preserveUnrelated: true,
    base: {
      projectRevisionHash: fixtureHash("a"),
      planContentHash: fixtureHash("b"),
      manifestHash: fixtureHash("c"),
      sourceSnapshotSetHash: fixtureHash("d"),
      timelineMapHash: fixtureHash("e"),
      canvasProfileHash: fixtureHash("f"),
      destinationProfileHashes: [fixtureHash("1")],
      pictureLockHash: fixtureHash("2"),
    },
    operations: [{
      schemaVersion: 1,
      operationId: "50000000-0000-4000-8000-000000000001",
      clauseId: "10000000-0000-4000-8000-000000000001",
      action,
    }],
  };
}

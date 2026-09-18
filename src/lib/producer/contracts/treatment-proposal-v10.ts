/** Supplied raster scene planning; exact v3 media decisions remain a separate required stage. */
import { exactKeys, objectValue } from "./validation";
import { parseNativeShortScene, parseTreatmentProposalV9, type NativeShortScene, type TreatmentProposalV9 } from "./treatment-proposal-v9";

export interface NativeSupportingScene extends Omit<NativeShortScene, "mechanism" | "view"> {
  mechanism: "supporting-asset";
  view: "presenter-supporting";
}
export type NativeShortSceneV10 = NativeShortScene | NativeSupportingScene;
export interface TreatmentProposalV10 extends Omit<TreatmentProposalV9, "schemaVersion" | "operations"> {
  schemaVersion: 10;
  operations: Array<{ type: "native-scene"; clauseIndex: number; beatIndex: number; scene: NativeShortSceneV10 }>;
}

/** Only the new mechanism can request a supplied image; reference IDs remain style context. */
export function parseNativeShortSceneV10(value: unknown): NativeShortSceneV10 {
  const row = objectValue(value, "V10 native scene"), supporting = row.mechanism === "supporting-asset";
  if (typeof row.mechanism !== "string" || typeof row.view !== "string") throw new Error("V10 scene requires scalar mechanism and view");
  if (supporting && row.view !== "presenter-supporting") throw new Error("Supporting asset requires its explicit presenter-supporting view");
  const scene = parseNativeShortScene(supporting ? { ...row, mechanism: "presenter-hold", view: "presenter" } : row);
  if (new Set(scene.requiredAssetIds).size !== scene.requiredAssetIds.length) throw new Error("Required supporting asset IDs must be unique within each scene");
  if (supporting && (!scene.requiredAssetIds.length || !scene.readingHoldFrames)) throw new Error("Supporting scene requires supplied IDs and an explicit reading hold");
  if (!supporting && scene.requiredAssetIds.length) throw new Error("Required supporting assets need an explicit supporting-asset mechanism");
  return supporting ? { ...scene, mechanism: "supporting-asset", view: "presenter-supporting" } : scene;
}

/** Reuse V9 clause/beat/identity parsing while retaining the actual V10 operations. */
export function parseTreatmentProposalV10(value: unknown): TreatmentProposalV10 {
  const row = objectValue(value, "V10 native proposal");
  if (row.schemaVersion !== 10 || row.colorPolicy !== "preserve") throw new Error("Native supplied-asset proposal requires V10 and preserved color");
  if (!Array.isArray(row.operations) || row.operations.length > 32) throw new Error("V10 operations exceed the bounded native scene count");
  const scenes = row.operations.map(value => {
    const operation = objectValue(value, "V10 native operation");
    exactKeys(operation, ["type", "clauseIndex", "beatIndex", "scene"], ["type", "clauseIndex", "beatIndex", "scene"], "V10 native operation");
    return parseNativeShortSceneV10(operation.scene);
  });
  const base = parseTreatmentProposalV9({ ...row, schemaVersion: 9, operations: row.operations.map((operation, index) => ({
    ...operation, scene: scenes[index].mechanism === "supporting-asset"
      ? { ...scenes[index], mechanism: "presenter-hold", view: "presenter" } : scenes[index],
  })) });
  return { ...base, schemaVersion: 10, operations: base.operations.map((operation, index) => ({ ...operation, scene: scenes[index] })) };
}

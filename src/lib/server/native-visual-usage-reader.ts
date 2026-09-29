import { createHash } from "node:crypto";
import { lstatSync, realpathSync } from "node:fs";
import path from "node:path";
import { readBoundedAuthoringFile } from
  "@/app/api/producer/auto-edit/initial-authoring-capture";
import { stableAuthorityHash } from "./auto-edit-authority-snapshot";
import { canonicalJson, canonicalJsonSha256 } from "./auto-edit-hash";
import type { NativeUsageReceipt } from "./native-visual-usage-receipt";
import { selectedVisualUses, type VisualUsageProject } from "./visual-plan-related-use";

const MAX_JSON_BYTES = 16 * 1024 * 1024;
const SHA256 = /^[a-f0-9]{64}$/u;
interface FilePin { path: string; sha256: string }

function object(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function jsonFile(file: string, label: string): {
  value: Record<string, unknown>; pin: FilePin;
} {
  if (realpathSync(file) !== file || lstatSync(file).isSymbolicLink()) {
    throw new Error(`${label} must be one canonical regular file`);
  }
  const bytes = readBoundedAuthoringFile(file, label, MAX_JSON_BYTES);
  return { value: object(JSON.parse(bytes.toString("utf8")), label),
    pin: { path: file, sha256: createHash("sha256").update(bytes).digest("hex") } };
}

function validReceipt(row: NativeUsageReceipt, producerDir: string, file: string): boolean {
  const { digest, ...core } = row;
  const milliseconds = Date.parse(row.machineCheckedAt);
  const currentName = Number.isSafeInteger(milliseconds) && milliseconds >= 0
    ? `${String(milliseconds).padStart(13, "0")}-${row.mode}-${digest}.json` : "";
  const filename = path.basename(file);
  return row.schemaVersion === 1 && row.kind === "native-visual-usage-receipt"
    && row.producerDir === producerDir && row.humanApprovalClaim === false
    && digest === canonicalJsonSha256(core) && SHA256.test(digest)
    && (filename === `${digest}.json` || filename === currentName)
    && row.machineCheckedAt === row.project?.approvedAt
    && Array.isArray(row.evidence) && row.evidence.length <= 16;
}

/** Revalidate one immutable receipt and every small JSON dependency; media is never read. */
export function readNativeVisualUsageReceipt(file: string, producerDir: string): VisualUsageProject {
  const row = jsonFile(file, "native visual usage receipt").value as unknown as NativeUsageReceipt;
  if (!validReceipt(row, producerDir, file)) {
    throw new Error("native visual usage receipt is malformed or belongs to another project");
  }
  for (const pin of row.evidence) {
    if (!pin.path.endsWith(".json")
        || jsonFile(pin.path, "native usage evidence").pin.sha256 !== pin.sha256) {
      throw new Error("native visual usage evidence changed");
    }
  }
  const visual = jsonFile(row.visualPlan.path, "native usage visual plan");
  const application = jsonFile(row.application.path, "native usage application");
  const applicationValue = row.mode === "long"
    ? object(application.value.visualPlanApplication, "native Long usage application")
    : application.value;
  const uses = selectedVisualUses(visual.value, row.project.planSha256);
  if (visual.pin.sha256 !== row.visualPlan.sha256 || !uses
      || application.pin.sha256 !== row.application.sha256
      || stableAuthorityHash(applicationValue) !== row.project.applicationSha256
      || canonicalJson(uses) !== canonicalJson(row.project.uses)
      || row.project.planSha256 !== stableAuthorityHash(visual.value)
      || object(visual.value.project, "native usage project").mode !== row.mode
      || object(visual.value.allocation, "native usage allocation").route !== row.route
      || !SHA256.test(row.project.applicationSha256)
      || !SHA256.test(row.project.packetSha256)) {
    throw new Error("native visual usage differs from its frozen allocation");
  }
  return row.project;
}

import { createHash } from "node:crypto";
import { existsSync, lstatSync, realpathSync } from "node:fs";
import path from "node:path";
import { readBoundedAuthoringFile } from
  "@/app/api/producer/auto-edit/initial-authoring-capture";
import { canonicalJson } from "./auto-edit-hash";
import { atomicCreateJsonSync } from "./atomic-file";

const MAX_JSON_BYTES = 16 * 1024 * 1024;

interface FilePin { path: string; sha256: string }

export interface NativeUsageRegistration {
  schemaVersion: 1;
  kind: "native-visual-usage-registration";
  status: "native-visual-usage-registered";
  humanApprovalClaim: false;
  producerDir: string;
  projectDir: string;
  exportDir: string;
  delivery: FilePin;
  receipt: FilePin & { digest: string };
  projectId: string;
}

interface RegistrationInput {
  producerDir: string;
  projectDir: string;
  exportDir: string;
  delivery: FilePin;
  receipt: string;
  digest: string;
  projectId: string;
}

function pinnedFile(file: string, label: string): FilePin {
  if (realpathSync(file) !== file || lstatSync(file).isSymbolicLink()) {
    throw new Error(`${label} must be one canonical regular file`);
  }
  const bytes = readBoundedAuthoringFile(file, label, MAX_JSON_BYTES);
  return { path: file, sha256: createHash("sha256").update(bytes).digest("hex") };
}

function existingRegistration(
  file: string,
  expected: NativeUsageRegistration,
): NativeUsageRegistration {
  const bytes = readBoundedAuthoringFile(file, "native usage registration", MAX_JSON_BYTES);
  const value = JSON.parse(bytes.toString("utf8")) as unknown;
  if (canonicalJson(value) !== canonicalJson(expected)) {
    throw new Error("native usage registration differs from this checked export");
  }
  return expected;
}

/** Bind the receipt identity to the checked export without changing delivery.json. */
export function recordNativeUsageRegistration(
  input: RegistrationInput,
): { path: string; sha256: string; value: NativeUsageRegistration } {
  const receipt = pinnedFile(input.receipt, "native visual usage receipt");
  const value: NativeUsageRegistration = {
    schemaVersion: 1,
    kind: "native-visual-usage-registration",
    status: "native-visual-usage-registered",
    humanApprovalClaim: false,
    producerDir: input.producerDir,
    projectDir: input.projectDir,
    exportDir: input.exportDir,
    delivery: input.delivery,
    receipt: { ...receipt, digest: input.digest },
    projectId: input.projectId,
  };
  const file = path.join(input.exportDir, "visual-usage-registration.json");
  if (existsSync(file)) existingRegistration(file, value);
  else atomicCreateJsonSync(file, value);
  return { ...pinnedFile(file, "native usage registration"), value };
}

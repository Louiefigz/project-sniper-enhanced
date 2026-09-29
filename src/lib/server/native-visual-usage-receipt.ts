import { createHash } from "node:crypto";
import { existsSync, lstatSync, mkdirSync, realpathSync } from "node:fs";
import path from "node:path";
import { readBoundedAuthoringFile } from
  "@/app/api/producer/auto-edit/initial-authoring-capture";
import { stableAuthorityHash } from "./auto-edit-authority-snapshot";
import { canonicalJson, canonicalJsonSha256 } from "./auto-edit-hash";
import { atomicCreateJsonSync } from "./atomic-file";
import { boundVisualPlanContent, type VisualPlanBinding } from "./visual-plan-binding";
import { selectedVisualUses, type RelatedUse, type VisualUsageProject } from
  "./visual-plan-related-use";
import { recordNativeUsageRegistration } from "./native-visual-usage-registration";
export const NATIVE_USAGE_DIRECTORY = ".sniper-visual-usage";
const MAX_JSON_BYTES = 16 * 1024 * 1024;
const SHA256 = /^[a-f0-9]{64}$/u;
interface FilePin { path: string; sha256: string }

function receiptName(value: NativeUsageReceipt): string {
  const milliseconds = Date.parse(value.machineCheckedAt);
  if (!Number.isSafeInteger(milliseconds) || milliseconds < 0) {
    throw new Error("native visual usage time cannot form a receipt identity");
  }
  return `${String(milliseconds).padStart(13, "0")}-${value.mode}-${value.digest}.json`;
}
export interface NativeUsageReceipt {
  schemaVersion: 1;
  kind: "native-visual-usage-receipt";
  producerDir: string;
  mode: "short" | "long";
  route: "native-short" | "native-long";
  machineCheckedAt: string;
  humanApprovalClaim: false;
  visualPlan: FilePin;
  application: FilePin;
  evidence: FilePin[];
  project: VisualUsageProject;
  digest: string;
}
function object(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}
function canonicalDirectory(raw: string, label: string): string {
  const resolved = path.resolve(raw);
  if (!path.isAbsolute(raw) || !existsSync(resolved) || lstatSync(resolved).isSymbolicLink()
      || !lstatSync(resolved).isDirectory() || realpathSync(resolved) !== resolved) {
    throw new Error(`${label} must be one canonical directory`);
  }
  return resolved;
}
function filePin(file: string, label: string): FilePin {
  const canonical = realpathSync(file);
  if (canonical !== file || lstatSync(file).isSymbolicLink()) {
    throw new Error(`${label} must be one canonical regular file`);
  }
  const bytes = readBoundedAuthoringFile(file, label, MAX_JSON_BYTES);
  return { path: file, sha256: createHash("sha256").update(bytes).digest("hex") };
}
function jsonFile(file: string, label: string): { value: Record<string, unknown>; pin: FilePin; text: string } {
  const pin = filePin(file, label);
  const bytes = readBoundedAuthoringFile(file, label, MAX_JSON_BYTES);
  return { value: object(JSON.parse(bytes.toString("utf8")), label), pin,
    text: bytes.toString("utf8") };
}
function exactPin(pins: Record<string, unknown>, pin: FilePin, label: string): void {
  if (pins[pin.path] !== pin.sha256) throw new Error(`${label} differs from the checked native export`);
}
function requestPacket(
  producerDir: string,
  plan: Record<string, unknown>,
  mode: "short" | "long",
): FilePin {
  const ref = object(plan.requestPacket, "native request packet binding");
  if (typeof ref.path !== "string" || typeof ref.sha256 !== "string") {
    throw new Error("native project lacks its prepared request packet");
  }
  const pin = filePin(ref.path, "native request packet");
  const lane = mode === "short" ? "native-shorts" : "native-longform";
  const expected = path.join(producerDir, lane, "requests") + path.sep;
  if (!pin.path.startsWith(expected) || pin.sha256 !== ref.sha256) {
    throw new Error("native request packet does not belong to this producer project");
  }
  return pin;
}
function applicationFile(
  projectDir: string,
  plan: Record<string, unknown>,
  mode: "short" | "long",
): { value: Record<string, unknown>; pin: FilePin } {
  const value = mode === "short"
    ? object(object(plan.strategy, "native Short strategy").visualPlanApplication,
      "native Short visual-plan application")
    : object(plan.visualPlanApplication, "native Long visual-plan application");
  if (mode === "long") {
    return { value, pin: filePin(path.join(projectDir, "LONG-PROJECT.json"), "native Long project") };
  }
  const sidecar = jsonFile(path.join(projectDir, "VISUAL-PLAN-APPLICATION.json"),
    "native Short visual-plan application");
  if (sidecar.text !== canonicalJson(value)) {
    throw new Error("native Short visual-plan application differs from its sidecar");
  }
  return { value, pin: sidecar.pin };
}
function assertApplication(
  visual: Record<string, unknown>,
  application: Record<string, unknown>,
  route: "native-short" | "native-long",
): void {
  const allocation = object(visual.allocation, "visual-plan allocation");
  const expected = Array.isArray(allocation.decisions) ? allocation.decisions.map((row) => object(row, "allocation decision")) : [];
  const actual = Array.isArray(application.decisions) ? application.decisions.map((row) => object(row, "application decision")) : [];
  if (application.schemaVersion !== 1 || application.route !== route
      || application.visualPlanSha256 !== stableAuthorityHash(visual)
      || expected.length !== actual.length || expected.some((row, index) =>
        row.opportunityId !== actual[index].opportunityId || row.candidateId !== actual[index].candidateId)) {
    throw new Error("native visual-plan application differs from its complete allocation");
  }
}
function nativeProject(
  producerDir: string,
  rawProjectDir: string,
): { mode: "short" | "long"; route: "native-short" | "native-long";
     plan: FilePin; visual: FilePin; application: FilePin; prebuild: FilePin;
     supporting: FilePin[];
     requestPacket: FilePin; uses: RelatedUse[]; planSha256: string; applicationSha256: string } {
  const projectDir = canonicalDirectory(rawProjectDir, "native project");
  const short = existsSync(path.join(projectDir, "SHORT-PROJECT.json"));
  const long = existsSync(path.join(projectDir, "LONG-PROJECT.json"));
  if (short === long) throw new Error("native project needs exactly one Short or Long plan");
  const mode = short ? "short" : "long", route = short ? "native-short" : "native-long";
  const planFile = path.join(projectDir, short ? "SHORT-PROJECT.json" : "LONG-PROJECT.json");
  const plan = jsonFile(planFile, "native project plan");
  const binding = object(plan.value.visualPlan, "native visual-plan binding") as unknown as VisualPlanBinding;
  const bound = boundVisualPlanContent(binding);
  const visual = object(bound.content, "native visual plan");
  const frozen = filePin(path.join(projectDir, "VISUAL-PLAN.json"), "frozen native visual plan");
  if (bound.byteHash !== frozen.sha256
      || visual.project === undefined || object(visual.project, "visual-plan project").mode !== mode
      || object(visual.allocation, "visual-plan allocation").route !== route) {
    throw new Error("native project visual plan differs from its allocated route");
  }
  const application = applicationFile(projectDir, plan.value, mode);
  assertApplication(visual, application.value, route);
  const planSha256 = stableAuthorityHash(visual), uses = selectedVisualUses(visual, planSha256);
  if (!uses) throw new Error("native visual plan has no valid allocated usage");
  const prebuild = jsonFile(path.join(projectDir, "PREBUILD-REVIEW.json"), "native prebuild review");
  const review = object(prebuild.value.review, "native prebuild verdict");
  if (prebuild.value.scope !== (short ? "native-short-full-plan" : "native-long-full-project")
      || review.verdict !== "pass" || !Array.isArray(review.materialIssues) || review.materialIssues.length) {
    throw new Error("native prebuild review is not a current passing full-plan record");
  }
  const supporting = short
    ? [shortManifest(projectDir, plan.value, [plan.pin, frozen, application.pin, prebuild.pin])]
    : [longPolicy(projectDir, plan.value)];
  return { mode, route, plan: plan.pin, visual: filePin(bound.path, "native visual plan source"),
    application: application.pin, prebuild: prebuild.pin, supporting,
    requestPacket: requestPacket(producerDir, plan.value, mode), uses, planSha256,
    applicationSha256: stableAuthorityHash(application.value) };
}
function longPolicy(projectDir: string, plan: Record<string, unknown>): FilePin {
  const policy = jsonFile(path.join(projectDir, "NATIVE-LONG-POLICY.json"), "native Long policy");
  if (policy.value.schemaVersion !== 1 || policy.value.requirement !== "required-for-new-native-long"
      || canonicalJson(policy.value.requestPacket) !== canonicalJson(plan.requestPacket)) {
    throw new Error("native Long policy differs from its prepared request authority");
  }
  return policy.pin;
}
function shortManifest(
  projectDir: string,
  plan: Record<string, unknown>,
  required: FilePin[],
): FilePin {
  const manifest = jsonFile(path.join(projectDir, "PROJECT-MANIFEST.json"), "native Short manifest");
  const rows = Array.isArray(manifest.value.files)
    ? manifest.value.files.map((row) => object(row, "native Short manifest file")) : [];
  const hashes = new Map(rows.map((row) => [path.join(projectDir, String(row.file)), row.sha256]));
  if (manifest.value.schemaVersion !== 1 || manifest.value.scope !== "native-short-review-project"
      || manifest.value.projectHash !== canonicalJsonSha256(plan)
      || manifest.value.humanApproved !== false
      || required.some((pin) => hashes.get(pin.path) !== pin.sha256)) {
    throw new Error("native Short manifest differs from its project and prebuild evidence");
  }
  return manifest.pin;
}
interface VerificationInput {
  exportDir: string;
  projectDir: string;
  expectedStatus: string;
  delivery: ReturnType<typeof jsonFile>;
  request: ReturnType<typeof jsonFile>;
  required: FilePin[];
}
function verificationEvidence(input: VerificationInput): FilePin[] {
  const stages = Array.isArray(input.delivery.value.stages)
    ? input.delivery.value.stages.map((row) => object(row, "native delivery stage")) : [];
  const rows = stages.filter((row) => row.phase === "verification");
  if (rows.length !== 1 || typeof rows[0].receipt !== "string") {
    throw new Error("native export lacks one final verification owner");
  }
  const owner = jsonFile(rows[0].receipt, "native verification owner");
  const checks = jsonFile(path.join(input.exportDir, "checks.json"), "native encoded checks");
  const pins = object(owner.value.additionalFilePinsBefore, "native verification owner pins");
  const cleanup = object(owner.value.cleanup, "native owner cleanup");
  if (owner.pin.path !== path.join(input.exportDir, "verification.render.json")
      || owner.pin.sha256 !== rows[0].sha256 || rows[0].status !== input.expectedStatus
      || owner.value.status !== input.expectedStatus || owner.value.exitCode !== 0
      || owner.value.project !== input.projectDir || owner.value.output !== checks.pin.path
      || owner.value.abortReason || cleanup.verified !== true
      || !Array.isArray(cleanup.survivors) || cleanup.survivors.length
      || checks.value.status !== "checks-passed-awaiting-owned-cleanup"
      || checks.value.fullAudioVideoDecodePassed !== true
      || checks.value.sha256 !== input.delivery.value.sha256
      || pins[input.request.pin.path] !== input.request.pin.sha256) {
    throw new Error("native final verification evidence is incomplete or changed");
  }
  for (const pin of input.required) exactPin(pins, pin, "native verification owner evidence");
  return [owner.pin, checks.pin];
}
function checkedEvidence(
  rawExportDir: string,
  projectDir: string,
  native: ReturnType<typeof nativeProject>,
): { checkedAt: string; packetSha256: string; pins: FilePin[];
     delivery: FilePin; exportDir: string } {
  const exportDir = canonicalDirectory(rawExportDir, "native checked export");
  const request = jsonFile(path.join(exportDir, "export-request.json"), "native export request");
  const delivery = jsonFile(path.join(exportDir, "delivery.json"), "native delivery evidence");
  const requestPins = object(request.value.pins, "native export pins");
  const expectedStatus = native.mode === "short"
    ? "native-short-checked-for-review" : "native-long-checked-for-review";
  const reviewFile = path.join(exportDir, "review.mp4");
  if (request.value.project !== projectDir || request.value.output !== exportDir
      || request.value.adapter !== (native.mode === "long" ? "native-long" : undefined)
      || delivery.value.status !== expectedStatus || delivery.value.fullAudioVideoDecodePassed !== true
      || delivery.value.humanApproved !== false || typeof delivery.value.completedAt !== "string"
      || !Number.isFinite(Date.parse(delivery.value.completedAt))
      || delivery.value.output !== reviewFile || typeof delivery.value.sha256 !== "string"
      || !SHA256.test(delivery.value.sha256) || !existsSync(reviewFile)
      || lstatSync(reviewFile).isSymbolicLink() || !lstatSync(reviewFile).isFile()) {
    throw new Error("native export lacks current machine-checked delivery evidence");
  }
  const required = [native.plan, native.visual, native.application, native.prebuild,
    native.requestPacket, ...native.supporting];
  for (const pin of required) {
    exactPin(requestPins, pin, "native project evidence");
  }
  const verified = verificationEvidence({ exportDir, projectDir, expectedStatus,
    delivery, request, required });
  return { checkedAt: delivery.value.completedAt, packetSha256: request.pin.sha256,
    pins: [...required, request.pin, delivery.pin, ...verified],
    delivery: delivery.pin, exportDir };
}
/** Register one immutable post-QC usage receipt without reading any media bytes. */
export function registerNativeVisualUsage(
  rawProducerDir: string,
  rawProjectDir: string,
  rawExportDir: string,
): { receipt: string; digest: string; project: VisualUsageProject;
     registration: { path: string; sha256: string } } {
  const producerDir = canonicalDirectory(rawProducerDir, "producer project");
  const projectDir = canonicalDirectory(rawProjectDir, "native project");
  const native = nativeProject(producerDir, projectDir);
  const checked = checkedEvidence(rawExportDir, projectDir, native);
  const project: VisualUsageProject = { projectId: `native-${native.mode}-${native.planSha256.slice(0, 8)}-${native.applicationSha256.slice(0, 8)}`,
    approvedAt: checked.checkedAt, planSha256: native.planSha256,
    applicationSha256: native.applicationSha256, packetSha256: checked.packetSha256,
    uses: native.uses };
  const core = { schemaVersion: 1 as const, kind: "native-visual-usage-receipt" as const,
    producerDir, mode: native.mode, route: native.route, machineCheckedAt: checked.checkedAt,
    humanApprovalClaim: false as const, visualPlan: native.visual, application: native.application,
    evidence: checked.pins, project };
  const value: NativeUsageReceipt = { ...core, digest: canonicalJsonSha256(core) };
  const directory = path.join(producerDir, NATIVE_USAGE_DIRECTORY);
  if (!existsSync(directory)) mkdirSync(directory, { mode: 0o700 });
  if (realpathSync(directory) !== directory || lstatSync(directory).isSymbolicLink()) {
    throw new Error("native visual usage directory must be canonical");
  }
  const legacyReceipt = path.join(directory, `${value.digest}.json`);
  const receipt = existsSync(legacyReceipt)
    ? legacyReceipt : path.join(directory, receiptName(value));
  if (!existsSync(receipt)) atomicCreateJsonSync(receipt, value);
  else if (canonicalJson(jsonFile(receipt, "native visual usage receipt").value)
      !== canonicalJson(value)) {
    throw new Error("native visual usage receipt identity is occupied by different bytes");
  }
  const registration = recordNativeUsageRegistration({ producerDir, projectDir,
    exportDir: checked.exportDir, delivery: checked.delivery, receipt,
    digest: value.digest, projectId: project.projectId });
  return { receipt, digest: value.digest, project,
    registration: { path: registration.path, sha256: registration.sha256 } };
}

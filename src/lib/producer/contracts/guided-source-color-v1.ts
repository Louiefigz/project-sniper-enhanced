/** Explicit source-observation transport only: no camera inference, grade or approval.
 * Actual used-source coverage, source frames, admitted bytes and runtime ownership
 * still require the original Python all-source preflight. These parsers do no IO.
 */
import { exactKeys, objectValue } from "./validation";
import { parsePrepareGuidedOpening, type PrepareGuidedOpeningV1 } from "./guided-opening-v1";

export const SOURCE_COLOR_V2_PROFILE = "original-uhd-xvycc709-observation-v2";
export const MAX_SOURCE_COLOR_REQUEST_BYTES = 4 * 1024 * 1024;

export interface SourceLightingGroup {
  id: string; startFrame: number; endFrame: number;
  intent: "neutral" | "dark" | "colored" | "unknown"; description: string;
}
export interface SourceColorDeclaration {
  schemaVersion: 1 | 2; sourceId: string; sourceProfile: "bt709-sdr" | "xvycc709" | "unknown";
  cameraProfile: string | null; historyState: "known" | "unknown";
  transformHistory: string[]; lightingGroups: SourceLightingGroup[];
}
export interface SourceColorSelection {
  profile: null | typeof SOURCE_COLOR_V2_PROFILE; declaration: SourceColorDeclaration;
}
export interface GuidedSourceColorV1 {
  schemaVersion: 1; declarations: Record<string, SourceColorSelection>;
}
export interface PrepareGuidedOpeningV2 extends Omit<PrepareGuidedOpeningV1, "schemaVersion"> {
  schemaVersion: 2; sourceColor: GuidedSourceColorV1;
}
export type PrepareGuidedOpeningRequest = PrepareGuidedOpeningV1 | PrepareGuidedOpeningV2;

const DECLARATION_KEYS = ["schemaVersion", "sourceId", "sourceProfile", "cameraProfile",
  "historyState", "transformHistory", "lightingGroups"];
const OPENING_V2_KEYS = ["schemaVersion", "operation", "idempotencyKey", "expectedToken", "expectedJournalHash",
  "proposalReadinessHash", "treatmentDraftRevisionHash", "sourceColor"];

/** Keep the source ID dialect shared with the existing grade input reader. */
function sourceId(value: unknown): string {
  if (typeof value !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/u.test(value)) {
    throw new Error("Source color identifier is invalid");
  }
  return value;
}

/** Preserve prose exactly; it is data, never filter code or verified history. */
function declarationText(value: unknown, maximum: number, empty = false): string {
  if (typeof value !== "string" || Array.from(value).length > maximum || (!empty && value.length === 0)
      || /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/u.test(value)
      || Array.from(value).some(char => char.length === 1 && /[\ud800-\udfff]/u.test(char))) {
    throw new Error("Source color declaration text is invalid");
  }
  return value;
}

/** Contiguous declared coverage only; its final frame is checked against real source evidence later. */
function lightingGroups(value: unknown, maximumFrames: number): SourceLightingGroup[] {
  if (!Array.isArray(value) || value.length < 1 || value.length > 12) throw new Error("Source color groups are unbounded");
  const seen = new Set<string>(); let position = 0;
  for (const item of value) {
    const row = objectValue(item, "source lighting group"), keys = ["id", "startFrame", "endFrame", "intent", "description"];
    exactKeys(row, keys, keys, "source lighting group");
    const id = sourceId(row.id);
    if (seen.has(id) || !Number.isSafeInteger(row.startFrame) || row.startFrame !== position
        || !Number.isSafeInteger(row.endFrame) || Number(row.endFrame) <= position || Number(row.endFrame) > maximumFrames
        || typeof row.intent !== "string" || !["neutral", "dark", "colored", "unknown"].includes(row.intent)) {
      throw new Error("Source color groups must have unique IDs and contiguous positive frame ranges");
    }
    declarationText(row.description, 500, true); seen.add(id); position = Number(row.endFrame);
  }
  return value as SourceLightingGroup[];
}

/** Explicit class/history rules only; operator statements are not verified camera facts. */
function declaration(value: unknown, id: string, profile: SourceColorSelection["profile"]): SourceColorDeclaration {
  const row = objectValue(value, "source color declaration");
  exactKeys(row, DECLARATION_KEYS, DECLARATION_KEYS, "source color declaration");
  const v2 = profile === SOURCE_COLOR_V2_PROFILE;
  if (row.sourceId !== id || row.schemaVersion !== (v2 ? 2 : 1)
      || typeof row.sourceProfile !== "string" || !(v2 ? ["xvycc709", "unknown"] : ["bt709-sdr"]).includes(row.sourceProfile)
      || typeof row.historyState !== "string" || !(v2 ? ["known", "unknown"] : ["known"]).includes(row.historyState)) {
    throw new Error("Source color declaration differs from its explicit source/profile/history class");
  }
  if (row.cameraProfile !== null) declarationText(row.cameraProfile, 200);
  if (!Array.isArray(row.transformHistory) || row.transformHistory.length > 20) throw new Error("Source color history is unbounded");
  for (const item of row.transformHistory) declarationText(item, 500);
  lightingGroups(row.lightingGroups, v2 ? 24_000 : 1_296_000);
  return row as unknown as SourceColorDeclaration;
}

/** A missing profile is not V1, and unknown history is never filled automatically. */
function selection(value: unknown, id: string): SourceColorSelection {
  const row = objectValue(value, "source color selection"), keys = ["profile", "declaration"];
  exactKeys(row, keys, keys, "source color selection");
  if (row.profile !== null && row.profile !== SOURCE_COLOR_V2_PROFILE) throw new Error("Source color observation profile is unsupported");
  declaration(row.declaration, id, row.profile);
  return row as unknown as SourceColorSelection;
}

/** Bounded immutable-request shape, not proof that these are the actual kept sources. */
export function parseGuidedSourceColor(value: unknown): GuidedSourceColorV1 {
  const row = objectValue(value, "guided source color"), keys = ["schemaVersion", "declarations"];
  exactKeys(row, keys, keys, "guided source color");
  if (row.schemaVersion !== 1) throw new Error("Unsupported source color request version");
  const declarations = objectValue(row.declarations, "source color declarations"), ids = Object.keys(declarations);
  if (ids.length < 1 || ids.length > 128) throw new Error("Source color declarations must name 1..128 sources");
  ids.forEach(id => selection(declarations[sourceId(id)], id));
  if (new TextEncoder().encode(JSON.stringify(row)).byteLength > MAX_SOURCE_COLOR_REQUEST_BYTES) {
    throw new Error("Source color request exceeds the transport budget");
  }
  return row as unknown as GuidedSourceColorV1;
}

/** Compare an explicit map to caller-supplied actual first-kept-occurrence IDs; no source discovery. */
export function assertGuidedSourceColorCoverage(value: GuidedSourceColorV1, ids: readonly string[]): void {
  parseGuidedSourceColor(value);
  if (!Array.isArray(ids) || ids.length < 1 || ids.length > 128 || new Set(ids).size !== ids.length) {
    throw new Error("Source color coverage requires the exact ordered unique used-source set");
  }
  for (const id of ids) sourceId(id);
  const selected = Object.keys(value.declarations);
  if (selected.length !== ids.length || ids.some(id => !Object.hasOwn(value.declarations, id))) {
    throw new Error("Source color declarations must cover exactly every used source");
  }
}

/** Additive request parser only; legacy launch/controller routes continue to reject V2 until wired. */
export function parsePrepareGuidedOpeningRequest(value: unknown): PrepareGuidedOpeningRequest {
  const row = objectValue(value, "guided opening request");
  if (row.schemaVersion === 1) return parsePrepareGuidedOpening(row);
  exactKeys(row, OPENING_V2_KEYS, OPENING_V2_KEYS, "guided opening V2 request");
  if (row.schemaVersion !== 2) throw new Error("Unsupported opening request version");
  const { sourceColor, ...base } = row;
  parsePrepareGuidedOpening({ ...base, schemaVersion: 1 });
  parseGuidedSourceColor(sourceColor);
  return row as unknown as PrepareGuidedOpeningV2;
}

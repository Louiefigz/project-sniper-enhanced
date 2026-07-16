export type NativePickerKind = "file" | "folder";

export interface NativePickerOptions {
  kind: NativePickerKind;
  prompt: string;
}

const MEDIA_UTIS = [
  "public.movie",
  "public.mpeg-4",
  "com.apple.quicktime-movie",
  "public.audio",
];

function requestRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return value as Record<string, unknown>;
}

export function pickerOptions(value: unknown): NativePickerOptions {
  const body = requestRecord(value);
  const requestedKind = body.kind;
  if (requestedKind != null && requestedKind !== "file" && requestedKind !== "folder") {
    throw new Error('kind must be "file" or "folder"');
  }

  const kind = requestedKind ?? (body.dir === true ? "folder" : "file");
  const fallback = kind === "folder" ? "Choose a project folder" : "Choose a media file";
  const prompt = typeof body.prompt === "string" && body.prompt.trim() ? body.prompt.trim() : fallback;
  return { kind, prompt };
}

function escapeAppleScriptText(value: string): string {
  return value.replace(/[\r\n\t]/g, " ").replace(/["\\]/g, "\\$&");
}

export function pickerAppleScript(options: NativePickerOptions): string {
  const prompt = escapeAppleScriptText(options.prompt);
  if (options.kind === "folder") {
    return `POSIX path of (choose folder with prompt "${prompt}")`;
  }
  const types = MEDIA_UTIS.map((uti) => `"${uti}"`).join(", ");
  return `POSIX path of (choose file with prompt "${prompt}" of type {${types}})`;
}

export function normalizePickedPath(stdout: string): string {
  const picked = stdout.trim();
  if (picked.length > 1 && picked.endsWith("/")) return picked.slice(0, -1);
  return picked;
}

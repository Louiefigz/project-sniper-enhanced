/** Trigger a browser download for a Blob, revoking the object URL afterward. */
export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** Download a plain-text string as a file. */
export function downloadText(content: string, filename: string, type = "text/plain") {
  downloadBlob(new Blob([content], { type }), filename);
}

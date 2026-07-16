/** Strip punctuation + lowercase for fuzzy word matching */
export function normalizeWord(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]/g, "");
}

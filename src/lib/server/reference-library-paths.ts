/**
 * One place for the packaged reference library's locations (resources/references).
 * Every loader reads through these constants, so the library can move without any
 * reader silently pointing at an old or external path.
 */
import path from "node:path";

export const REFERENCE_ROOT = path.join("resources", "references");
export const SHORTS_LIBRARY = path.join(REFERENCE_ROOT, "shorts");
export const SEQUENCE_LIBRARY = path.join(SHORTS_LIBRARY, "sequences");
export const EXPANSION_LIBRARY = path.join(SHORTS_LIBRARY, "expansion");
export const LONGFORM_LIBRARY = path.join(REFERENCE_ROOT, "longform");

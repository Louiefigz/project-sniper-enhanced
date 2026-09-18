/** Local Script Director template selection and slot filling; no model invocation. */
import { directorCatalogHash, templateSlots, type DirectorCatalog } from "./native-director-library";

export interface LocalHookSelection {
  anchor: string;
  slots: Record<string, string>;
}
export interface LocalHookCopy {
  anchor: string;
  category: string;
  template: string;
  libraryHash: string;
  slots: Record<string, string>;
  text: string;
  scope: "local-template-fill-not-editorial-approval";
}
export interface UserTitleCopy {
  text: string;
  scope: "user-supplied-title";
}
export type NativeTitleCopy = LocalHookCopy | UserTitleCopy;

/** Preserve explicit operator copy without attributing it to a Director formula. */
export function createUserTitleCopy(text: string): UserTitleCopy {
  if (typeof text !== "string" || !text.trim() || text.length > 120
      || /[\u0000-\u001f\u007f\u0085\u2028\u2029]/u.test(text)) {
    throw new Error("User-supplied title must be nonblank single-line copy of at most 120 characters");
  }
  return { text, scope: "user-supplied-title" };
}

/** Validate the same exact user-copy contract at presentation and project boundaries. */
export function assertUserTitleCopy(copy: UserTitleCopy): void {
  if (!copy || typeof copy !== "object" || Array.isArray(copy) || copy.scope !== "user-supplied-title"
      || Object.keys(copy).length !== 2 || Object.keys(copy).some((key) => !["scope", "text"].includes(key))) {
    throw new Error("User-supplied title cannot claim template or library authority");
  }
  createUserTitleCopy(copy.text);
}

/** Select the canonical formula before drafting; never copy a second hook catalog. */
export function fillLocalHookTemplate(catalog: DirectorCatalog, choice: LocalHookSelection): LocalHookCopy {
  const anchor = catalog.anchors.find((row) => row.id === choice.anchor);
  if (!anchor) throw new Error("Unknown local Director hook template");
  const quoted = /^"([^"\n]+)"/u.exec(anchor.template);
  if (!quoted) throw new Error("This template requires editorial adaptation rather than literal slot filling");
  const names = templateSlots(quoted[1]);
  if (!choice.slots || Array.isArray(choice.slots) || typeof choice.slots !== "object"
      || Object.keys(choice.slots).some((name) => !names.includes(name))) throw new Error("Unknown hook template slot");
  for (const value of Object.values(choice.slots)) {
    if (typeof value !== "string" || !value.trim() || value.length > 160
        || /[\[\]\r\n]/u.test(value)) throw new Error("Hook slot must contain explicit single-line copy");
  }
  let formula = quoted[1];
  // steps-toward-goal declares its timeframe clause optional (resources/director/hook-anchors.md).
  if (anchor.id === "steps-toward-goal" && !Object.hasOwn(choice.slots, "timeframe")) {
    formula = formula.replace(" (in [timeframe])", "");
  }
  const missing = templateSlots(formula).filter((name) => !Object.hasOwn(choice.slots, name));
  if (missing.length) throw new Error(`Missing hook template slots: ${missing.join(", ")}`);
  const text = formula.replace(/\[([^\]\n]+)\]/gu, (_, name: string) => choice.slots[name].trim());
  if (text.length > 120) throw new Error("Filled hook exceeds the native screen-copy limit");
  return { anchor: anchor.id, category: anchor.category, template: anchor.template,
    libraryHash: directorCatalogHash(catalog), slots: { ...choice.slots }, text,
    scope: "local-template-fill-not-editorial-approval" };
}

/** Presentation may wrap the selected words but cannot silently rewrite their promise. */
export function assertHookLineBreaks(copy: NativeTitleCopy, lines: string[]): void {
  if (copy?.scope === "user-supplied-title") {
    assertUserTitleCopy(copy);
  } else if (copy?.scope !== "local-template-fill-not-editorial-approval") {
    throw new Error("Unknown native title copy scope");
  }
  const normalize = (text: string) => text.replace(/\s+/gu, " ").trim();
  if (!Array.isArray(lines) || lines.length < 1 || lines.length > 3
      || lines.some((line) => typeof line !== "string" || !line.trim() || /[\r\n]/u.test(line))
      || normalize(lines.join(" ")) !== normalize(copy.text)) throw new Error("Title lines must preserve the selected hook copy");
}

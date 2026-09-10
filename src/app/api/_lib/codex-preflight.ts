import { codexProcessEnv, codexSettings } from "./ai-provider";
import { buildCodexArgs } from "./codex-cli";
import { admitSubscriptionInvocation } from "./subscription-invocation";
import { SUBSCRIPTION_VERSIONS } from "./subscription-policy";

export interface CodexPreflight {
  ready: boolean;
  version: string | null;
  authenticated: boolean;
  /** Version-pinned grammar, not a live provider/model compatibility call. */
  targetSyntaxSupported: boolean;
  detail: string | null;
}

/** Informational only; every actual inference repeats bounded subscription admission. */
export async function codexPreflight(signal?: AbortSignal): Promise<CodexPreflight> {
  try {
    const settings = codexSettings(), timeoutMs = 10_000;
    const admitted = await admitSubscriptionInvocation({ provider: "codex", bin: settings.bin,
      args: buildCodexArgs({ sandbox: "read-only", timeoutMs }), cwd: process.cwd(),
      env: codexProcessEnv(), timeoutMs, signal });
    admitted.remainingMs();
    return { ready: true, version: SUBSCRIPTION_VERSIONS.codex, authenticated: true,
      targetSyntaxSupported: true, detail: "Pinned CLI syntax and ChatGPT authentication; account overage policy is not verified" };
  } catch {
    return { ready: false, version: null, authenticated: false, targetSyntaxSupported: false,
      detail: "Bounded Codex subscription admission failed or cleanup is unverified; no inference ran. Do not retry automatically." };
  }
}

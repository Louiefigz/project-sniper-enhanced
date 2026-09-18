/**
 * Check the selected editor-brain provider with the product's own admission.
 *
 *   node --import tsx scripts/infra/provider-admission.ts [--provider codex|claude]
 *
 * This is a thin adapter, not a second policy: it calls the same
 * `admitSubscriptionInvocation` every real inference calls, with the same argument
 * builders and the same filtered environment. It runs the version and
 * authentication checks and stops before any inference. It prints one JSON line
 * and never prints authentication output — the admission code discards it.
 */
import { admitSubscriptionInvocation } from "@/app/api/_lib/subscription-invocation";
import { brainProvider, claudeModelArgs, claudeProcessEnv, codexProcessEnv, codexSettings }
  from "@/app/api/_lib/ai-provider";
import { buildCodexArgs } from "@/app/api/_lib/codex-cli";
import { SUBSCRIPTION_VERSIONS, type SubscriptionProvider } from "@/app/api/_lib/subscription-policy";

export interface AdmissionReport {
  provider: SubscriptionProvider;
  admittedVersion: string;
  ready: boolean;
  reason: "ready" | "cli-missing" | "wrong-version" | "not-signed-in-or-not-subscription"
    | "unexpected-diagnostics" | "timeout-or-cancelled" | "invalid-configuration" | "unknown";
  detail: string;
}

const REASONS: Array<[RegExp, AdmissionReport["reason"]]> = [
  [/executable is unavailable|must be absolute|path is invalid|not a regular executable/u, "cli-missing"],
  [/version is not qualified/u, "wrong-version"],
  [/emitted unexpected diagnostics/u, "unexpected-diagnostics"],
  [/requires verified|metadata is invalid|was not confirmed/u, "not-signed-in-or-not-subscription"],
  [/timed out|cancelled/u, "timeout-or-cancelled"],
  [/must be one of|contains an invalid value|unsupported/iu, "invalid-configuration"],
];

/** The provider the app will actually use, from the same setting the app reads. */
export function selectedProvider(explicit?: string): SubscriptionProvider {
  if (explicit === "codex" || explicit === "claude") return explicit;
  return brainProvider() === "codex" ? "codex" : "claude";
}

function invocation(provider: SubscriptionProvider) {
  const timeoutMs = 20_000;
  if (provider === "codex") {
    return { provider, bin: codexSettings().bin, timeoutMs, cwd: process.cwd(), env: codexProcessEnv(),
      args: buildCodexArgs({ sandbox: "read-only", timeoutMs }) };
  }
  return { provider, bin: process.env.CLAUDE_BIN || "claude", timeoutMs, cwd: process.cwd(),
    env: claudeProcessEnv(), args: ["-p", "admission check", ...claudeModelArgs(), "--output-format", "json"] };
}

/** Run admission for one provider and classify the result without exposing account data. */
export async function checkProviderAdmission(provider: SubscriptionProvider): Promise<AdmissionReport> {
  const admittedVersion = SUBSCRIPTION_VERSIONS[provider];
  try {
    const admitted = await admitSubscriptionInvocation(invocation(provider));
    admitted.remainingMs();
    return { provider, admittedVersion, ready: true, reason: "ready",
      detail: "pinned CLI version and subscription sign-in accepted; no inference was run" };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const reason = REASONS.find(([pattern]) => pattern.test(message))?.[1] ?? "unknown";
    return { provider, admittedVersion, ready: false, reason, detail: message };
  }
}

async function main(): Promise<void> {
  const flag = process.argv.indexOf("--provider");
  const provider = selectedProvider(flag >= 0 ? process.argv[flag + 1] : undefined);
  const report = await checkProviderAdmission(provider);
  process.stdout.write(`${JSON.stringify(report)}\n`);
  process.exitCode = report.ready ? 0 : 1;
}

if (process.argv[1]?.endsWith("provider-admission.ts")) void main();

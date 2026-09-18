/**
 * Text Review is the one optional paid feature: it sends still frames to Anthropic
 * on the buyer's own API key. It needs an explicit per-run opt-in and a key the
 * buyer configured (the package launchers never inherit one from the shell).
 */
export function textReviewPaidFeatureError(
  consent: unknown,
  env: Readonly<Record<string, string | undefined>> = process.env,
): string | null {
  if (consent !== true) {
    return "Text Review is an optional paid feature: confirm that it may send still frames to Anthropic "
      + "and bill your own Anthropic API key";
  }
  if (!env.ANTHROPIC_API_KEY?.trim()) {
    return "Text Review needs your own Anthropic API key (ANTHROPIC_API_KEY in runtime/sniper.local.env); "
      + "it is not covered by your Codex or Claude subscription";
  }
  return null;
}

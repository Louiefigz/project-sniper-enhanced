/** Explicit synthetic observation for controller tests, never real-media proof. */
export function audioAuditFixture(finalSha256 = "a".repeat(64)) {
  const audioDelivery = {
    policyVersion: 2, integratedLufs: -14, truePeakDbtp: -2,
    lufsTarget: -14, lufsTolerance: 1, truePeakCeilingDbtp: -1.5,
    lufsResidual: 0, truePeakExcessDb: 0, lufsWithinTolerance: true,
    truePeakWithinCeiling: true, audioDecodeSucceeded: true,
    audioDecodeExitCode: 0, audioDecodeError: "", qualified: true,
  };
  return {
    overall: "pass", audioDeliveryPolicyVersion: 2, finalSha256, audioDelivery,
    checks: ["audio_decode_complete", "loudness_integrated", "loudness_true_peak",
      "format_acodec", "format_arate", "format_achannels", "audio_av_timing",
      "final_identity"].map((name) => ({
      name, status: "pass", measured: "synthetic controller fixture", detail: "not media evidence",
    })),
  };
}

/** Versioned machine contract, not a listening/perceptual-quality verdict. */
type Row = Record<string, unknown>;

const EVIDENCE_KEYS = [
  "policyVersion", "integratedLufs", "truePeakDbtp", "lufsTarget", "lufsTolerance",
  "truePeakCeilingDbtp", "lufsResidual", "truePeakExcessDb", "lufsWithinTolerance",
  "truePeakWithinCeiling", "audioDecodeSucceeded", "audioDecodeExitCode",
  "audioDecodeError", "qualified",
];

function row(value: unknown): Row | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Row : null;
}

function finiteOrNull(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isFinite(value));
}

function evidenceFailure(value: Row): string | null {
  if (Object.keys(value).length !== EVIDENCE_KEYS.length
      || !EVIDENCE_KEYS.every((key) => Object.hasOwn(value, key))) {
    return "audio evidence has missing or unknown fields";
  }
  // These constants define audio policy v2. Python's producer_config remains
  // the renderer source; a changed target requires a new cross-runtime policy.
  if (value.policyVersion !== 2 || value.lufsTarget !== -14 || value.lufsTolerance !== 1
      || value.truePeakCeilingDbtp !== -1.5) return "audio delivery policy is stale";
  if (!finiteOrNull(value.integratedLufs) || !finiteOrNull(value.truePeakDbtp)
      || !Number.isInteger(value.audioDecodeExitCode)
      || typeof value.audioDecodeError !== "string") return "audio observation is malformed";
  const decoded = value.audioDecodeExitCode === 0;
  const integrated = value.integratedLufs;
  const peak = value.truePeakDbtp;
  const residual = integrated === null ? null : integrated + 14;
  const excess = peak === null ? null : Math.max(0, peak + 1.5);
  const loudnessOk = residual !== null && Math.abs(residual) <= 1;
  const peakOk = peak !== null && peak <= -1.5;
  if ((!decoded && (integrated !== null || peak !== null))
      || value.audioDecodeSucceeded !== decoded || value.lufsResidual !== residual
      || value.truePeakExcessDb !== excess || value.lufsWithinTolerance !== loudnessOk
      || value.truePeakWithinCeiling !== peakOk
      || value.qualified !== (decoded && loudnessOk && peakOk)
      || (value.qualified === true && value.audioDecodeError !== "")) {
    return "audio evidence contradicts its measured values";
  }
  return null;
}

function checksFailure(checks: unknown[], evidence: Row): string | null {
  const expected = new Map([
    ["audio_decode_complete", evidence.audioDecodeSucceeded === true],
    ["loudness_integrated", evidence.audioDecodeSucceeded === true
      && evidence.lufsWithinTolerance === true],
    ["loudness_true_peak", evidence.audioDecodeSucceeded === true
      && evidence.truePeakWithinCeiling === true],
  ]);
  for (const [name, passed] of expected) {
    const matching = checks.map(row).filter((check) => check?.name === name);
    if (matching.length !== 1 || matching[0]?.status !== (passed ? "pass" : "fail")) {
      return `audio audit row ${name} is missing, duplicated, or contradictory`;
    }
  }
  if (evidence.qualified !== true) return "audio delivery failed complete-decode/LUFS/true-peak policy";
  for (const name of ["format_acodec", "format_arate", "format_achannels", "audio_av_timing", "final_identity"]) {
    const matching = checks.map(row).filter((check) => check?.name === name);
    if (matching.length !== 1 || matching[0]?.status !== "pass") {
      return `audio mechanical check is missing or failed: ${name}`;
    }
  }
  const mechanical = checks.map(row).find((check) => check?.status === "fail"
    && (String(check.name).startsWith("format_a") || check.name === "audio_av_timing"));
  return mechanical ? `audio mechanical check failed: ${String(mechanical.name)}` : null;
}

/** Missing/stale/malformed evidence and mechanical audio defects are terminal. */
export function audioAuditFailure(value: unknown, expectedSha256?: string | null): string | null {
  const machine = row(value);
  if (machine?.audioDeliveryPolicyVersion !== 2) return "audio audit policy v2 is required";
  if (!["pass", "warn", "fail"].includes(String(machine.overall))) return "audio audit verdict is invalid";
  if (typeof machine.finalSha256 !== "string" || !/^[0-9a-f]{64}$/u.test(machine.finalSha256)
      || (expectedSha256 !== undefined && machine.finalSha256 !== expectedSha256)) {
    return "audio audit does not bind the expected candidate bytes";
  }
  const evidence = row(machine.audioDelivery);
  if (!evidence || !Array.isArray(machine.checks)) return "audio audit evidence is missing";
  return evidenceFailure(evidence) ?? checksFailure(machine.checks, evidence);
}

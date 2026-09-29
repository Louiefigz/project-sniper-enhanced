/** Register one machine-checked native allocation in its producer project's usage memory. */
import { registerNativeVisualUsage } from
  "../../src/lib/server/native-visual-usage-receipt";

const USAGE = "Usage: visual-plan-usage.ts register <producer-dir> <native-project-dir> <checked-export-dir>";

export function executeVisualPlanUsage(argv: string[]) {
  const [operation, producerDir, projectDir, exportDir] = argv;
  if (operation !== "register" || !producerDir || !projectDir || !exportDir
      || argv.length !== 4) throw new Error(USAGE);
  return { status: "native-visual-usage-registered",
    humanApprovalClaim: false,
    ...registerNativeVisualUsage(producerDir, projectDir, exportDir) };
}

if (require.main === module) {
  try {
    console.log(JSON.stringify(executeVisualPlanUsage(process.argv.slice(2))));
  } catch (error) {
    console.error(JSON.stringify({ ok: false, error: String(error).slice(0, 2048) }));
    process.exitCode = 1;
  }
}

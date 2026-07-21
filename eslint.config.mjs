import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Bundled agent skills, isolated worktrees, Python packages, and vendored
    // browser libraries are inputs/assets, not Next application source.
    ".agents/**",
    ".claude/worktrees/**",
    ".venv/**",
    "templates/motion/vendor/**",
    "vendor/hyperframes-skills/**",
    // Frozen gate-run evidence trees (vendored gsap copies, captured project
    // snapshots) — records, not application source.
    "artifacts/**",
  ]),
  {
    // Node isolation shims are deliberately CommonJS (.cjs) so a bare `node`
    // subprocess can load them without a loader; require() is the point.
    files: ["**/*.cjs"],
    rules: { "@typescript-eslint/no-require-imports": "off" },
  },
]);

export default eslintConfig;

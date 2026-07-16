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
  ]),
]);

export default eslintConfig;

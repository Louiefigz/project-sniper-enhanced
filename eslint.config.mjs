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
    // next.config.ts also permits named .next-<slug> qualification caches.
    ".next-*/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Bundled agent skills, isolated worktrees, Python packages, and vendored
    // browser libraries are inputs/assets, not Next application source.
    ".agents/**",
    ".claude/worktrees/**",
    ".venv/**",
    // Installed native SDK copies and frame caches are generated dependencies.
    "**/.sniper-native-runtime/**",
    "templates/motion/vendor/**",
    "vendor/hyperframes-skills/**",
    // Frozen gate-run evidence trees (vendored gsap copies, captured project
    // snapshots) — records, not application source.
    "artifacts/**",
  ]),
  {
    // Node isolation shims and these two source-injected diagnostic workers
    // deliberately run as CommonJS; the worker policies pass their bytes to
    // the sealed image's `node -e`, not an application ESM loader.
    files: [
      "**/*.cjs",
      "scripts/producer/headless/color_diagnostic_worker.js",
      "scripts/producer/headless/grade_observation_worker.js",
    ],
    rules: { "@typescript-eslint/no-require-imports": "off" },
  },
  {
    // These CommonJS fragments are concatenated before the renderer image
    // executes them, so declarations intentionally cross the file boundary.
    files: [
      "scripts/producer/headless/qualification_mezzanine_worker.js",
      "scripts/producer/headless/qualification_mezzanine_worker_media.js",
    ],
    rules: {
      "@typescript-eslint/no-require-imports": "off",
      "@typescript-eslint/no-unused-vars": "off",
    },
  },
]);

export default eslintConfig;

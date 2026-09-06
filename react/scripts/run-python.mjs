/** Run the backend with the repository virtual environment when available. */

import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const reactDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const root = resolve(reactDir, "..");
const candidates =
  process.platform === "win32"
    ? [resolve(root, ".venv", "Scripts", "python.exe"), "python"]
    : [resolve(root, ".venv", "bin", "python"), "python3", "python"];
const python = candidates.find((candidate) => !candidate.includes(".venv") || existsSync(candidate));

if (!python) {
  console.error("Python was not found. Create .venv or install Python 3.11+.");
  process.exit(1);
}

const result = spawnSync(python, process.argv.slice(2), {
  cwd: root,
  env: process.env,
  stdio: "inherit",
});

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}
process.exit(result.status ?? 1);

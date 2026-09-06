/**
 * Copy generated content from ../output into public/data and build a manifest.
 *
 * The tkinter launchers read JSON straight off disk with pathlib; a browser
 * cannot, so the equivalent step here is to stage the files under public/ and
 * emit an index the app can fetch. Run via `npm run sync` (also runs
 * automatically before `dev` and `build`).
 */

import { cp, mkdir, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const source = resolve(root, "..", "output");
const target = resolve(root, "public", "data");

/** Content kinds, mirroring one tkinter launcher each. */
const KINDS = [
  { kind: "quizzes", titleOf: (d) => d.title },
  { kind: "mindmaps", titleOf: (d) => d.name },
  { kind: "flashcards", titleOf: (d) => d.title },
  { kind: "reports", titleOf: (d) => d.title },
  { kind: "slides", titleOf: (d) => d.title },
  { kind: "datatables", titleOf: (d) => d.title },
  { kind: "infographics", titleOf: (d) => d.title },
];

/** Sibling artifacts worth surfacing in the UI, by kind. */
const SIDECARS = {
  mindmaps: [".md", ".mmd"],
  reports: [".md", ".html"],
  slides: [".md"],
  datatables: [".csv"],
  infographics: [".html", ".svg", ".md", ".wireframe.txt"],
  flashcards: [".txt"],
};

async function listJson(dir) {
  if (!existsSync(dir)) return [];
  const entries = await readdir(dir, { withFileTypes: true });
  return entries
    .filter((e) => e.isFile() && e.name.endsWith(".json"))
    .map((e) => e.name)
    .sort();
}

async function sidecarsFor(dir, stem, kind) {
  const found = [];
  for (const suffix of SIDECARS[kind] ?? []) {
    const name = `${stem}${suffix}`;
    if (existsSync(join(dir, name))) found.push(name);
  }
  return found;
}

async function main() {
  if (!existsSync(source)) {
    console.error(`No output folder at ${source} — nothing to sync.`);
    process.exit(1);
  }

  await rm(target, { recursive: true, force: true });
  await mkdir(target, { recursive: true });

  const manifest = { generatedAt: new Date().toISOString(), kinds: {} };
  let total = 0;

  for (const { kind, titleOf } of KINDS) {
    const dir = join(source, kind);
    const files = await listJson(dir);
    const documents = [];

    for (const file of files) {
      const stem = file.replace(/\.json$/, "");
      let data;
      try {
        data = JSON.parse(await readFile(join(dir, file), "utf8"));
      } catch (error) {
        console.warn(`  skipped ${kind}/${file}: ${error.message}`);
        continue;
      }
      documents.push({
        file,
        stem,
        title: titleOf(data) ?? stem,
        sidecars: await sidecarsFor(dir, stem, kind),
      });
    }

    if (documents.length) {
      await cp(dir, join(target, kind), { recursive: true });
      total += documents.length;
    }
    manifest.kinds[kind] = documents;
    console.log(`  ${kind.padEnd(14)} ${documents.length} document(s)`);
  }

  await writeFile(
    join(target, "manifest.json"),
    JSON.stringify(manifest, null, 2),
    "utf8",
  );
  console.log(`\nSynced ${total} documents to public/data`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

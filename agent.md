## Cross-platform UI

- Whenever the Python Windows UI changes, make the corresponding change in the React UI.
- Keep shared behavior and generated-content formats consistent across platforms.
- Structure new functionality so it can later support Android and iOS.

## Repository hygiene

- Keep source code, configuration, prompts, skills, and documentation in Git.
- Do not commit `input/`, `output/`, `react/public/data/`, dependencies, build artifacts, caches, or local secrets.
- Run the relevant Python checks and `npm run typecheck` from `react/` after changes.

## Releases

- Merging into `main` triggers `.github/workflows/release-on-main.yml`.
- The workflow creates a GitHub Release with a tag in the `vYYYY.MM.DD.N` format and generated notes.
- Do not create a duplicate manual release tag for a merge into `main`.
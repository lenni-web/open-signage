# Repository instructions

- Maintain `CHANGELOG.md` for every user-visible feature, behavior change,
  bug fix, security fix, deprecation, or removal.
- Add work in progress below `Unreleased`; when preparing a release, move the
  entries into a dated version section.
- Keep the single source of truth for the version in
  `src/open_signage/version.py`.
- Follow semantic versioning:
  - patch for backward-compatible fixes;
  - minor for backward-compatible features;
  - major for incompatible changes.
- A release version bump and its dated changelog section must be committed
  together.

# Public Release Design

Status: initial release approved by the repository owner on 2026-11-09; expanded package approved after the owner requested the full update.

## Goal

Publish Novel Master Lab as a standalone Codex skill for Chinese serialized fiction. Keep the scene-first, three-pass writing method while adding proportionate long-form continuity controls. A reader must be able to install and use this repository without the original local `chinese-novel-master` skill.

## Package

- `SKILL.md`: complete controller for project intake, planning, chapter drafting, three-pass revision, candidate-to-canon approval, and periodic review.
- `references/`: planning, chapter craft, source validity, scoped briefs, optional structured state, and separate literary/factual review.
- `agents/openai.yaml`: Codex discovery metadata.
- `templates/`: five new-project planning documents, chapter and review forms, and empty JSON state files.
- `scripts/nml.py`: dependency-free, read-only-by-default state checks and an explicit, backed-up approval operation.
- `tests/` and `.github/workflows/test.yml`: synthetic regression coverage on supported Python versions.
- `README.md`: concise Chinese purpose, workflow, installation, usage, and output.

No novel manuscript, first-chapter trial, private evaluation report, local absolute path, token, or secret is part of this public package. No license is selected in this release.

## Behavior and Boundaries

The skill is one writing controller, not a separate CLI or a guaranteed quality score. Short tasks do not require a ceremonial ledger. For a long-running novel or a high-risk rewrite, it checks source coverage, effective chapter range, character knowledge, object holders, costs, and adjacent chapter promises. Drafted facts remain candidates until approved. An independent factual read is recommended when available; self-review must be labeled honestly.

## Verification

Run Codex's `quick_validate.py`, run the Python regression suite, inspect the published tree for private material, compare the installed and published copies, verify a clean git state, then confirm the public GitHub URL and CI. A one-chapter pilot is exploratory evidence only, not proof of repeatable 8.2+ literary quality.

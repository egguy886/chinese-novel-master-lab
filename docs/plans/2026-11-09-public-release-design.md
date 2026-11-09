# Public Release Design

Status: approved by the repository owner on 2026-11-09.

## Goal

Publish Novel Master Lab as a standalone Codex skill for Chinese serialized fiction. Keep the scene-first, three-pass writing method while adding proportionate long-form continuity controls. A reader must be able to install and use this repository without the original local `chinese-novel-master` skill.

## Package

- `SKILL.md`: complete controller for project intake, planning, chapter drafting, three-pass revision, candidate-to-canon approval, and periodic review.
- `references/project-bootstrap.md`: roles of the five lightweight planning files and how to handle existing projects.
- `references/long-form-continuity.md`: source validity, scoped chapter briefs, moving state, evidence checks, and chapter handoff.
- `agents/openai.yaml`: Codex discovery metadata.
- `README.md`: Chinese introduction, features, installation, usage, deliverables, limitations, and validation status.

No novel manuscript, first-chapter trial, private evaluation report, local absolute path, token, or secret is part of this public package. No license is selected in this release.

## Behavior and Boundaries

The skill is one writing controller, not a separate CLI or a guaranteed quality score. Short tasks do not require a ceremonial ledger. For a long-running novel or a high-risk rewrite, it checks source coverage, effective chapter range, character knowledge, object holders, costs, and adjacent chapter promises. Drafted facts remain candidates until approved. An independent factual read is recommended when available; self-review must be labeled honestly.

## Verification

Run Codex's `quick_validate.py`, inspect the published tree for private material, compare the installed and published copies, verify a clean git state, then confirm the public GitHub URL and rendered README. A one-chapter pilot is exploratory evidence only, not proof of repeatable 8.2+ literary quality.

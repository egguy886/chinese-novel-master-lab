# Optional Project State Contract

This is an optional, minimal structured ledger for long projects. The prose and approved project documents remain the meaning-bearing sources. JSON checks can catch stale hashes, impossible transfers, and invalid state transitions; they cannot decide whether a character's reaction is believable or whether a clue is truly paid off.

## Files

Set `SKILL_DIR` to the absolute path of this installed skill and `PROJECT` to the novel project's absolute path. Run the script through `"$SKILL_DIR/scripts/nml.py"`, regardless of the current working directory. `python3 "$SKILL_DIR/scripts/nml.py" init "$PROJECT"` creates these files without overwriting existing ones:

```text
PROJECT/.novel-master-lab/
  sources.json
  state.json
  deltas/
  approvals/
  backups/
```

The project may keep chapters and planning documents wherever it already does. All paths recorded in the ledger are relative to the project root. The ledger is not a replacement for accepted chapters.

## Source Registry

`sources.json` records each relevant source's `id`, `path`, `kind`, `status`, chapter coverage, last verified chapter, and a short note. Valid statuses are `active`, `candidate`, `stale`, and `mixed`. If a document's declared end precedes appended entries, mark it `mixed` and verify needed claims against accepted prose before using them.

The script reports missing files, inconsistent chapter ranges, and misleading `active` status as errors or warnings according to source status. It does not read a Markdown heading and infer truth from prose. After approval, it registers the accepted chapter with its SHA-256, so later edits to that file are detected.

## State Snapshot

`state.json` contains `as_of_chapter`, `story_day`, and maps for `characters`, `locations`, `relationships`, `props`, `knowledge`, `threads`, and `promises`. Keep entries small and anchored to an accepted chapter or approved source. A character's knowledge level is `unknown` (absent), `suspects`, or `knows`. A prop holder must be a registered character or location, or the sentinel `unknown`, `lost`, or `consumed`.

Stable character identity and speech can live in the character map; changing facts such as location and condition are updated by approved deltas. For a rewrite of an earlier chapter, do not compare against a later snapshot as though the earlier viewpoint knew it.

Character entries may list `aliases` and `deprecated_names`; `state.json` may also list global `retired_names`. The checker gives a **warning** for literal appearances of deprecated or retired names after masking active names and aliases. It cannot decide whether a historical quotation or an ambiguous substring is intentional.

## Candidate Delta

After drafting a continuation chapter, run:

```bash
python3 "$SKILL_DIR/scripts/nml.py" prepare "$PROJECT" \
  "$PROJECT/path/to/chapter.md" --chapter 12
```

This creates a candidate JSON delta with the chapter file's SHA-256 and the current state file's SHA-256. Fill only changes shown in the chapter. Each meaningful change needs a concise evidence locator. Use `new_entities` for approved-ready new characters, facts, props, or threads; use `new_canon_requests` for proposals that still require a decision.

The supported changes are character, relationship, prop, knowledge, thread, and chapter-promise changes. The data shapes are illustrated in `templates/delta.json`. Do not use the ledger to backfill an entire novel in one pass; start with the active arc and expand only when needed.

For filled examples, read [structured delta examples](data-examples.md). The template is intentionally empty so an agent cannot mistake sample events for this project's facts.

## Check and Approval

`python3 "$SKILL_DIR/scripts/nml.py" check "$PROJECT" --delta "$PROJECT/path/to/delta.json"` is read-only. It checks the hashes, adjacent chapter number, monotonic story day, existing prop holder, knowledge progression, thread lifecycle, evidence presence, and registered source status. A passing check is **not** approval of literary quality or factual truth in the prose.

`python3 "$SKILL_DIR/scripts/nml.py" approve "$PROJECT" --delta "$PROJECT/path/to/delta.json" --approval-note "user approved chapter and delta"` mutates the state and source registry only after explicit user approval in the conversation. The agent must not use it merely because a script passes. It saves the previous state and source registry in `backups/` and an approval receipt in `approvals/`; the delta remains a candidate artifact. The command refuses unresolved `new_canon_requests`, stale hashes, unsupported rewrites, and duplicate approval receipts. Its approval note is a record of a decision, not machine proof that a human approved it.

For an earlier-chapter rewrite, use a scoped manual impact review instead of `approve`; subsequent accepted chapters may need re-evaluation. Never silently replace them.

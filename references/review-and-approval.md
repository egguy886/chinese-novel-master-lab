# Review and Approval

Keep creative writing, literary response, factual checking, and canon updates distinct. Use separate contexts when available, but do not require a multi-agent chain for every chapter.

## Inputs

The writer receives a compact scene brief: current viewpoint, goal, pressure, relationship state, exact binding facts, previous consequence, and open invention space. Do not feed the writer the full fact ledger, previous editorial complaints, private reviewer notes, or a score target.

The first reader sees the chapter and the minimum context needed to follow it. Ask what held attention, what felt uncertain, where interest dropped, and what the reader expects next. Do not ask the first reader to solve continuity.

The literary editor sees the draft and the first-reader response. Classify issues as local prose work, scene restaging, or a problem in the chapter premise. Do not rewrite a broken premise with decorative language. Preserve the original draft before substantial editing.

The factual reviewer sees the draft and only the relevant approved sources or exact claims. Report `claim | source | pass/conflict/uncertain | proposed action`. It may identify a missing physical detail or knowledge leak; it does not write patch prose or decide a character's feelings.

When independent contexts are unavailable, perform the passes sequentially and label them self-review. Do not claim an independent audit occurred.

## Approval Boundary

1. Present the chapter candidate and any material conflicts.
2. Present a separate candidate delta: new facts, state changes, resource transfers, relationship shifts, clue movement, and next-chapter promise.
3. Obtain user approval for both the text and the material delta before updating approved canon.
4. After approval, preview affected state files and then commit the approved changes. If using the optional structured ledger, run its read-only `check` before `approve`.

If the user approves prose but questions a new fact, keep that fact unresolved. If the chapter is rewritten after approval, repeat the impact check; a prior approval does not automatically cover a different draft hash.

## Review Rhythm

- Every 3-5 accepted chapters: read for repeated phrasing, character voice, emotional movement, dropped costs, and whether the protagonist is still acting.
- Every 10 accepted chapters: read arc escalation, promise/payoff, thread gaps, time/place/asset consistency, and the next cycle's pressure.

These are editorial checkpoints, not prescribed scene rhythms. Report evidence and uncertainty; do not turn a single model score into a claim of stable quality.

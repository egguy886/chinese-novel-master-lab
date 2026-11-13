# Final Check（终检）

Load this before presenting a chapter candidate. The final check is the last gate after the three writing passes. It is adapted from Commercial Writing System v2.1: its mechanical lint and its ending discipline. NML keeps the authorship. The final check finds defects; it does not take over the voice.

## Order

1. Free draft → canon lock → human voice. Writing happens here.
2. **Final check.** Run the script, audit the ending, make minimal repairs.
3. Extract the candidate delta, then present the chapter.

If a first reader, editor, or fact check later changes the text, run the final check again before presenting it.

Do not run the final check on a free draft. It only cleans prose that already has its voice.

## Minimal-Repair Rule

Every repair must be the smallest change that clears the finding:

- Fix the punctuation, replace the flagged phrase, or move the cut point of the ending.
- Do not rewrite dialogue, change a character's speech habits, add explanation, or restage a scene to satisfy the gate.
- If a repair touches more than three sentences, or changes what a character says, reread that passage as a human-voice pass before finishing.
- A finding that would require damaging the scene to clear is reported to the user with the reason. It is not silenced by rewording around the rule.

## Script

```bash
python3 "$SKILL_DIR/scripts/nml.py" final-check "$PROJECT/path/to/chapter.md" \
  --project "$PROJECT" \
  --previous "$PROJECT/path/to/earlier-01.md" "$PROJECT/path/to/earlier-02.md" \
  --hook "关键词1,关键词2" \
  --catch "上一章结尾的关键词"
```

The command is read-only and returns exit code 1 when any ERROR remains. It checks:

| Area | ERROR | WARN |
| --- | --- | --- |
| quotes | straight `"` quotes; mixed quote styles; unpaired quotes | half-width punctuation between Chinese characters; dialogue that may have lost its quotes |
| phrase | stock AI-flavoured phrases over their limit (default list from CWS `cn-webnovel`) | — |
| ending | summary or uplift lines in the last two paragraphs ("一切才刚刚开始", "命运的齿轮" …) | — |
| length | far outside the configured Han-character range | slightly outside the range |
| hook | words from `--hook` are missing from the last 300 characters | — |
| catch | words from `--catch` are missing from the first 400 characters | — |
| meta | — | planning or audit text in prose (本章, 伏笔, 细纲, list or table syntax …) |
| names | — | deprecated or retired names, when the project ledger exists |

Multi-chapter phrase limits count earlier chapters only when the current chapter itself uses the phrase. Old chapters cannot block a clean new one.

Pass `--previous` with the most recent chapters, oldest first. When the project's earlier chapters violate a rule, do not edit them during the final check; list them for a later revision pass.

### Project Configuration

Put project rules in `PROJECT/.novel-master-lab/final-check.json`, or pass `--config`. Start from `templates/final-check.json`. Supported keys:

- `quotes`: `cn_curly`, `corner`, or `none`;
- `length`: `min`, `max`, `tolerance`;
- `extra_banned`: rules added for this book;
- `disable_banned`: default terms switched off;
- `banned`: replaces the default list;
- `ending_patterns`, `meta_patterns`, `lost_quote_pattern`;
- `ending_window_paragraphs`, `landing_chars`, `opening_chars`.

A banned rule is:

```json
{"term": "…", "regex": false, "where": "narration", "max": 0, "window": 1, "severity": "ERROR", "label": "…", "note": "…"}
```

A book-specific exception belongs in the project config, with the reason in the project's own notes. Do not edit the skill's defaults for one book.

## Ending Audit

The script only proves that the planned words landed. A person judges the ending's force. Read the last 100–300 characters and classify the ending backstage:

| Strength | Meaning | Use |
| --- | --- | --- |
| 1 | light close or small question | transitional chapters in bought-out or slow books only |
| 2 | one clear small question the next opening can answer | occasional; never two chapters in a row in a paid serial |
| 3 | the situation changed: new variable, new arrival, interruption | the floor for a serial chapter |
| 4 | real threat to a relationship, secret, body, or safety | before a paywall, during promotion, at unit ends |
| 5 | a known core fact overturned, life-or-death, irreversible | paywall chapter, major climax, volume end |

Hook types, from hardest to softest:

- **Hard:** danger, caught, reveal, desire, reversal.
- **Propulsion:** message, deadline, showdown, decision, arrival.
- **Soft:** question, button. A button is a closing line that shifts the relationship.

Checks:

- **Live consequence.** A serial chapter, except the final one, ends with something unresolved that the next chapter must answer. Aftermath can end a chapter when it changes the relationship or the reader's question. Comfort that closes every question cannot.
- **Half-beat cut** (from CWS). For paywall, unit-end, volume-end, and other planned high-strength chapters, cut while the action is half done or at the moment of interruption, not after it lands. A good half-beat cut has been seeded inside the chapter: the reader knows why the door is about to open. Do not force this shape on every chapter. NML still varies its endings.
- **Rhythm.** Do not use the same hook type more than two chapters in a row. Do not end two chapters in a row on a soft hook.
- **Payability.** The next chapter must be able to pay the hook in its opening, or the plan must say when the hook is paid.

Record the type, strength, and keywords in the review report, not in the prose.

## Report

Add a short final-check block to the chapter review:

- the script result: errors and warnings;
- each repair, as a before → after phrase;
- each finding kept, with its reason;
- the ending's hook type and strength.

A passing final check means the encoded rules passed. It does not certify literary quality, factual truth, or user approval.

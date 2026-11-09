# Structured Delta Examples

These are small examples for the optional `.novel-master-lab` ledger, not required story beats. Each `evidence` value should point to a chapter passage or accepted source the project can actually inspect. `check` validates structure and transitions; it cannot verify the meaning of that passage.

## Source Registry Entry

```json
{
  "id": "old-ledger",
  "path": "设定/旧账本.md",
  "kind": "snapshot",
  "status": "mixed",
  "chapter_start": 1,
  "chapter_end": 53,
  "declared_through": 53,
  "latest_entry_chapter": 80,
  "verified_through": 53,
  "note": "Later entries require checking against accepted chapters."
}
```

## Approved State Entries

```json
{
  "characters": {
    "captain": {"name": "船长", "location": "码头", "condition": "无伤", "resources": "两桶水", "aim": "返航", "voice": "简短"}
  },
  "props": {
    "ledger": {"name": "旧账册", "holder": "captain", "condition": "封口完整"}
  },
  "knowledge": {
    "f1": {"statement": "账册有夹层", "people": {}}
  },
  "threads": {
    "t1": {"name": "失踪货主", "status": "open", "last_touched": 1}
  }
}
```

## Candidate Changes

Add these entries to a delta created by `nml.py prepare`:

```json
{
  "character_changes": [
    {"id": "captain", "field": "location", "from": "码头", "to": "船上", "evidence": "chapters/002.md#登船"}
  ],
  "prop_changes": [
    {"id": "ledger", "from_holder": "captain", "to_holder": "mate", "condition": "封口完整", "evidence": "chapters/002.md#交接"}
  ],
  "knowledge_changes": [
    {"fact": "f1", "who": "captain", "from": "unknown", "to": "suspects", "how": "摸到纸层", "evidence": "chapters/002.md#纸边"}
  ],
  "thread_changes": [
    {"id": "t1", "action": "advance", "evidence": "chapters/002.md#货主名字"}
  ],
  "promise_open": [
    {"id": "p2", "text": "夹层写了什么", "due": "next", "evidence": "chapters/002.md#末段"}
  ]
}
```

The holder `mate` must be created in `new_entities.characters` or already be in approved state before promotion. Do not use `new_canon_requests` for a change that has already been approved; unresolved requests intentionally block promotion.

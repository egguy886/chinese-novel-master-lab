#!/usr/bin/env python3
"""Small, dependency-free continuity ledger, chapter final check, and cross-volume series auditor
for Chinese Novel Master Lab (supporting both Chinese `--lang zh` and English `--lang en` fiction).

The ledger validates structured state transitions. The final check reports mechanical,
tense-drift, quote, cliché-density, and continuity defects in one chapter or across volumes.
Neither mutates manuscript prose.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = SKILL_ROOT / "templates"
LEDGER_DIR = ".novel-master-lab"
LEVEL_ORDER = {"unknown": 0, "suspects": 1, "knows": 2}
SOURCE_STATUSES = {"active", "candidate", "stale", "mixed"}
ENTITY_KINDS = ("characters", "locations", "relationships", "props", "knowledge", "threads")
CHARACTER_FIELDS = {"name", "location", "condition", "resources", "aim", "voice", "status"}
RELATIONSHIP_FIELDS = {"trust", "debt", "power", "boundary", "promise"}
SUPPORTED_LANGS = {"zh", "en", "auto"}
SUPPORTED_QUOTES = {
    "cn_curly", "corner", "en_double", "en_straight", "en_curly", "en_single", "none"
}
SUPPORTED_TENSE_MODES = {"off", "auto", "present", "past"}


class InputError(Exception):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputError(f"Cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise InputError(f"Expected JSON object in {path}")
    return value


def json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise InputError(f"Cannot read {path}: {exc}") from exc


def project_path(project: Path, value: str) -> Path:
    if not isinstance(value, str) or not value:
        raise InputError("Expected a nonempty project-relative path")
    path = (project / value).resolve()
    try:
        path.relative_to(project.resolve())
    except ValueError as exc:
        raise InputError(f"Path leaves project root: {value}") from exc
    return path


def relative_path(project: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(project.resolve()).as_posix()
    except ValueError as exc:
        raise InputError(f"Chapter must be inside project root: {path}") from exc


def known_holder(value: Any, state: dict[str, Any]) -> bool:
    return isinstance(value, str) and (
        value in state["characters"]
        or value in state["locations"]
        or value in {"unknown", "lost", "consumed"}
    )


def infer_chapter_number(path: Path) -> int | None:
    m = re.search(r"(?:ch(?:apter)?[-_\s]*)?(\d{1,4})", path.stem, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _term_occurs(text: str, term: str) -> bool:
    if re.match(r"^[A-Za-z0-9 .'-]+$", term):
        pat = rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])"
        return bool(re.search(pat, text))
    return term in text


def scan_retired_names(prose: str, state: dict[str, Any], issues: list[tuple[str, str]]) -> None:
    active: set[str] = set()
    retired = [name for name in state.get("retired_names", []) if isinstance(name, str) and name]
    for character in state["characters"].values():
        aliases = character.get("aliases", [])
        deprecated = character.get("deprecated_names", [])
        if not isinstance(aliases, list) or not isinstance(deprecated, list):
            record(issues, "ERROR", "Character aliases and deprecated_names must be arrays")
            continue
        for name in [character.get("name"), *aliases]:
            if isinstance(name, str) and name:
                active.add(name)
        retired.extend(
            name for name in deprecated if isinstance(name, str) and name
        )
    masked = prose
    for name in sorted(active, key=len, reverse=True):
        masked = masked.replace(name, " " * len(name))
    for name in sorted(set(retired)):
        if _term_occurs(masked, name):
            record(issues, "WARN", f"[names] retired or deprecated name may appear in prose: {name}")


def scan_state_continuity_rules(
    prose: str,
    lines: list[tuple[int, str]],
    state: dict[str, Any],
    chapter_num: int | None,
    lang: str,
    issues: list[tuple[str, str]],
) -> None:
    """Scan optional continuity_rules and persona_locks from state.json against chapter prose."""
    narration = mask_dialogue(prose, lang)

    for idx, rule in enumerate(state.get("continuity_rules", [])):
        if not isinstance(rule, dict):
            continue
        c_start = rule.get("chapter_start")
        c_end = rule.get("chapter_end")
        if chapter_num is not None:
            if isinstance(c_start, int) and chapter_num < c_start:
                continue
            if isinstance(c_end, int) and chapter_num > c_end:
                continue
        pattern = rule.get("forbidden_regex") or rule.get("term")
        if not isinstance(pattern, str) or not pattern:
            continue
        is_regex = bool(rule.get("forbidden_regex") or rule.get("regex"))
        flags = re.IGNORECASE if rule.get("ignore_case") else 0
        rx = re.compile(pattern if is_regex else re.escape(pattern), flags)
        where = rule.get("where", "any")
        target = narration if where == "narration" else prose
        if rx.search(target):
            lineno = next(
                (n for n, s in lines if rx.search(mask_dialogue(s, lang) if where == "narration" else s)),
                0,
            )
            severity = rule.get("severity", "ERROR")
            label = rule.get("id") or rule.get("label") or f"continuity_rules[{idx}]"
            note = f" ({rule['note']})" if rule.get("note") else ""
            record(issues, severity, f"[continuity] L{lineno}: rule '{label}' matched{note}")

    for idx, lock in enumerate(state.get("persona_locks", [])):
        if not isinstance(lock, dict):
            continue
        until_ch = lock.get("isolated_until_chapter")
        if chapter_num is not None and isinstance(until_ch, int) and chapter_num > until_ch:
            continue
        patterns = lock.get("forbidden_patterns", [])
        if not isinstance(patterns, list):
            continue
        for pat in patterns:
            if not isinstance(pat, str) or not pat:
                continue
            rx = re.compile(pat, re.MULTILINE)
            if rx.search(prose):
                lineno = next((n for n, s in lines if rx.search(s)), 0)
                severity = lock.get("severity", "ERROR")
                lid = lock.get("id") or f"persona_locks[{idx}]"
                note = f" ({lock['note']})" if lock.get("note") else ""
                record(
                    issues,
                    severity,
                    f"[persona] L{lineno}: premature identity leak for '{lid}' before chapter {until_ch}{note}",
                )


def ledger_paths(project: Path) -> tuple[Path, Path, Path]:
    ledger = project / LEDGER_DIR
    return ledger, ledger / "state.json", ledger / "sources.json"


def exclusive_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8") as stream:
            stream.write(source.read_text(encoding="utf-8"))
    except FileExistsError as exc:
        raise InputError(f"Refusing to overwrite {target}") from exc


def exclusive_json(target: Path, value: dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("xb") as stream:
            stream.write(json_bytes(value))
    except FileExistsError as exc:
        raise InputError(f"Refusing to overwrite {target}") from exc


def atomic_json(target: Path, value: dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=".nml-", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(json_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def command_init(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    if not project.is_dir():
        raise InputError(f"Project directory does not exist: {project}")
    ledger, state_path, sources_path = ledger_paths(project)
    if state_path.exists() or sources_path.exists():
        raise InputError(f"Ledger already exists in {ledger}; no files were overwritten")
    exclusive_copy(TEMPLATES / "state.json", state_path)
    exclusive_copy(TEMPLATES / "sources.json", sources_path)
    for name in ("deltas", "approvals", "backups"):
        (ledger / name).mkdir(exist_ok=True)
    if args.new_project:
        for source in sorted((TEMPLATES / "new-project").glob("*.md")):
            target = project / source.name
            if not target.exists():
                exclusive_copy(source, target)
    print(f"Initialized {ledger}")
    return 0


def command_prepare(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    ledger, state_path, _ = ledger_paths(project)
    state = load_json(state_path)
    issues: list[tuple[str, str]] = []
    validate_state(state, issues)
    if issues:
        raise InputError("Invalid state: " + "; ".join(message for _, message in issues))
    chapter = int(args.chapter)
    if chapter != state.get("as_of_chapter", -1) + 1:
        raise InputError("Only the next continuation chapter can use prepare")
    chapter_path = Path(args.chapter_file).expanduser()
    if not chapter_path.is_absolute():
        chapter_path = project / chapter_path
    chapter_path = chapter_path.resolve()
    if not chapter_path.is_file():
        raise InputError(f"Chapter file does not exist: {chapter_path}")
    delta = load_json(TEMPLATES / "delta.json")
    delta.update(
        chapter=chapter,
        chapter_file=relative_path(project, chapter_path),
        chapter_sha256=sha256_file(chapter_path),
        state_sha256=sha256_file(state_path),
        story_day=state.get("story_day", 0),
    )
    target = ledger / "deltas" / f"ch-{chapter:03d}.json"
    exclusive_json(target, delta)
    print(f"Prepared candidate delta: {target}")
    return 0


def record(issues: list[tuple[str, str]], severity: str, message: str) -> None:
    issues.append((severity, message))


def require_evidence(entry: dict[str, Any], label: str, issues: list[tuple[str, str]]) -> None:
    if not isinstance(entry.get("evidence"), str) or not entry["evidence"].strip():
        record(issues, "ERROR", f"{label} needs a chapter evidence locator")


def validate_sources(project: Path, sources: dict[str, Any], issues: list[tuple[str, str]]) -> None:
    if sources.get("schema_version") != 1 or not isinstance(sources.get("sources"), list):
        record(issues, "ERROR", "sources.json must use schema_version 1 and a sources array")
        return
    seen: set[str] = set()
    for index, entry in enumerate(sources["sources"]):
        label = f"source[{index}]"
        if not isinstance(entry, dict):
            record(issues, "ERROR", f"{label} must be an object")
            continue
        source_id = entry.get("id")
        if not isinstance(source_id, str) or not source_id.strip() or source_id in seen:
            record(issues, "ERROR", f"{label} needs a unique id")
        else:
            seen.add(source_id)
        status = entry.get("status")
        if not isinstance(status, str) or status not in SOURCE_STATUSES:
            record(issues, "ERROR", f"{label} has invalid status {status!r}")
        declared = entry.get("declared_through")
        latest = entry.get("latest_entry_chapter")
        if (isinstance(declared, int) and isinstance(latest, int)
                and latest > declared and status != "mixed"):
            record(issues, "ERROR", f"{label} has later entries than its declared coverage; mark mixed")
        start, end = entry.get("chapter_start"), entry.get("chapter_end")
        if isinstance(start, int) and isinstance(end, int) and end < start:
            record(issues, "ERROR", f"{label} chapter_end precedes chapter_start")
        try:
            path = project_path(project, entry.get("path"))
        except InputError as exc:
            record(issues, "ERROR", f"{label}: {exc}")
            continue
        if not path.is_file():
            severity = "ERROR" if status == "active" else "WARN"
            record(issues, severity, f"{label} path is not currently readable: {entry['path']}")
        elif (isinstance(entry.get("sha256"), str) and entry["sha256"]
              and sha256_file(path) != entry["sha256"]):
            severity = "ERROR" if status == "active" else "WARN"
            record(issues, severity, f"{label} content changed after source verification")


def validate_state(state: dict[str, Any], issues: list[tuple[str, str]]) -> None:
    if state.get("schema_version") != 1:
        record(issues, "ERROR", "state.json needs schema_version 1")
    if not isinstance(state.get("as_of_chapter"), int) or state["as_of_chapter"] < 0:
        record(issues, "ERROR", "state.json needs nonnegative as_of_chapter")
    if not isinstance(state.get("story_day"), int) or state["story_day"] < 0:
        record(issues, "ERROR", "state.json needs nonnegative story_day")
    for kind in (*ENTITY_KINDS, "promises"):
        if not isinstance(state.get(kind), dict):
            record(issues, "ERROR", f"state.json {kind} must be an object")
        elif any(not isinstance(entry, dict) for entry in state[kind].values()):
            record(issues, "ERROR", f"state.json {kind} entries must be objects")
    if not isinstance(state.get("retired_names"), list):
        record(issues, "ERROR", "state.json retired_names must be an array")
    if "continuity_rules" in state and not isinstance(state["continuity_rules"], list):
        record(issues, "ERROR", "state.json continuity_rules must be an array")
    if "persona_locks" in state and not isinstance(state["persona_locks"], list):
        record(issues, "ERROR", "state.json persona_locks must be an array")


def apply_new_entities(
    state: dict[str, Any], delta: dict[str, Any], issues: list[tuple[str, str]]
) -> None:
    groups = delta.get("new_entities")
    if not isinstance(groups, dict):
        record(issues, "ERROR", "delta new_entities must be an object")
        return
    for kind in ENTITY_KINDS:
        entries = groups.get(kind, {})
        if not isinstance(entries, dict):
            record(issues, "ERROR", f"new_entities.{kind} must be an object")
            continue
        for entity_id, entry in entries.items():
            label = f"new_entities.{kind}.{entity_id}"
            if not isinstance(entry, dict):
                record(issues, "ERROR", f"{label} must be an object")
                continue
            require_evidence(entry, label, issues)
            if entity_id in state[kind]:
                record(issues, "ERROR", f"{label} already exists in approved state")
                continue
            if kind in {"characters", "locations", "props", "threads"} and not entry.get("name"):
                record(issues, "ERROR", f"{label} needs a name")
            if kind == "knowledge" and not entry.get("statement"):
                record(issues, "ERROR", f"{label} needs a statement")
            if kind == "props" and "holder" not in entry:
                record(issues, "ERROR", f"{label} needs a holder")
            if kind == "props" and "holder" in entry and not known_holder(entry["holder"], state):
                record(issues, "ERROR", f"{label} has unknown holder {entry['holder']!r}")
            if kind == "relationships":
                members = entry.get("members")
                if (not isinstance(members, list) or len(members) != 2
                        or any(not isinstance(member, str) or member not in state["characters"] for member in members)):
                    record(issues, "ERROR", f"{label} needs two known character members")
            if kind == "knowledge" and not isinstance(entry.get("people", {}), dict):
                record(issues, "ERROR", f"{label} people must be an object")
            elif kind == "knowledge":
                people = entry.setdefault("people", {})
                for who, level_record in people.items():
                    if (who not in state["characters"] or not isinstance(level_record, dict)
                            or not isinstance(level_record.get("level"), str)
                            or level_record["level"] not in {"suspects", "knows"}):
                        record(issues, "ERROR", f"{label} has invalid initial knower {who!r}")
            if kind == "threads" and entry.get("status", "open") != "open":
                record(issues, "ERROR", f"{label} must begin open")
            elif kind == "threads":
                entry.setdefault("status", "open")
                entry.setdefault("last_touched", delta["chapter"])
            state[kind][entity_id] = copy.deepcopy(entry)


def apply_field_changes(
    state: dict[str, Any], delta: dict[str, Any], kind: str, allowed: set[str],
    issues: list[tuple[str, str]],
) -> None:
    key = "character_changes" if kind == "characters" else "relationship_changes"
    changes = delta.get(key, [])
    if not isinstance(changes, list):
        record(issues, "ERROR", f"{key} must be an array")
        return
    for index, change in enumerate(changes):
        label = f"{key}[{index}]"
        if not isinstance(change, dict):
            record(issues, "ERROR", f"{label} must be an object")
            continue
        require_evidence(change, label, issues)
        entity_id, field = change.get("id"), change.get("field")
        if (not isinstance(entity_id, str) or not isinstance(field, str)
                or entity_id not in state[kind] or field not in allowed):
            record(issues, "ERROR", f"{label} has unknown entity or field")
            continue
        current = state[kind][entity_id].get(field)
        if current != change.get("from") or "to" not in change:
            record(issues, "ERROR", f"{label} from value does not match approved state")
            continue
        state[kind][entity_id][field] = change["to"]


def apply_prop_changes(state: dict[str, Any], delta: dict[str, Any], issues: list[tuple[str, str]]) -> None:
    changes = delta.get("prop_changes", [])
    if not isinstance(changes, list):
        record(issues, "ERROR", "prop_changes must be an array")
        return
    for index, change in enumerate(changes):
        label = f"prop_changes[{index}]"
        if not isinstance(change, dict):
            record(issues, "ERROR", f"{label} must be an object")
            continue
        require_evidence(change, label, issues)
        prop_id = change.get("id")
        prop = state["props"].get(prop_id) if isinstance(prop_id, str) else None
        if not isinstance(prop, dict):
            record(issues, "ERROR", f"{label} uses an unknown prop")
            continue
        if prop.get("holder") != change.get("from_holder") or "to_holder" not in change:
            record(issues, "ERROR", f"{label} holder does not match approved state")
            continue
        holder = change["to_holder"]
        if not known_holder(holder, state):
            record(issues, "ERROR", f"{label} has unknown holder {holder!r}")
            continue
        prop["holder"] = change["to_holder"]
        if "condition" in change:
            prop["condition"] = change["condition"]


def apply_knowledge_changes(
    state: dict[str, Any], delta: dict[str, Any], issues: list[tuple[str, str]]
) -> None:
    changes = delta.get("knowledge_changes", [])
    if not isinstance(changes, list):
        record(issues, "ERROR", "knowledge_changes must be an array")
        return
    for index, change in enumerate(changes):
        label = f"knowledge_changes[{index}]"
        if not isinstance(change, dict):
            record(issues, "ERROR", f"{label} must be an object")
            continue
        require_evidence(change, label, issues)
        fact_id = change.get("fact")
        fact = state["knowledge"].get(fact_id) if isinstance(fact_id, str) else None
        who = change.get("who")
        if not isinstance(fact, dict) or not isinstance(who, str) or who not in state["characters"]:
            record(issues, "ERROR", f"{label} uses an unknown fact or character")
            continue
        people = fact.setdefault("people", {})
        if not isinstance(people, dict) or not isinstance(people.get(who, {}), dict):
            record(issues, "ERROR", f"{label} has malformed approved knowledge")
            continue
        current = people.get(who, {}).get("level", "unknown")
        target = change.get("to")
        if change.get("from") != current or not isinstance(target, str) or target not in LEVEL_ORDER:
            record(issues, "ERROR", f"{label} level does not match approved state")
            continue
        if LEVEL_ORDER[target] <= LEVEL_ORDER[current]:
            record(issues, "ERROR", f"{label} knowledge cannot regress or repeat")
            continue
        if not isinstance(change.get("how"), str) or not change["how"].strip():
            record(issues, "ERROR", f"{label} needs how the character learned it")
            continue
        people[who] = {"level": target, "how": change["how"], "chapter": delta["chapter"]}


def apply_thread_changes(state: dict[str, Any], delta: dict[str, Any], issues: list[tuple[str, str]]) -> None:
    changes = delta.get("thread_changes", [])
    if not isinstance(changes, list):
        record(issues, "ERROR", "thread_changes must be an array")
        return
    for index, change in enumerate(changes):
        label = f"thread_changes[{index}]"
        if not isinstance(change, dict):
            record(issues, "ERROR", f"{label} must be an object")
            continue
        require_evidence(change, label, issues)
        thread_id = change.get("id")
        thread = state["threads"].get(thread_id) if isinstance(thread_id, str) else None
        action = change.get("action")
        if not isinstance(thread, dict) or not isinstance(action, str) or action not in {"advance", "resolve"}:
            record(issues, "ERROR", f"{label} has unknown thread or action")
            continue
        if thread.get("status") == "resolved":
            record(issues, "ERROR", f"{label} cannot touch a resolved thread")
            continue
        thread["status"] = "advanced" if action == "advance" else "resolved"
        thread["last_touched"] = delta["chapter"]


def apply_promises(state: dict[str, Any], delta: dict[str, Any], issues: list[tuple[str, str]]) -> None:
    opens, payoffs = delta.get("promise_open", []), delta.get("promise_payoff", [])
    if not isinstance(opens, list) or not isinstance(payoffs, list):
        record(issues, "ERROR", "promise_open and promise_payoff must be arrays")
        return
    paid: set[str] = set()
    for index, entry in enumerate(payoffs):
        label = f"promise_payoff[{index}]"
        if not isinstance(entry, dict):
            record(issues, "ERROR", f"{label} must be an object")
            continue
        require_evidence(entry, label, issues)
        promise_id = entry.get("id")
        promise = state["promises"].get(promise_id) if isinstance(promise_id, str) else None
        if not isinstance(promise, dict) or promise.get("status") != "open":
            record(issues, "ERROR", f"{label} references no open promise")
            continue
        promise["status"] = "paid"
        promise["paid_in"] = delta["chapter"]
        paid.add(promise_id)
    for promise_id, promise in state["promises"].items():
        if (promise.get("due") == "next" and promise.get("chapter") == delta["chapter"] - 1
                and promise_id not in paid):
            record(issues, "WARN", f"next-chapter promise {promise_id} has no recorded payoff")
    for index, entry in enumerate(opens):
        label = f"promise_open[{index}]"
        if not isinstance(entry, dict):
            record(issues, "ERROR", f"{label} must be an object")
            continue
        require_evidence(entry, label, issues)
        promise_id = entry.get("id")
        if not isinstance(promise_id, str) or not promise_id or promise_id in state["promises"]:
            record(issues, "ERROR", f"{label} needs a unique id")
            continue
        if (not entry.get("text") or not isinstance(entry.get("due"), str)
                or entry["due"] not in {"next", "later"}):
            record(issues, "ERROR", f"{label} needs text and due=next/later")
            continue
        state["promises"][promise_id] = {
            "chapter": delta["chapter"], "text": entry["text"],
            "due": entry["due"], "status": "open", "evidence": entry["evidence"],
        }


def validate_delta(
    project: Path, state_path: Path, state: dict[str, Any], delta: dict[str, Any],
    issues: list[tuple[str, str]],
) -> dict[str, Any]:
    updated = copy.deepcopy(state)
    if delta.get("schema_version") != 1 or delta.get("mode") != "continue":
        record(issues, "ERROR", "Only schema_version 1 continuation deltas are supported")
    if delta.get("status") != "candidate":
        record(issues, "ERROR", "Delta must remain candidate until approval receipt exists")
    chapter = delta.get("chapter")
    if not isinstance(chapter, int) or chapter != state.get("as_of_chapter", -2) + 1:
        record(issues, "ERROR", "Delta chapter must immediately follow approved state")
        return updated
    if delta.get("state_sha256") != sha256_file(state_path):
        record(issues, "ERROR", "State changed after delta preparation; rebuild candidate")
    try:
        chapter_path = project_path(project, delta.get("chapter_file"))
        if not chapter_path.is_file() or delta.get("chapter_sha256") != sha256_file(chapter_path):
            record(issues, "ERROR", "Chapter missing or changed after delta preparation")
        else:
            prose = chapter_path.read_text(encoding="utf-8")
            lines, body = chapter_body(prose)
            lang = detect_language(body, state.get("lang", "auto"))
            scan_retired_names(prose, state, issues)
            scan_state_continuity_rules(body, lines, state, chapter, lang, issues)
    except (InputError, OSError) as exc:
        record(issues, "ERROR", f"Invalid chapter path: {exc}")
    day = delta.get("story_day")
    if not isinstance(day, int) or day < 0:
        record(issues, "ERROR", "story_day must be a nonnegative integer")
    elif day < state.get("story_day", 0) and delta.get("flashback") is not True:
        record(issues, "ERROR", "story_day moved backwards without flashback=true")
    if not isinstance(delta.get("summary"), str) or not delta["summary"].strip():
        record(issues, "WARN", "Candidate summary is empty")
    apply_new_entities(updated, delta, issues)
    apply_field_changes(updated, delta, "characters", CHARACTER_FIELDS, issues)
    apply_field_changes(updated, delta, "relationships", RELATIONSHIP_FIELDS, issues)
    apply_prop_changes(updated, delta, issues)
    apply_knowledge_changes(updated, delta, issues)
    apply_thread_changes(updated, delta, issues)
    apply_promises(updated, delta, issues)
    for thread_id, thread in updated["threads"].items():
        if thread.get("status") == "resolved":
            continue
        payoff_by = thread.get("payoff_by")
        max_gap = thread.get("max_gap")
        last_touched = thread.get("last_touched")
        if isinstance(payoff_by, int) and chapter > payoff_by:
            record(issues, "WARN", f"thread {thread_id} passed payoff_by chapter {payoff_by}")
        if isinstance(max_gap, int) and isinstance(last_touched, int) and chapter - last_touched > max_gap:
            record(issues, "WARN", f"thread {thread_id} exceeded max_gap {max_gap}")
    requests = delta.get("new_canon_requests", [])
    if not isinstance(requests, list):
        record(issues, "ERROR", "new_canon_requests must be an array")
    elif requests:
        record(issues, "WARN", "Unresolved new_canon_requests prevent promotion")
    updated["as_of_chapter"] = chapter
    if isinstance(day, int) and delta.get("flashback") is not True:
        updated["story_day"] = day
    return updated


def run_checks(project: Path, delta_path: Path | None) -> tuple[list[tuple[str, str]], dict[str, Any] | None]:
    _, state_path, sources_path = ledger_paths(project)
    state = load_json(state_path)
    sources = load_json(sources_path)
    issues: list[tuple[str, str]] = []
    validate_state(state, issues)
    validate_sources(project, sources, issues)
    if any(severity == "ERROR" for severity, _ in issues):
        return issues, None
    updated = None
    if delta_path is not None:
        delta = load_json(delta_path)
        updated = validate_delta(project, state_path, state, delta, issues)
    return issues, updated


def show_issues(issues: list[tuple[str, str]]) -> None:
    for severity, message in issues:
        print(f"{severity}: {message}")
    errors = sum(severity == "ERROR" for severity, _ in issues)
    warnings = sum(severity == "WARN" for severity, _ in issues)
    print(f"Check complete: {errors} error(s), {warnings} warning(s)")


def command_check(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    delta_path = Path(args.delta).expanduser().resolve() if args.delta else None
    issues, _ = run_checks(project, delta_path)
    show_issues(issues)
    return 1 if any(severity == "ERROR" for severity, _ in issues) else 0


# ---------- Final check (终检: Chinese & English modes) ----------

FINAL_CHECK_CONFIG = "final-check.json"

ZH_FINAL_CHECK_DEFAULTS: dict[str, Any] = {
    "lang": "zh",
    "quotes": "cn_curly",
    "cjk_leak_check": False,
    "tense": {"mode": "off", "min_ratio": 0.80, "paragraph_slip": False, "flashback_chapters": []},
    "length": {"min": None, "max": None, "tolerance": 0.15},
    "banned": [
        {"term": "极其"}, {"term": "极度"}, {"term": "宛如"}, {"term": "简直"},
        {"term": "仿佛", "where": "narration"}, {"term": "毫无疑问"}, {"term": "分外"},
        {"term": "赫然"}, {"term": "悄然"}, {"term": "蓦然"}, {"term": "不禁"},
        {"term": "不由得"}, {"term": "殊不知"}, {"term": "浑然不觉"},
        {"term": "不仅[^。！？\\n]{0,40}更是", "regex": True, "label": "不仅……更是……"},
        {"term": "闪过一丝", "note": "人脸不是调色盘"},
        {"term": "嘴角[^。！？\\n]{0,8}勾起", "regex": True, "label": "嘴角勾起", "max": 1, "window": 50},
        {"term": "空气中弥漫着"}, {"term": "不易察觉"},
    ],
    "extra_banned": [],
    "disable_banned": [],
    "ending_window_paragraphs": 2,
    "ending_patterns": [
        "这不仅是", "一切才刚刚开始", "这只是开始", "从此[^。！？]{0,12}(?:不同|改变|再也)",
        "命运的齿轮", "他(?:们)?不知道的是", "她(?:们)?不知道的是", "殊不知", "未完待续",
    ],
    "meta_patterns": [
        "本章", "伏笔", "钩子", "细纲", "章纲", "作者有话说", "下章预告", "TODO", "候选稿",
        "^\\s*[-*+]\\s+\\S", "^\\s*\\|", "【[^】]{0,12}】",
    ],
    "lost_quote_pattern": "[他她我你][^。！？”]{0,6}[说道问喊][：:](?!\\s*“)",
    "landing_chars": 300,
    "opening_chars": 400,
    "landing_words": 120,
    "opening_words": 160,
}

EN_FINAL_CHECK_DEFAULTS: dict[str, Any] = {
    "lang": "en",
    "quotes": "en_double",
    "cjk_leak_check": True,
    "tense": {"mode": "auto", "min_ratio": 0.80, "paragraph_slip": True, "flashback_chapters": []},
    "length": {"min": None, "max": None, "tolerance": 0.15},
    "banned": [
        {
            "term": r"\b(?:let|lets|letting|released|releases)\s+out\s+a\s+breath\s+(?:I|she|he|we|they)\s+(?:didn['’]t|did\s+not|hadn['’]t)\s+know\b",
            "regex": True,
            "where": "narration",
            "max": 0,
            "severity": "ERROR",
            "label": "breath I didn't know I was holding",
            "note": "overused Western romance/YA stock cliché",
        },
        {
            "term": r"\ba\s+testament\s+to\b",
            "regex": True,
            "where": "narration",
            "max": 0,
            "severity": "ERROR",
            "label": "a testament to",
            "note": "AI stock transitional phrase",
        },
        {
            "term": r"\bunbeknownst\s+to\b",
            "regex": True,
            "where": "narration",
            "max": 0,
            "severity": "ERROR",
            "label": "unbeknownst to",
            "note": "omniscient intrusion / stock phrase",
        },
        {
            "term": r"\blittle\s+did\s+(?:I|he|she|we|they)\s+know\b",
            "regex": True,
            "where": "narration",
            "max": 0,
            "severity": "ERROR",
            "label": "little did X know",
            "note": "retrospective spoiler cliché",
        },
        {
            "term": r"\bministrations\b",
            "regex": True,
            "where": "narration",
            "max": 0,
            "severity": "ERROR",
            "label": "ministrations",
            "note": "dated fanfiction purple prose",
        },
        {
            "term": r"\b(?:blue|brown|dark|green|grey|gray|amber|emerald|sapphire|icy|piercing|glowing)\s+orbs\b",
            "regex": True,
            "where": "narration",
            "max": 0,
            "severity": "ERROR",
            "label": "color orbs",
            "note": "say eyes/irises/gaze, never orbs",
        },
        {
            "term": r"\bcouldn['’]t\s+help\s+but\b",
            "regex": True,
            "where": "narration",
            "max": 1,
            "window": 5,
            "severity": "WARN",
            "label": "couldn't help but",
            "note": "filter-verb padding; show the action directly",
        },
        {
            "term": r"\b(?:trapped\s+bird|bird\s+trapped\s+in)\b",
            "regex": True,
            "where": "narration",
            "max": 1,
            "window": 25,
            "severity": "WARN",
            "label": "trapped bird",
            "note": "repetitive pulse/heartbeat simile across chapters",
        },
        {
            "term": r"\bapex\s+predator\b",
            "regex": True,
            "where": "narration",
            "max": 2,
            "window": 15,
            "severity": "WARN",
            "label": "apex predator",
            "note": "repetitive alpha-hero stock label",
        },
        {
            "term": r"\bshivers?\s+(?:down|up)\s+(?:my|her|his)\s+spine\b",
            "regex": True,
            "where": "narration",
            "max": 1,
            "window": 10,
            "severity": "WARN",
            "label": "shiver down spine",
        },
        {
            "term": r"\bknuckles\s+turn(?:ed|s|ing)?\s+(?:bone-)?white\b",
            "regex": True,
            "where": "narration",
            "max": 2,
            "window": 10,
            "severity": "WARN",
            "label": "knuckles turn white",
        },
    ],
    "extra_banned": [],
    "disable_banned": [],
    "ending_window_paragraphs": 2,
    "ending_patterns": [
        r"(?i)\blittle\s+did\s+(?:I|he|she|we|they)\s+know\b",
        r"(?i)\beverything\s+was\s+about\s+to\s+change\b",
        r"(?i)\bnothing\s+would\s+ever\s+be\s+the\s+same\b",
        r"(?i)\bthis\s+was\s+(?:only|just)\s+the\s+beginning\b",
        r"(?i)\bthe\s+game\s+had\s+(?:only\s+)?just\s+begun\b",
        r"(?i)\bto\s+be\s+continued\b",
    ],
    "meta_patterns": [
        r"(?i)\b(?:in|since|from|back\s+in|see)\s+chapter\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|[a-z]+-[a-z]+)\b",
        r"\bTODO\b",
        r"\bFIXME\b",
        r"(?i)\[insert\s+",
        r"(?i)^author['’]s\s+note\b",
        r"^\s*[-*+]\s+\S",
        r"^\s*\|.*\|",
    ],
    "lost_quote_pattern": "",
    "landing_chars": 300,
    "opening_chars": 400,
    "landing_words": 120,
    "opening_words": 160,
}

ALLOWED_FINAL_CONFIG_KEYS = set(ZH_FINAL_CHECK_DEFAULTS.keys())

HEADING_RE = re.compile(
    r"^\s*(?:#+\s|第\s*[\d一二三四五六七八九十百千零两]+\s*[章回]|chapter\s+(?:\d+|[a-z-]+)\b|prologue\b|epilogue\b)",
    re.IGNORECASE,
)


def detect_language(text: str, requested: str | None) -> str:
    lang = (requested or "zh").lower()
    if lang not in SUPPORTED_LANGS:
        raise InputError(f"Unsupported language {requested!r}; use zh, en, or auto")
    if lang != "auto":
        return lang
    han = han_count(text)
    en_w = en_word_count(text)
    return "en" if en_w > han * 2 and en_w >= 10 else "zh"


def load_final_config(
    project: Path | None,
    config: Path | None,
    cli_lang: str | None = None,
    sample_text: str = "",
) -> dict[str, Any]:
    candidates: list[tuple[Path, dict[str, Any]]] = []
    if project is not None:
        p_cfg = project / LEDGER_DIR / FINAL_CHECK_CONFIG
        if p_cfg.is_file():
            candidates.append((p_cfg, load_json(p_cfg)))
    if config is not None:
        if not config.is_file():
            raise InputError(f"Final-check config does not exist: {config}")
        candidates.append((config, load_json(config)))

    for path, override in candidates:
        for key in override:
            if key not in ALLOWED_FINAL_CONFIG_KEYS:
                raise InputError(f"Unknown final-check config key {key!r} in {path}")

    # Determine effective language: CLI > config > default "zh"
    raw_lang = cli_lang
    if not raw_lang:
        for _, override in candidates:
            if "lang" in override:
                raw_lang = str(override["lang"])
    resolved_lang = detect_language(sample_text, raw_lang or "zh")

    base = EN_FINAL_CHECK_DEFAULTS if resolved_lang == "en" else ZH_FINAL_CHECK_DEFAULTS
    merged = copy.deepcopy(base)
    merged["lang"] = resolved_lang

    for _, override in candidates:
        for key, value in override.items():
            if key == "length":
                if not isinstance(value, dict):
                    raise InputError("final-check length must be an object")
                merged["length"].update(value)
            elif key == "tense":
                if isinstance(value, str):
                    merged["tense"]["mode"] = value
                elif isinstance(value, dict):
                    merged["tense"].update(value)
                else:
                    raise InputError("final-check tense must be a string or object")
            elif key == "lang":
                if not cli_lang:
                    merged["lang"] = detect_language(sample_text, str(value))
            else:
                merged[key] = value
    return merged


def chapter_body(text: str) -> tuple[list[tuple[int, str]], str]:
    lines = text.replace("\r\n", "\n").split("\n")
    start = 0
    for index, line in enumerate(lines):
        if line.strip():
            start = index + 1 if HEADING_RE.match(line) else index
            break
    numbered = [(start + i + 1, line) for i, line in enumerate(lines[start:]) if line.strip()]
    return numbered, "\n".join(lines[start:])


def han_count(text: str) -> int:
    return len(re.findall(r"[㐀-鿿]", text))


def en_word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z]+(?:['’][A-Za-z]+)?|\d+(?:[.,]\d+)?", text))


def mask_dialogue(text: str, lang: str = "zh") -> str:
    masked = re.sub(r"“[^”]*”", lambda m: " " * len(m.group(0)), text)
    if lang == "en":
        masked = re.sub(r'"[^"\n]*"', lambda m: " " * len(m.group(0)), masked)
    return masked


def _check_straight_quotes(lines: list[tuple[int, str]], issues: list[tuple[str, str]]) -> None:
    in_epistolary = False
    for index, (lineno, line) in enumerate(lines):
        stripped = line.strip()
        count = line.count('"')
        if in_epistolary:
            if not (stripped.startswith("*") or stripped.startswith(">")):
                record(issues, "ERROR", f"[quotes] L{lineno}: multi-line italicized/block quote was not closed")
                in_epistolary = False
            elif count % 2 == 1:
                in_epistolary = False
                continue
            else:
                continue
        if count % 2 == 1:
            following = lines[index + 1][1].lstrip() if index + 1 < len(lines) else ""
            if stripped.startswith('"') and following.startswith('"'):
                continue
            if (stripped.startswith('*"') or stripped.startswith("> ")) and (following.startswith("*") or following.startswith(">")):
                in_epistolary = True
                continue
            record(issues, "ERROR", f"[quotes] L{lineno}: quote is not closed in this paragraph")


def _check_paired_quotes(
    lines: list[tuple[int, str]],
    open_q: str,
    close_q: str,
    issues: list[tuple[str, str]],
    allow_epistolary: bool = False,
) -> None:
    epistolary_depth = 0
    for index, (lineno, line) in enumerate(lines):
        stripped = line.strip()
        if epistolary_depth and allow_epistolary:
            if not (stripped.startswith("*") or stripped.startswith(">")):
                record(issues, "ERROR", f"[quotes] L{lineno}: multi-line italicized/block quote was not closed")
                epistolary_depth = 0
        depth = epistolary_depth
        for char in line:
            if char == open_q:
                if depth:
                    record(issues, "ERROR", f"[quotes] L{lineno}: a quote opens before the previous one closes")
                depth = 1
            elif char == close_q:
                if not depth:
                    record(issues, "ERROR", f"[quotes] L{lineno}: closing quote without an opening quote")
                depth = 0
        if depth:
            following = lines[index + 1][1].lstrip() if index + 1 < len(lines) else ""
            if following.startswith(open_q):
                epistolary_depth = 0
                continue
            if allow_epistolary and (epistolary_depth or stripped.startswith(f"*{open_q}") or stripped.startswith(">")) and (following.startswith("*") or following.startswith(">")):
                epistolary_depth = 1
                continue
            epistolary_depth = 0
            record(issues, "ERROR", f"[quotes] L{lineno}: quote is not closed in this paragraph")
        else:
            epistolary_depth = 0


def final_quotes(lines: list[tuple[int, str]], cfg: dict[str, Any], issues: list[tuple[str, str]]) -> None:
    mode = cfg["quotes"]
    if mode == "none":
        return
    if mode not in SUPPORTED_QUOTES:
        raise InputError(f"Unsupported quotes mode {mode!r}; use one of {sorted(SUPPORTED_QUOTES)}")

    if mode in {"cn_curly", "corner"}:
        open_q, close_q = ("“", "”") if mode == "cn_curly" else ("「", "」")
        wrong = [(n, s) for n, s in lines if '"' in s]
        if wrong:
            record(issues, "ERROR", f"[quotes] L{wrong[0][0]}: straight double quotes on {len(wrong)} line(s); use {open_q} {close_q}")
        other = "「」『』" if mode == "cn_curly" else "“”"
        mixed = [(n, s) for n, s in lines if any(c in s for c in other)]
        if mixed:
            record(issues, "ERROR", f"[quotes] L{mixed[0][0]}: other quote style on {len(mixed)} line(s); project uses {open_q} {close_q}")
        half = [(n, s) for n, s in lines if re.search(r"[一-鿿][,?!;:][一-鿿]", s)]
        if half:
            record(issues, "WARN", f"[quotes] L{half[0][0]}: half-width punctuation between Chinese characters on {len(half)} line(s)")
        _check_paired_quotes(lines, open_q, close_q, issues)
        pattern = cfg.get("lost_quote_pattern")
        if pattern and mode == "cn_curly":
            lost = re.compile(pattern)
            for lineno, line in lines:
                if open_q not in line and lost.search(line):
                    record(issues, "WARN", f"[quotes] L{lineno}: dialogue may have lost its quotes: {line.strip()[:40]}")
        return

    # English quote modes: en_double, en_straight, en_curly, en_single
    cjk_brackets = [(n, s) for n, s in lines if any(c in s for c in "「」『』《》")]
    if cjk_brackets:
        record(issues, "ERROR", f"[quotes] L{cjk_brackets[0][0]}: CJK corner/book quotes on {len(cjk_brackets)} line(s) in English mode")

    if mode == "en_straight":
        curly_lines = [(n, s) for n, s in lines if "“" in s or "”" in s]
        if curly_lines:
            record(issues, "ERROR", f"[quotes] L{curly_lines[0][0]}: curly double quotes on {len(curly_lines)} line(s); project uses straight \" quotes")
        _check_straight_quotes(lines, issues)
    elif mode == "en_curly":
        straight_lines = [(n, s) for n, s in lines if '"' in s]
        if straight_lines:
            record(issues, "ERROR", f"[quotes] L{straight_lines[0][0]}: straight double quotes on {len(straight_lines)} line(s); project uses “ ”")
        _check_paired_quotes(lines, "“", "”", issues, allow_epistolary=True)
    elif mode == "en_single":
        double_lines = [(n, s) for n, s in lines if '"' in s or "“" in s or "”" in s]
        if double_lines:
            record(issues, "WARN", f"[quotes] L{double_lines[0][0]}: double quotes on {len(double_lines)} line(s) while quotes=en_single")
        _check_paired_quotes(lines, "‘", "’", issues, allow_epistolary=True)
    elif mode == "en_double":
        # Smart Western manuscript mode: enforce pairing on BOTH straight '"' and curly '“...”', and warn if mixed on the same line
        same_line_mix = [(n, s) for n, s in lines if '"' in s and ("“" in s or "”" in s)]
        if same_line_mix:
            record(issues, "ERROR", f"[quotes] L{same_line_mix[0][0]}: mixed straight and curly double quotes on the same line")
        else:
            has_straight = any('"' in s for _, s in lines)
            has_curly = any("“" in s or "”" in s for _, s in lines)
            if has_straight and has_curly:
                first_c = next(n for n, s in lines if "“" in s or "”" in s)
                record(issues, "WARN", f"[quotes] L{first_c}: chapter mixes straight (\") and curly (“ ”) double quotes; standardize if targeting print/EPUB")
        _check_straight_quotes(lines, issues)
        _check_paired_quotes(lines, "“", "”", issues, allow_epistolary=True)


def final_cjk_leak(lines: list[tuple[int, str]], cfg: dict[str, Any], issues: list[tuple[str, str]]) -> None:
    if not cfg.get("cjk_leak_check"):
        return
    cjk_re = re.compile(r"[㐀-鿿，。！？；：【】《》「」『』、]")
    for lineno, line in lines:
        m = cjk_re.search(line)
        if m:
            snippet = line[max(0, m.start() - 12):min(len(line), m.end() + 18)].strip()
            record(issues, "ERROR", f"[cjk-leak] L{lineno}: CJK character/punctuation leaked into English prose: {snippet!r}")


# ---------- English Narrative Tense-Drift Engine ----------

EN_DEFINITE_PAST_ANCHOR_RE = re.compile(
    r"\b(?:"
    r"(?:\w+\s+)?(?:seconds?|minutes?|hours?|days?|weeks?|months?|years?|decades?)\s+ago"
    r"|yesterday|last\s+(?:night|week|weekend|month|year|spring|summer|fall|autumn|winter|semester|Tuesday|Monday|Wednesday|Thursday|Friday|Saturday|Sunday)"
    r"|earlier\s+(?:today|tonight|this\s+morning|this\s+afternoon|this\s+evening|this\s+week)"
    r"|in\s+(?:high\s+school|middle\s+school|grade\s+school|college|freshman\s+year|sophomore\s+year|20\d\d|19\d\d)"
    r"|back\s+in\s+[A-Z]\w+"
    r"|when\s+(?:I|she|he|we|they)\s+(?:was|were|lived|worked|created|went|came|met|started)"
    r"|before\s+(?:tonight|today|we\s+met|I\s+met)"
    r"|used\s+to\b|once\s+before\b"
    r"|for\s+(?:six|five|four|three|two|ten|\d+)\s+(?:months|years)\b"
    r")",
    re.IGNORECASE,
)

EN_COUNTERFACTUAL_RE = re.compile(
    r"\b(?:if|unless|as\s+if|as\s+though|wish|wishes|wished|wishing|would\s+have|could\s+have|might\s+have|should\s+have)\b",
    re.IGNORECASE,
)

EN_PRES_ANCHOR_RE = re.compile(
    r"\b(?:"
    r"I\s+(?:am|['’]m|do|don['’]t|have|haven['’]t|can|can['’]t|sit|stand|walk|look|stare|turn|take|pull|push|feel|hear|see|know|think|whisper|say|ask|breathe|swallow|freeze|step|reach|press|hold|lean|watch|shake|nod|grab|open|close)"
    r"|(?:[Hh]e|[Ss]he|[Ii]t|[A-Z][a-z]{2,15})\s+(?:is|isn['’]t|does|doesn['’]t|has|hasn['’]t|says|murmurs|whispers|asks|replies|looks|stares|turns|stands|sits|walks|steps|reaches|takes|holds|leans|smiles|smirks|nods|pulls|pushes|moves)"
    r")\b"
)

EN_PAST_ANCHOR_RE = re.compile(
    r"\b(?:"
    r"I\s+(?:was|wasn['’]t|did|didn['’]t|sat|stood|walked|looked|stared|turned|took|pulled|pushed|felt|heard|saw|knew|thought|whispered|said|asked|breathed|swallowed|froze|stepped|reached|pressed|held|leaned|watched|shook|nodded|grabbed|opened|closed)"
    r"|(?:[Hh]e|[Ss]he|[Ii]t|[A-Z][a-z]{2,15})\s+(?:was|wasn['’]t|did|didn['’]t|said|murmured|whispered|asked|replied|looked|stared|turned|stood|sat|walked|stepped|reached|took|held|leaned|smiled|smirked|nodded|pulled|pushed|moved)"
    r")\b"
)


def analyze_en_tense(
    lines: list[tuple[int, str]],
) -> tuple[int, int, float, list[tuple[int, str, str]]]:
    """Return (pres_count, past_count, pres_ratio, slip_samples[(lineno, kind, snippet)])."""
    pres_total = 0
    past_total = 0
    para_records: list[tuple[int, int, int, str]] = []
    in_flashback_block = False

    for lineno, line in lines:
        s = line.strip()
        # Skip non-narration formatting lines (headings, dividers, SMS **Name:**, italic system alerts, blockquotes)
        if (
            not s
            or s.startswith(("#", ">", "**"))
            or s in {"***", "---", "* * *"}
            or (s.startswith("*") and s.endswith("*") and ":" in s[:35])
        ):
            continue

        unq = mask_dialogue(s, "en")
        # Detect multi-paragraph flashback start (e.g. "Six months ago, ..." or heavy pluperfect memory density >= 2)
        hads = len(re.findall(r"\bhad\s+[a-z]+", unq, re.IGNORECASE))
        if re.match(r"^(?:Six|Five|Four|Three|Two|Ten|Twenty|\d+)\s+(?:months|years|weeks)\s+ago\b", s, re.IGNORECASE) or hads >= 2:
            in_flashback_block = True
        elif in_flashback_block:
            # Exit flashback block as soon as dialogue opens at start of line or clear present-tense anchor appears without pluperfect
            if s.startswith(('"', "“")) or (EN_PRES_ANCHOR_RE.search(unq) and hads == 0):
                in_flashback_block = False

        if in_flashback_block:
            continue

        p_pres = 0
        p_past = 0
        for sent in re.split(r"(?<=[.!?])\s+", unq):
            if not sent.strip():
                continue
            if EN_DEFINITE_PAST_ANCHOR_RE.search(sent) or EN_COUNTERFACTUAL_RE.search(sent):
                continue
            p_pres += len(EN_PRES_ANCHOR_RE.findall(sent))
            p_past += len(EN_PAST_ANCHOR_RE.findall(sent))

        pres_total += p_pres
        past_total += p_past
        if p_pres or p_past:
            para_records.append((lineno, p_pres, p_past, s))

    denom = pres_total + past_total
    pres_ratio = (pres_total / denom) if denom > 0 else 1.0
    dominant = "present" if pres_ratio >= 0.5 else "past"
    slips: list[tuple[int, str, str]] = []
    for lineno, p_pres, p_past, raw_line in para_records:
        if dominant == "present" and p_past > 0 and p_past >= p_pres:
            slips.append((lineno, "past_in_present", raw_line[:85]))
        elif dominant == "past" and p_pres > 0 and p_pres >= p_past:
            slips.append((lineno, "present_in_past", raw_line[:85]))

    return pres_total, past_total, pres_ratio, slips


def final_tense(
    lines: list[tuple[int, str]],
    cfg: dict[str, Any],
    chapter_num: int | None,
    cli_tense: str | None,
    issues: list[tuple[str, str]],
) -> tuple[int, int, float]:
    tense_cfg = cfg.get("tense") or {}
    mode = (cli_tense or tense_cfg.get("mode") or "off").lower()
    if mode not in SUPPORTED_TENSE_MODES:
        raise InputError(f"Unsupported tense mode {mode!r}; use present, past, auto, or off")
    if cfg.get("lang") != "en" or mode == "off":
        return (0, 0, 1.0)

    flashback_chapters = set(tense_cfg.get("flashback_chapters") or [])
    if chapter_num is not None and chapter_num in flashback_chapters:
        return (0, 0, 1.0)

    pres, past, pres_ratio, slips = analyze_en_tense(lines)
    total = pres + past
    if total < 3:
        return (pres, past, pres_ratio)

    min_ratio = float(tense_cfg.get("min_ratio", 0.80))
    if mode == "present":
        if pres_ratio < min_ratio:
            record(
                issues,
                "ERROR",
                f"[tense] chapter present-tense anchor ratio is {pres_ratio:.1%} ({pres} present vs {past} past), below required {min_ratio:.0%}",
            )
        elif tense_cfg.get("paragraph_slip", True):
            for lineno, _, snippet in slips[:5]:
                record(issues, "WARN", f"[tense] L{lineno}: unanchored past-tense narration in present-tense chapter: {snippet}")
    elif mode == "past":
        past_ratio = 1.0 - pres_ratio
        if past_ratio < min_ratio:
            record(
                issues,
                "ERROR",
                f"[tense] chapter past-tense anchor ratio is {past_ratio:.1%} ({past} past vs {pres} present), below required {min_ratio:.0%}",
            )
        elif tense_cfg.get("paragraph_slip", True):
            for lineno, _, snippet in slips[:5]:
                record(issues, "WARN", f"[tense] L{lineno}: unanchored present-tense narration in past-tense chapter: {snippet}")
    elif mode == "auto":
        dominant_ratio = max(pres_ratio, 1.0 - pres_ratio)
        dominant_label = "present" if pres_ratio >= 0.5 else "past"
        if dominant_ratio < min_ratio:
            record(
                issues,
                "WARN",
                f"[tense] mixed narrative tense within chapter ({pres} present vs {past} past; dominant {dominant_label} = {dominant_ratio:.1%})",
            )
            for lineno, _, snippet in slips[:3]:
                record(issues, "WARN", f"[tense] L{lineno}: possible tense drift against {dominant_label} baseline: {snippet}")

    return (pres, past, pres_ratio)


def final_banned(
    body: str, lines: list[tuple[int, str]], previous: list[str], cfg: dict[str, Any],
    issues: list[tuple[str, str]],
) -> None:
    lang = cfg.get("lang", "zh")
    disabled = set(cfg.get("disable_banned", []))
    rules = [rule for rule in [*cfg["banned"], *cfg.get("extra_banned", [])]
             if isinstance(rule, dict) and rule.get("term") not in disabled and rule.get("label") not in disabled]
    for rule in rules:
        term = rule.get("term")
        if not isinstance(term, str) or not term:
            raise InputError("Each banned rule needs a nonempty term")
        flags = re.IGNORECASE if (lang == "en" and rule.get("ignore_case", True)) else 0
        regex = re.compile(term if rule.get("regex") else re.escape(term), flags)
        narration_only = rule.get("where") == "narration"
        current = regex.findall(mask_dialogue(body, lang) if narration_only else body)
        if not current:
            continue
        limit = int(rule.get("max", 0))
        window = int(rule.get("window", 1))
        earlier = previous[-(window - 1):] if window > 1 else []
        total = len(current) + sum(
            len(regex.findall(mask_dialogue(text, lang) if narration_only else text)) for text in earlier
        )
        if total <= limit:
            continue
        label = rule.get("label") or term
        note = f"; {rule['note']}" if rule.get("note") else ""
        line = next((n for n, s in lines if regex.search(mask_dialogue(s, lang) if narration_only else s)), 0)
        scope = f"{total} in the last {window} chapter(s)" if window > 1 else f"{len(current)} time(s)"
        record(issues, rule.get("severity", "ERROR"), f"[phrase] L{line}: “{label}” appears {scope}, limit {limit}{note}")


def final_structure(
    lines: list[tuple[int, str]], body: str, cfg: dict[str, Any], issues: list[tuple[str, str]],
) -> None:
    lang = cfg.get("lang", "zh")
    count = en_word_count(body) if lang == "en" else han_count(body)
    unit_label = "words" if lang == "en" else "Han characters"
    low, high = cfg["length"].get("min"), cfg["length"].get("max")
    tolerance = float(cfg["length"].get("tolerance") or 0)
    if isinstance(low, int) and count < low:
        severity = "ERROR" if count < low * (1 - tolerance) else "WARN"
        record(issues, severity, f"[length] {count} {unit_label}, below minimum {low}")
    if isinstance(high, int) and count > high:
        severity = "ERROR" if count > high * (1 + tolerance) else "WARN"
        record(issues, severity, f"[length] {count} {unit_label}, above maximum {high}")
    tail = lines[-int(cfg["ending_window_paragraphs"]):] if lines else []
    for pattern in cfg["ending_patterns"]:
        regex = re.compile(pattern)
        for lineno, line in tail:
            if regex.search(line):
                record(issues, "ERROR", f"[ending] L{lineno}: summary or uplift ending: {line.strip()[:55]}")
    for pattern in cfg["meta_patterns"]:
        regex = re.compile(pattern)
        for lineno, line in lines:
            if line.strip() in {"***", "---", "* * *"}:
                continue
            target_s = mask_dialogue(line, lang) if "chapter" in pattern.lower() else line
            if regex.search(target_s):
                sev = "ERROR" if "chapter" in pattern.lower() and lang == "en" else "WARN"
                record(issues, sev, f"[meta] L{lineno}: possible planning, fourth-wall, or audit text in prose: {line.strip()[:55]}")
                break


def final_hooks(
    body: str, cfg: dict[str, Any], hook: list[str], catch: list[str], issues: list[tuple[str, str]],
) -> None:
    lang = cfg.get("lang", "zh")
    if lang == "en":
        words = body.split()
        landing_w = int(cfg.get("landing_words") or 120)
        opening_w = int(cfg.get("opening_words") or 160)
        if hook:
            tail_text = " ".join(words[-landing_w:]).lower()
            missing = [w for w in hook if w.lower() not in tail_text]
            if missing:
                record(issues, "ERROR", f"[hook] planned ending is not in the last {landing_w} words: {', '.join(missing)}")
        if catch:
            head_text = " ".join(words[:opening_w]).lower()
            missing = [w for w in catch if w.lower() not in head_text]
            if missing:
                record(issues, "ERROR", f"[catch] opening does not pick up the previous ending within {opening_w} words: {', '.join(missing)}")
        return

    plain = re.sub(r"\s+", "", body)
    if hook:
        tail = plain[-int(cfg["landing_chars"]):]
        missing = [word for word in hook if word not in tail]
        if missing:
            record(issues, "ERROR", f"[hook] planned ending is not in the last {cfg['landing_chars']} characters: {'、'.join(missing)}")
    if catch:
        head = plain[:int(cfg["opening_chars"]):]
        missing = [word for word in catch if word not in head]
        if missing:
            record(issues, "ERROR", f"[catch] opening does not pick up the previous ending within {cfg['opening_chars']} characters: {'、'.join(missing)}")


def split_keywords(value: str | None) -> list[str]:
    if not value:
        return []
    return [word.strip() for word in re.split(r"[,，、]", value) if word.strip()]


def command_final_check(args: argparse.Namespace) -> int:
    chapter = Path(args.chapter_file).expanduser().resolve()
    if not chapter.is_file():
        raise InputError(f"Chapter file does not exist: {chapter}")
    project = Path(args.project).expanduser().resolve() if args.project else None
    config = Path(args.config).expanduser().resolve() if args.config else None
    text = chapter.read_text(encoding="utf-8")
    lines, body = chapter_body(text)
    cfg = load_final_config(project, config, getattr(args, "lang", None), body)
    lang = cfg["lang"]
    chapter_num = getattr(args, "chapter", None) or infer_chapter_number(chapter)

    previous = []
    for item in args.previous or []:
        path = Path(item).expanduser().resolve()
        if not path.is_file():
            raise InputError(f"Previous chapter does not exist: {path}")
        previous.append(chapter_body(path.read_text(encoding="utf-8"))[1])

    issues: list[tuple[str, str]] = []
    if not body.strip():
        record(issues, "ERROR", "[length] chapter has no prose after the heading")
    final_quotes(lines, cfg, issues)
    final_cjk_leak(lines, cfg, issues)
    final_tense(lines, cfg, chapter_num, getattr(args, "tense", None), issues)
    final_banned(body, lines, previous, cfg, issues)
    final_structure(lines, body, cfg, issues)
    final_hooks(body, cfg, split_keywords(args.hook), split_keywords(args.catch), issues)

    if project is not None:
        state_path = ledger_paths(project)[1]
        if state_path.is_file():
            state = load_json(state_path)
            validate_state(state, issues)
            if not any(severity == "ERROR" and "state.json" in message for severity, message in issues):
                scan_retired_names(body, state, issues)
                scan_state_continuity_rules(body, lines, state, chapter_num, lang, issues)

    if lang == "en":
        print(f"Final check: {chapter.name}, {en_word_count(body)} words (lang=en)")
    else:
        print(f"Final check: {chapter.name}, {han_count(body)} Han characters")
    show_issues(issues)
    return 1 if any(severity == "ERROR" for severity, _ in issues) else 0


# ---------- Cross-Volume Series Audit (跨卷连续性与全书终检) ----------

BACKSTAGE_FILE_RE = re.compile(r"^(?:walkthrough|summary|notes|outline|brief|audit|readme)[-_.]", re.IGNORECASE)


def discover_series_chapters(project: Path, chapters_dir: str | None, pattern: str | None = None) -> list[Path]:
    if chapters_dir:
        cdir = Path(chapters_dir).expanduser()
        if not cdir.is_absolute():
            cdir = (project / cdir).resolve()
    else:
        for candidate in ("正文", "chapters", "章节", "manuscript"):
            if (project / candidate).is_dir():
                cdir = (project / candidate).resolve()
                break
        else:
            cdir = project
    if not cdir.is_dir():
        raise InputError(f"Chapters directory does not exist: {cdir}")
    glob_pat = pattern or "*.md"
    md_files = [
        p for p in cdir.glob(glob_pat)
        if p.is_file() and (pattern is not None or (p.name.lower() != "readme.md" and not BACKSTAGE_FILE_RE.match(p.name)))
    ]
    if not md_files:
        raise InputError(f"No chapter files matching {glob_pat!r} found in {cdir}")
    md_files.sort(key=lambda p: (infer_chapter_number(p) is None, infer_chapter_number(p) or 0, p.name))
    return md_files


def command_audit_series(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    if not project.is_dir():
        raise InputError(f"Project directory does not exist: {project}")
    config = Path(args.config).expanduser().resolve() if args.config else None
    chapters = discover_series_chapters(project, args.chapters_dir, getattr(args, "pattern", None))

    first_body = chapter_body(chapters[0].read_text(encoding="utf-8"))[1]
    cfg = load_final_config(project, config, args.lang, first_body)
    lang = cfg["lang"]

    state: dict[str, Any] | None = None
    state_path = ledger_paths(project)[1]
    series_issues: list[tuple[str, str]] = []
    if state_path.is_file():
        state = load_json(state_path)
        validate_state(state, series_issues)

    history_bodies: list[str] = []
    total_metric = 0
    vol_size = max(1, int(args.volume_size or 20))
    vol_stats: dict[int, list[float]] = {}
    phrase_totals: dict[str, int] = {}

    disabled = set(cfg.get("disable_banned", []))
    active_rules = [
        r for r in [*cfg["banned"], *cfg.get("extra_banned", [])]
        if isinstance(r, dict) and r.get("term") not in disabled and r.get("label") not in disabled
    ]

    for idx, ch_path in enumerate(chapters, 1):
        raw = ch_path.read_text(encoding="utf-8")
        lines, body = chapter_body(raw)
        ch_num = infer_chapter_number(ch_path) or idx
        total_metric += en_word_count(body) if lang == "en" else han_count(body)

        ch_issues: list[tuple[str, str]] = []
        final_quotes(lines, cfg, ch_issues)
        final_cjk_leak(lines, cfg, ch_issues)
        pres, past, p_ratio = final_tense(lines, cfg, ch_num, args.tense, ch_issues)
        if lang == "en" and (pres + past) >= 4:
            vol_idx = (idx - 1) // vol_size + 1
            vol_stats.setdefault(vol_idx, []).append(p_ratio)

        final_banned(body, lines, history_bodies, cfg, ch_issues)
        final_structure(lines, body, cfg, ch_issues)

        if state is not None:
            scan_retired_names(body, state, ch_issues)
            scan_state_continuity_rules(body, lines, state, ch_num, lang, ch_issues)

        # Count book-wide phrase density for summary
        for rule in active_rules:
            term = rule["term"]
            flags = re.IGNORECASE if (lang == "en" and rule.get("ignore_case", True)) else 0
            rx = re.compile(term if rule.get("regex") else re.escape(term), flags)
            narration_only = rule.get("where") == "narration"
            hits = len(rx.findall(mask_dialogue(body, lang) if narration_only else body))
            if hits:
                lbl = rule.get("label") or term
                phrase_totals[lbl] = phrase_totals.get(lbl, 0) + hits

        for sev, msg in ch_issues:
            if args.errors_only and sev != "ERROR":
                continue
            series_issues.append((sev, f"[{ch_path.name}] {msg}"))

        history_bodies.append(body)

    unit_name = "words" if lang == "en" else "Han characters"
    print(f"Series audit: {len(chapters)} chapter(s), {total_metric:,} {unit_name} (lang={lang})")
    if lang == "en" and vol_stats:
        vol_parts = [
            f"Vol.{v}: {sum(ratios)/len(ratios):.1%} present"
            for v, ratios in sorted(vol_stats.items())
        ]
        print("Tense by volume: " + " | ".join(vol_parts))
    if phrase_totals:
        top_phrases = sorted(phrase_totals.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
        print("Tracked phrase totals: " + ", ".join(f"{k}={v}" for k, v in top_phrases))

    max_show = int(args.max_issues or 60)
    shown = series_issues[:max_show]
    for severity, message in shown:
        print(f"{severity}: {message}")
    if len(series_issues) > max_show:
        print(f"... ({len(series_issues) - max_show} additional finding(s) omitted; increase --max-issues)")

    errors = sum(sev == "ERROR" for sev, _ in series_issues)
    warnings = sum(sev == "WARN" for sev, _ in series_issues)
    print(f"Series audit complete: {errors} error(s), {warnings} warning(s)")
    return 1 if errors > 0 else 0


def register_approved_chapter(sources: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    updated = copy.deepcopy(sources)
    chapter = delta["chapter"]
    path = delta["chapter_file"]
    matches = [entry for entry in updated["sources"] if entry.get("path") == path]
    if len(matches) > 1:
        raise InputError(f"Multiple source records refer to approved chapter: {path}")
    if matches:
        entry = matches[0]
        if entry.get("status") != "candidate":
            raise InputError(f"Existing source record is not a candidate: {path}")
    else:
        source_id = f"approved-ch-{chapter:03d}"
        if any(entry.get("id") == source_id for entry in updated["sources"]):
            raise InputError(f"Source id already exists: {source_id}")
        entry = {"id": source_id, "path": path}
        updated["sources"].append(entry)
    entry.update(
        kind="approved_prose",
        status="active",
        chapter_start=chapter,
        chapter_end=chapter,
        sha256=delta["chapter_sha256"],
    )
    return updated


def command_approve(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    ledger, state_path, sources_path = ledger_paths(project)
    delta_path = Path(args.delta).expanduser().resolve()
    if not args.approval_note.strip():
        raise InputError("Approval note must record the user's explicit decision")
    if not ledger.is_dir():
        raise InputError(f"Ledger does not exist: {ledger}")
    lock = ledger / ".approve.lock"
    try:
        with lock.open("x", encoding="utf-8") as stream:
            stream.write(datetime.now(timezone.utc).isoformat())
    except FileExistsError as exc:
        raise InputError("Another approval is in progress or left a lock") from exc
    try:
        issues, updated = run_checks(project, delta_path)
        show_issues(issues)
        if updated is None or any(severity == "ERROR" for severity, _ in issues):
            raise InputError("Approval stopped because checks failed")
        delta = load_json(delta_path)
        if delta.get("new_canon_requests"):
            raise InputError("Resolve new_canon_requests before approval")
        sources = load_json(sources_path)
        approved_sources = register_approved_chapter(sources, delta)
        chapter = delta["chapter"]
        receipt_path = ledger / "approvals" / f"ch-{chapter:03d}.json"
        if receipt_path.exists():
            raise InputError(f"Approval receipt already exists: {receipt_path}")
        prior_hash = sha256_file(state_path)
        prior_sources_hash = sha256_file(sources_path)
        state_backup = ledger / "backups" / f"state-before-ch-{chapter:03d}-{prior_hash[:12]}.json"
        sources_backup = ledger / "backups" / f"sources-before-ch-{chapter:03d}-{prior_sources_hash[:12]}.json"
        if state_backup.exists() or sources_backup.exists():
            raise InputError("Approval backup already exists")
        shutil.copy2(state_path, state_backup)
        shutil.copy2(sources_path, sources_backup)
        receipt = {
            "schema_version": 1,
            "chapter": chapter,
            "chapter_sha256": delta["chapter_sha256"],
            "delta_sha256": sha256_file(delta_path),
            "prior_state_sha256": prior_hash,
            "approved_state_sha256": sha256_bytes(json_bytes(updated)),
            "prior_sources_sha256": prior_sources_hash,
            "approved_sources_sha256": sha256_bytes(json_bytes(approved_sources)),
            "approval_note": args.approval_note.strip(),
            "approved_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        try:
            atomic_json(state_path, updated)
            atomic_json(sources_path, approved_sources)
            exclusive_json(receipt_path, receipt)
        except Exception:
            shutil.copy2(state_backup, state_path)
            shutil.copy2(sources_backup, sources_path)
            raise
        print(f"Approved chapter {chapter}; backups: {state_backup}, {sources_backup}; receipt: {receipt_path}")
        return 0
    finally:
        lock.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Initialize an optional ledger without overwriting files")
    init.add_argument("project")
    init.add_argument("--new-project", action="store_true", help="Add missing planning document skeletons")
    init.set_defaults(func=command_init)

    prepare = sub.add_parser("prepare", help="Prepare a candidate delta after drafting")
    prepare.add_argument("project")
    prepare.add_argument("chapter_file")
    prepare.add_argument("--chapter", type=int, required=True)
    prepare.set_defaults(func=command_prepare)

    check = sub.add_parser("check", help="Read-only state and candidate checks")
    check.add_argument("project")
    check.add_argument("--delta")
    check.set_defaults(func=command_check)

    final = sub.add_parser(
        "final-check",
        help="Read-only last gate for one chapter: quotes, CJK leaks, tense drift, stock phrases, ending, length, hook landing, continuity rules",
    )
    final.add_argument("chapter_file")
    final.add_argument("--project", help="Novel project root; reads .novel-master-lab/final-check.json and state.json if present")
    final.add_argument("--config", help="Extra final-check JSON config, applied after the project config")
    final.add_argument("--lang", choices=["zh", "en", "auto"], help="Language mode: zh (default), en (English novel mode), or auto")
    final.add_argument("--tense", choices=["present", "past", "auto", "off"], help="English narrative tense gate: present, past, auto, or off")
    final.add_argument("--chapter", type=int, help="Explicit chapter number override for chapter-scoped continuity/persona rules")
    final.add_argument("--previous", nargs="*", help="Earlier chapters, oldest first, for multi-chapter phrase limits")
    final.add_argument("--hook", help="Comma-separated words/phrases the planned ending must contain near the end")
    final.add_argument("--catch", help="Comma-separated words/phrases the opening must contain to pick up the previous ending")
    final.set_defaults(func=command_final_check)

    series = sub.add_parser(
        "audit-series",
        help="Read-only cross-volume continuity, tense-drift, quote, and cliché-density audit across all chapters",
    )
    series.add_argument("project", help="Novel project root")
    series.add_argument("--chapters-dir", help="Chapters directory (relative to project or absolute; auto-detects 正文/ or chapters/)")
    series.add_argument("--pattern", help="Optional glob pattern for chapter files (e.g. 'Ch*.md'); backstage walkthrough/notes files are excluded automatically")
    series.add_argument("--config", help="Optional final-check JSON config")
    series.add_argument("--lang", choices=["zh", "en", "auto"], default="auto", help="Language mode (default: auto)")
    series.add_argument("--tense", choices=["present", "past", "auto", "off"], help="Narrative tense baseline across mainline chapters")
    series.add_argument("--volume-size", type=int, default=20, help="Chapters per volume bucket for tense summary (default: 20)")
    series.add_argument("--errors-only", action="store_true", help="Display only ERROR findings in per-chapter output")
    series.add_argument("--max-issues", type=int, default=60, help="Maximum findings printed before truncation (default: 60)")
    series.set_defaults(func=command_audit_series)

    approve = sub.add_parser("approve", help="Promote a checked candidate after explicit user approval")
    approve.add_argument("project")
    approve.add_argument("--delta", required=True)
    approve.add_argument("--approval-note", required=True)
    approve.set_defaults(func=command_approve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except InputError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

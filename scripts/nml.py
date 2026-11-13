#!/usr/bin/env python3
"""Small, dependency-free continuity ledger and final check for Chinese Novel Master Lab.

The ledger validates structured state transitions. The final check reports mechanical
defects in one chapter. Neither judges the truth or quality of prose.
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
        if name in masked:
            record(issues, "WARN", f"retired or deprecated name may appear in prose: {name}")


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
            scan_retired_names(prose, state, issues)
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


# ---------- Final check (终检) ----------
# Mechanical last gate adapted from Commercial Writing System v2.1. It reports;
# it never edits prose. Literary quality stays a human and reviewer judgment.

FINAL_CHECK_CONFIG = "final-check.json"
FINAL_CHECK_DEFAULTS: dict[str, Any] = {
    "quotes": "cn_curly",
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
        "^\\s*[-*+]\\s", "^\\s*\\|", "【[^】]{0,12}】",
    ],
    "lost_quote_pattern": "[他她我你][^。！？”]{0,6}[说道问喊][：:](?!\\s*“)",
    "landing_chars": 300,
    "opening_chars": 400,
}
HEADING_RE = re.compile(r"^\s*(#+\s|第\s*[\d一二三四五六七八九十百千零两]+\s*[章回])")


def load_final_config(project: Path | None, config: Path | None) -> dict[str, Any]:
    merged = copy.deepcopy(FINAL_CHECK_DEFAULTS)
    candidates = []
    if project is not None:
        candidates.append(project / LEDGER_DIR / FINAL_CHECK_CONFIG)
    if config is not None:
        if not config.is_file():
            raise InputError(f"Final-check config does not exist: {config}")
        candidates.append(config)
    for path in candidates:
        if not path.is_file():
            continue
        override = load_json(path)
        for key, value in override.items():
            if key not in FINAL_CHECK_DEFAULTS:
                raise InputError(f"Unknown final-check config key {key!r} in {path}")
            if key == "length":
                if not isinstance(value, dict):
                    raise InputError("final-check length must be an object")
                merged["length"].update(value)
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


def mask_dialogue(text: str) -> str:
    return re.sub(r"“[^”]*”", lambda match: " " * len(match.group(0)), text)


def final_quotes(lines: list[tuple[int, str]], cfg: dict[str, Any], issues: list[tuple[str, str]]) -> None:
    mode = cfg["quotes"]
    if mode == "none":
        return
    if mode not in {"cn_curly", "corner"}:
        raise InputError(f"Unsupported quotes mode {mode!r}; use cn_curly, corner, or none")
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
    for index, (lineno, line) in enumerate(lines):
        depth = 0
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
            if not following.startswith(open_q):
                record(issues, "ERROR", f"[quotes] L{lineno}: quote is not closed in this paragraph")
    pattern = cfg.get("lost_quote_pattern")
    if pattern and mode == "cn_curly":
        lost = re.compile(pattern)
        for lineno, line in lines:
            if open_q not in line and lost.search(line):
                record(issues, "WARN", f"[quotes] L{lineno}: dialogue may have lost its quotes: {line.strip()[:40]}")


def final_banned(
    body: str, lines: list[tuple[int, str]], previous: list[str], cfg: dict[str, Any],
    issues: list[tuple[str, str]],
) -> None:
    disabled = set(cfg.get("disable_banned", []))
    rules = [rule for rule in [*cfg["banned"], *cfg.get("extra_banned", [])]
             if isinstance(rule, dict) and rule.get("term") not in disabled]
    for rule in rules:
        term = rule.get("term")
        if not isinstance(term, str) or not term:
            raise InputError("Each banned rule needs a nonempty term")
        regex = re.compile(term if rule.get("regex") else re.escape(term))
        narration_only = rule.get("where") == "narration"
        current = regex.findall(mask_dialogue(body) if narration_only else body)
        if not current:
            continue
        limit = int(rule.get("max", 0))
        window = int(rule.get("window", 1))
        earlier = previous[-(window - 1):] if window > 1 else []
        total = len(current) + sum(
            len(regex.findall(mask_dialogue(text) if narration_only else text)) for text in earlier
        )
        if total <= limit:
            continue
        label = rule.get("label") or term
        note = f"; {rule['note']}" if rule.get("note") else ""
        line = next((n for n, s in lines if regex.search(mask_dialogue(s) if narration_only else s)), 0)
        scope = f"{total} in the last {window} chapter(s)" if window > 1 else f"{len(current)} time(s)"
        record(issues, rule.get("severity", "ERROR"), f"[phrase] L{line}: “{label}” appears {scope}, limit {limit}{note}")


def final_structure(
    lines: list[tuple[int, str]], body: str, cfg: dict[str, Any], issues: list[tuple[str, str]],
) -> None:
    count = han_count(body)
    low, high = cfg["length"].get("min"), cfg["length"].get("max")
    tolerance = float(cfg["length"].get("tolerance") or 0)
    if isinstance(low, int) and count < low:
        severity = "ERROR" if count < low * (1 - tolerance) else "WARN"
        record(issues, severity, f"[length] {count} Han characters, below minimum {low}")
    if isinstance(high, int) and count > high:
        severity = "ERROR" if count > high * (1 + tolerance) else "WARN"
        record(issues, severity, f"[length] {count} Han characters, above maximum {high}")
    tail = lines[-int(cfg["ending_window_paragraphs"]):] if lines else []
    for pattern in cfg["ending_patterns"]:
        regex = re.compile(pattern)
        for lineno, line in tail:
            if regex.search(line):
                record(issues, "ERROR", f"[ending] L{lineno}: summary or uplift ending: {line.strip()[:40]}")
    for pattern in cfg["meta_patterns"]:
        regex = re.compile(pattern)
        for lineno, line in lines:
            if regex.search(line):
                record(issues, "WARN", f"[meta] L{lineno}: possible planning or audit text in prose: {line.strip()[:40]}")
                break


def final_hooks(
    body: str, cfg: dict[str, Any], hook: list[str], catch: list[str], issues: list[tuple[str, str]],
) -> None:
    plain = re.sub(r"\s+", "", body)
    if hook:
        tail = plain[-int(cfg["landing_chars"]):]
        missing = [word for word in hook if word not in tail]
        if missing:
            record(issues, "ERROR", f"[hook] planned ending is not in the last {cfg['landing_chars']} characters: {'、'.join(missing)}")
    if catch:
        head = plain[:int(cfg["opening_chars"])]
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
    cfg = load_final_config(project, config)
    text = chapter.read_text(encoding="utf-8")
    lines, body = chapter_body(text)
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
    print(f"Final check: {chapter.name}, {han_count(body)} Han characters")
    show_issues(issues)
    return 1 if any(severity == "ERROR" for severity, _ in issues) else 0


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
        help="Read-only last gate for one chapter: quotes, stock phrases, ending, length, hook landing",
    )
    final.add_argument("chapter_file")
    final.add_argument("--project", help="Novel project root; reads .novel-master-lab/final-check.json and state names if present")
    final.add_argument("--config", help="Extra final-check JSON config, applied after the project config")
    final.add_argument("--previous", nargs="*", help="Earlier chapters, oldest first, for multi-chapter phrase limits")
    final.add_argument("--hook", help="Comma-separated words the planned ending must contain near the end")
    final.add_argument("--catch", help="Comma-separated words the opening must contain to pick up the previous ending")
    final.set_defaults(func=command_final_check)
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

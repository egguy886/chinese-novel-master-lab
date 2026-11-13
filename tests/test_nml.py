"""Behavioral tests for the optional, structured Novel Master Lab ledger."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "nml.py"
SPEC = importlib.util.spec_from_file_location("nml", SCRIPT)
assert SPEC and SPEC.loader
nml = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(nml)


class LedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "book"
        self.project.mkdir()
        self.assertEqual(self.run_cli("init", str(self.project))[0], 0)
        self.ledger = self.project / ".novel-master-lab"
        self.state_path = self.ledger / "state.json"
        self.sources_path = self.ledger / "sources.json"
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        state.update(as_of_chapter=1, story_day=1)
        state["characters"]["captain"] = {
            "name": "船长", "location": "码头", "condition": "无伤",
            "resources": "两桶水", "aim": "返航", "voice": "简短",
        }
        state["props"]["ledger"] = {
            "name": "旧账册", "holder": "captain", "condition": "封口完整"
        }
        state["knowledge"]["f1"] = {"statement": "账册有夹层", "people": {}}
        state["threads"]["t1"] = {"name": "失踪货主", "status": "open", "last_touched": 1}
        self.write_json(self.state_path, state)
        chapter_dir = self.project / "chapters"
        chapter_dir.mkdir()
        self.chapter = chapter_dir / "002.md"
        self.chapter.write_text("# 第二章\n\n船长把账册交给大副。\n", encoding="utf-8")
        self.assertEqual(
            self.run_cli("prepare", str(self.project), "chapters/002.md", "--chapter", "2")[0], 0
        )
        self.delta_path = self.ledger / "deltas" / "ch-002.json"

    def run_cli(self, *args: str) -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = nml.main(list(args))
        return code, output.getvalue()

    @staticmethod
    def write_json(path: Path, value: dict) -> None:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def delta(self) -> dict:
        return json.loads(self.delta_path.read_text(encoding="utf-8"))

    def valid_delta(self) -> dict:
        delta = self.delta()
        delta["story_day"] = 2
        delta["summary"] = "船长把旧账册交给大副，怀疑其中有夹层。"
        delta["new_entities"]["characters"]["mate"] = {
            "name": "大副", "location": "船上", "evidence": "chapters/002.md#交接"
        }
        delta["character_changes"] = [{
            "id": "captain", "field": "location", "from": "码头", "to": "船上",
            "evidence": "chapters/002.md#登船",
        }]
        delta["prop_changes"] = [{
            "id": "ledger", "from_holder": "captain", "to_holder": "mate",
            "condition": "封口完整", "evidence": "chapters/002.md#交接",
        }]
        delta["knowledge_changes"] = [{
            "fact": "f1", "who": "captain", "from": "unknown", "to": "suspects",
            "how": "摸到纸层", "evidence": "chapters/002.md#纸边",
        }]
        delta["thread_changes"] = [{
            "id": "t1", "action": "advance", "evidence": "chapters/002.md#货主名字",
        }]
        delta["promise_open"] = [{
            "id": "p2", "text": "夹层写了什么", "due": "next", "evidence": "chapters/002.md#末段",
        }]
        return delta

    def test_init_never_overwrites_existing_ledger(self) -> None:
        before = self.state_path.read_bytes()
        code, message = self.run_cli("init", str(self.project), "--new-project")
        self.assertEqual(code, 2)
        self.assertIn("already exists", message)
        self.assertEqual(before, self.state_path.read_bytes())

    def test_new_project_templates_preserve_existing_plan(self) -> None:
        other = Path(self.temp.name) / "new-book"
        other.mkdir()
        constitution = other / "00_创作宪法.md"
        constitution.write_text("用户已有设定\n", encoding="utf-8")
        code, message = self.run_cli("init", str(other), "--new-project")
        self.assertEqual(code, 0, message)
        self.assertEqual(constitution.read_text(encoding="utf-8"), "用户已有设定\n")
        self.assertTrue((other / "04_任务清单.md").is_file())

    def test_valid_check_is_read_only_and_approval_records_backup(self) -> None:
        self.write_json(self.delta_path, self.valid_delta())
        before = self.state_path.read_bytes()
        sources_before = self.sources_path.read_bytes()
        code, message = self.run_cli("check", str(self.project), "--delta", str(self.delta_path))
        self.assertEqual(code, 0, message)
        self.assertEqual(before, self.state_path.read_bytes())
        self.assertEqual(sources_before, self.sources_path.read_bytes())
        code, message = self.run_cli(
            "approve", str(self.project), "--delta", str(self.delta_path),
            "--approval-note", "User approved chapter and candidate delta",
        )
        self.assertEqual(code, 0, message)
        approved = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(approved["as_of_chapter"], 2)
        self.assertEqual(approved["props"]["ledger"]["holder"], "mate")
        self.assertEqual(approved["knowledge"]["f1"]["people"]["captain"]["level"], "suspects")
        self.assertEqual(approved["threads"]["t1"]["status"], "advanced")
        sources = json.loads(self.sources_path.read_text(encoding="utf-8"))
        self.assertEqual(len(sources["sources"]), 1)
        self.assertEqual(sources["sources"][0]["status"], "active")
        self.assertEqual(sources["sources"][0]["sha256"], nml.sha256_file(self.chapter))
        receipt = json.loads((self.ledger / "approvals" / "ch-002.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["approved_state_sha256"], nml.sha256_file(self.state_path))
        self.assertEqual(receipt["approved_sources_sha256"], nml.sha256_file(self.sources_path))
        self.assertEqual(receipt["prior_state_sha256"], nml.sha256_bytes(before))
        self.assertEqual(receipt["prior_sources_sha256"], nml.sha256_bytes(sources_before))
        self.assertEqual(len(list((self.ledger / "backups").glob("*.json"))), 2)
        code, _ = self.run_cli(
            "approve", str(self.project), "--delta", str(self.delta_path),
            "--approval-note", "duplicate",
        )
        self.assertNotEqual(code, 0)

    def test_approval_promotes_existing_candidate_source(self) -> None:
        self.write_json(self.delta_path, self.valid_delta())
        self.write_json(self.sources_path, {
            "schema_version": 1,
            "sources": [{
                "id": "chapter-draft", "path": "chapters/002.md",
                "kind": "draft", "status": "candidate",
            }],
        })
        code, message = self.run_cli(
            "approve", str(self.project), "--delta", str(self.delta_path),
            "--approval-note", "User approved chapter and candidate delta",
        )
        self.assertEqual(code, 0, message)
        sources = json.loads(self.sources_path.read_text(encoding="utf-8"))["sources"]
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["id"], "chapter-draft")
        self.assertEqual(sources[0]["kind"], "approved_prose")
        self.assertEqual(sources[0]["status"], "active")

    def test_approved_chapter_mutation_is_detected(self) -> None:
        self.write_json(self.delta_path, self.valid_delta())
        code, message = self.run_cli(
            "approve", str(self.project), "--delta", str(self.delta_path),
            "--approval-note", "User approved chapter and candidate delta",
        )
        self.assertEqual(code, 0, message)
        self.chapter.write_text("# 第二章\n\n改过的正文。\n", encoding="utf-8")
        code, message = self.run_cli("check", str(self.project))
        self.assertEqual(code, 1)
        self.assertIn("content changed", message)

    def test_wrong_prop_holder_is_blocked(self) -> None:
        delta = self.valid_delta()
        delta["prop_changes"][0]["from_holder"] = "someone_else"
        self.write_json(self.delta_path, delta)
        code, message = self.run_cli("check", str(self.project), "--delta", str(self.delta_path))
        self.assertEqual(code, 1)
        self.assertIn("holder does not match", message)

    def test_unknown_target_prop_holder_is_blocked(self) -> None:
        delta = self.valid_delta()
        delta["prop_changes"][0]["to_holder"] = "ghost"
        self.write_json(self.delta_path, delta)
        code, message = self.run_cli("check", str(self.project), "--delta", str(self.delta_path))
        self.assertEqual(code, 1)
        self.assertIn("unknown holder", message)

    def test_knowledge_regression_is_blocked(self) -> None:
        delta = self.valid_delta()
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        state["knowledge"]["f1"]["people"]["captain"] = {
            "level": "knows", "how": "亲眼所见", "chapter": 1,
        }
        self.write_json(self.state_path, state)
        delta["state_sha256"] = nml.sha256_file(self.state_path)
        delta["knowledge_changes"][0].update({"from": "knows", "to": "suspects"})
        self.write_json(self.delta_path, delta)
        code, message = self.run_cli("check", str(self.project), "--delta", str(self.delta_path))
        self.assertEqual(code, 1)
        self.assertIn("cannot regress", message)

    def test_malformed_knowledge_level_reports_error(self) -> None:
        delta = self.valid_delta()
        delta["knowledge_changes"][0]["to"] = ["knows"]
        self.write_json(self.delta_path, delta)
        code, message = self.run_cli("check", str(self.project), "--delta", str(self.delta_path))
        self.assertEqual(code, 1)
        self.assertIn("level does not match", message)

    def test_changed_chapter_hash_is_blocked(self) -> None:
        self.write_json(self.delta_path, self.valid_delta())
        self.chapter.write_text("# 第二章\n\n改过的正文。\n", encoding="utf-8")
        code, message = self.run_cli("check", str(self.project), "--delta", str(self.delta_path))
        self.assertEqual(code, 1)
        self.assertIn("changed after delta preparation", message)

    def test_mixed_source_must_not_claim_active(self) -> None:
        source = {
            "schema_version": 1,
            "sources": [{
                "id": "old-ledger", "path": "chapters/002.md", "kind": "snapshot",
                "status": "active", "declared_through": 53, "latest_entry_chapter": 80,
            }],
        }
        self.write_json(self.sources_path, source)
        code, message = self.run_cli("check", str(self.project))
        self.assertEqual(code, 1)
        self.assertIn("mark mixed", message)
        source["sources"][0]["status"] = "mixed"
        self.write_json(self.sources_path, source)
        code, message = self.run_cli("check", str(self.project))
        self.assertEqual(code, 0, message)

    def test_missing_active_source_blocks_approval(self) -> None:
        source = {
            "schema_version": 1,
            "sources": [{
                "id": "approved-chapter", "path": "chapters/missing.md",
                "kind": "approved_prose", "status": "active",
            }],
        }
        self.write_json(self.sources_path, source)
        self.write_json(self.delta_path, self.valid_delta())
        code, message = self.run_cli("check", str(self.project), "--delta", str(self.delta_path))
        self.assertEqual(code, 1)
        self.assertIn("not currently readable", message)
        self.assertFalse(list((self.ledger / "approvals").glob("*.json")))

    def test_changed_active_source_hash_is_blocked(self) -> None:
        source = {
            "schema_version": 1,
            "sources": [{
                "id": "chapter-2", "path": "chapters/002.md", "kind": "approved_prose",
                "status": "active", "sha256": "0" * 64,
            }],
        }
        self.write_json(self.sources_path, source)
        code, message = self.run_cli("check", str(self.project))
        self.assertEqual(code, 1)
        self.assertIn("content changed", message)

    def test_registered_location_can_hold_prop(self) -> None:
        delta = self.valid_delta()
        delta["new_entities"]["locations"]["hold"] = {
            "name": "底舱", "evidence": "chapters/002.md#底舱"
        }
        delta["prop_changes"][0]["to_holder"] = "hold"
        self.write_json(self.delta_path, delta)
        code, message = self.run_cli("check", str(self.project), "--delta", str(self.delta_path))
        self.assertEqual(code, 0, message)

    def test_malformed_holder_reports_error_instead_of_crashing(self) -> None:
        delta = self.valid_delta()
        delta["prop_changes"][0]["to_holder"] = {"unexpected": "object"}
        self.write_json(self.delta_path, delta)
        code, message = self.run_cli("check", str(self.project), "--delta", str(self.delta_path))
        self.assertEqual(code, 1)
        self.assertIn("unknown holder", message)

    def test_thread_gap_is_reported_without_blocking(self) -> None:
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        state["threads"]["t1"].update(max_gap=0, payoff_by=1)
        self.write_json(self.state_path, state)
        delta = self.valid_delta()
        delta["state_sha256"] = nml.sha256_file(self.state_path)
        delta["thread_changes"] = []
        self.write_json(self.delta_path, delta)
        code, message = self.run_cli("check", str(self.project), "--delta", str(self.delta_path))
        self.assertEqual(code, 0, message)
        self.assertIn("passed payoff_by", message)
        self.assertIn("exceeded max_gap", message)

    def test_retired_name_warning_ignores_active_longer_name(self) -> None:
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        state["characters"]["captain"]["name"] = "李四海"
        state["retired_names"] = ["李四"]
        self.write_json(self.state_path, state)
        self.chapter.write_text("# 第二章\n\n李四海登船。\n", encoding="utf-8")
        delta = self.valid_delta()
        delta["state_sha256"] = nml.sha256_file(self.state_path)
        delta["chapter_sha256"] = nml.sha256_file(self.chapter)
        self.write_json(self.delta_path, delta)
        code, message = self.run_cli("check", str(self.project), "--delta", str(self.delta_path))
        self.assertEqual(code, 0, message)
        self.assertNotIn("retired or deprecated name", message)
        self.chapter.write_text("# 第二章\n\n李四来了。\n", encoding="utf-8")
        delta["chapter_sha256"] = nml.sha256_file(self.chapter)
        self.write_json(self.delta_path, delta)
        code, message = self.run_cli("check", str(self.project), "--delta", str(self.delta_path))
        self.assertEqual(code, 0, message)
        self.assertIn("retired or deprecated name", message)

    def test_approval_requires_nonempty_note(self) -> None:
        self.write_json(self.delta_path, self.valid_delta())
        code, message = self.run_cli(
            "approve", str(self.project), "--delta", str(self.delta_path),
            "--approval-note", "  ",
        )
        self.assertEqual(code, 2)
        self.assertIn("Approval note", message)
        self.assertEqual(json.loads(self.state_path.read_text(encoding="utf-8"))["as_of_chapter"], 1)

    def test_unresolved_requests_block_approval(self) -> None:
        delta = self.valid_delta()
        delta["new_canon_requests"] = [{"kind": "fact", "proposal": "待确认"}]
        self.write_json(self.delta_path, delta)
        code, message = self.run_cli(
            "approve", str(self.project), "--delta", str(self.delta_path),
            "--approval-note", "Approved text only",
        )
        self.assertEqual(code, 2)
        self.assertIn("Resolve new_canon_requests", message)

    def test_rewrite_mode_is_not_auto_promoted(self) -> None:
        delta = self.valid_delta()
        delta["mode"] = "rewrite"
        self.write_json(self.delta_path, delta)
        code, message = self.run_cli("check", str(self.project), "--delta", str(self.delta_path))
        self.assertEqual(code, 1)
        self.assertIn("Only schema_version 1 continuation", message)

    def test_next_chapter_promise_without_payoff_warns(self) -> None:
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        state["promises"]["p1"] = {
            "chapter": 1, "text": "谁拿走账册", "due": "next", "status": "open",
        }
        self.write_json(self.state_path, state)
        delta = self.valid_delta()
        delta["state_sha256"] = nml.sha256_file(self.state_path)
        self.write_json(self.delta_path, delta)
        code, message = self.run_cli("check", str(self.project), "--delta", str(self.delta_path))
        self.assertEqual(code, 0, message)
        self.assertIn("no recorded payoff", message)



class FinalCheckTests(unittest.TestCase):
    CLEAN = (
        "# 第六章 引水人\n\n"
        "雾从门缝里挤进来，漫过她的靴面。\n\n"
        "“起锚。”龙婆说。\n\n"
        "船靠上码头，牙行的人踩着跳板上来。\n\n"
        "“干娘说了，货要验，人也要验。”\n"
    )

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def chapter(self, text: str, name: str = "006.md") -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def run_cli(self, *args: str) -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = nml.main(list(args))
        return code, output.getvalue()

    def test_clean_chapter_passes_and_is_read_only(self) -> None:
        path = self.chapter(self.CLEAN)
        before = sorted(p.name for p in self.root.iterdir())
        code, message = self.run_cli(
            "final-check", str(path), "--hook", "干娘说了,人也要验", "--catch", "雾"
        )
        self.assertEqual(code, 0, message)
        self.assertIn("0 error(s), 0 warning(s)", message)
        self.assertEqual(before, sorted(p.name for p in self.root.iterdir()))
        self.assertEqual(path.read_text(encoding="utf-8"), self.CLEAN)

    def test_straight_quotes_are_errors(self) -> None:
        path = self.chapter(self.CLEAN.replace("“", '"').replace("”", '"'))
        code, message = self.run_cli("final-check", str(path))
        self.assertEqual(code, 1, message)
        self.assertIn("straight double quotes", message)

    def test_unclosed_quote_is_error(self) -> None:
        path = self.chapter("# 第一章\n\n“你来了。\n\n她没回头。\n")
        code, message = self.run_cli("final-check", str(path))
        self.assertEqual(code, 1, message)
        self.assertIn("not closed", message)

    def test_cross_paragraph_dialogue_is_allowed(self) -> None:
        path = self.chapter("# 第一章\n\n“你来了。\n\n“坐吧。”\n")
        code, message = self.run_cli("final-check", str(path))
        self.assertEqual(code, 0, message)

    def test_stock_phrase_is_error_and_narration_rule_skips_dialogue(self) -> None:
        path = self.chapter("# 第一章\n\n她不禁笑了。\n\n“仿佛见过你。”他说。\n")
        code, message = self.run_cli("final-check", str(path))
        self.assertEqual(code, 1, message)
        self.assertIn("不禁", message)
        self.assertNotIn("仿佛", message)

    def test_window_limit_ignores_old_chapters_when_current_is_clean(self) -> None:
        old = [self.chapter(f"# 旧章\n\n他嘴角微微勾起。\n", f"00{i}.md") for i in range(1, 4)]
        clean = self.chapter("# 第四章\n\n他没笑。\n", "004.md")
        code, message = self.run_cli("final-check", str(clean), "--previous", *map(str, old))
        self.assertEqual(code, 0, message)
        dirty = self.chapter("# 第五章\n\n他嘴角勾起。\n", "005.md")
        code, message = self.run_cli("final-check", str(dirty), "--previous", *map(str, old))
        self.assertEqual(code, 1, message)
        self.assertIn("嘴角勾起", message)
        self.assertIn("last 50 chapter", message)

    def test_summary_ending_is_error(self) -> None:
        path = self.chapter("# 第一章\n\n门开了。\n\n一切才刚刚开始。\n")
        code, message = self.run_cli("final-check", str(path))
        self.assertEqual(code, 1, message)
        self.assertIn("[ending]", message)

    def test_hook_and_catch_must_land(self) -> None:
        path = self.chapter(self.CLEAN)
        code, message = self.run_cli("final-check", str(path), "--hook", "秤钩", "--catch", "风暴")
        self.assertEqual(code, 1, message)
        self.assertIn("[hook]", message)
        self.assertIn("[catch]", message)

    def test_meta_text_warns_without_blocking(self) -> None:
        path = self.chapter("# 第一章\n\n本章伏笔：残牌。\n\n她收好残牌。\n")
        code, message = self.run_cli("final-check", str(path))
        self.assertEqual(code, 0, message)
        self.assertIn("[meta]", message)

    def test_project_config_sets_length_and_book_rules(self) -> None:
        project = self.root / "book"
        (project / ".novel-master-lab").mkdir(parents=True)
        (project / ".novel-master-lab" / "final-check.json").write_text(
            json.dumps({
                "length": {"min": 100, "max": 200, "tolerance": 0.1},
                "extra_banned": [{"term": "冷笑", "max": 0}],
                "disable_banned": ["不禁"],
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        path = self.chapter("# 第一章\n\n她不禁冷笑。\n")
        code, message = self.run_cli("final-check", str(path), "--project", str(project))
        self.assertEqual(code, 1, message)
        self.assertIn("冷笑", message)
        self.assertNotIn("不禁", message)
        self.assertIn("below minimum 100", message)

    def test_unknown_config_key_is_rejected(self) -> None:
        config = self.root / "bad.json"
        config.write_text('{"quote": "none"}', encoding="utf-8")
        path = self.chapter(self.CLEAN)
        code, message = self.run_cli("final-check", str(path), "--config", str(config))
        self.assertEqual(code, 2, message)
        self.assertIn("Unknown final-check config key", message)

    def test_corner_quote_mode(self) -> None:
        config = self.root / "corner.json"
        config.write_text('{"quotes": "corner"}', encoding="utf-8")
        good = self.chapter("# 第一章\n\n「起锚。」龙婆说。\n")
        code, message = self.run_cli("final-check", str(good), "--config", str(config))
        self.assertEqual(code, 0, message)
        bad = self.chapter(self.CLEAN, "007.md")
        code, message = self.run_cli("final-check", str(bad), "--config", str(config))
        self.assertEqual(code, 1, message)
        self.assertIn("other quote style", message)

    def test_retired_name_warns_when_project_ledger_exists(self) -> None:
        project = self.root / "book"
        project.mkdir()
        self.assertEqual(self.run_cli("init", str(project))[0], 0)
        state_path = project / ".novel-master-lab" / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["characters"]["hero"] = {"name": "阿奴", "aliases": [], "deprecated_names": ["阿狗"]}
        state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        path = self.chapter("# 第一章\n\n阿狗低下头。\n")
        code, message = self.run_cli("final-check", str(path), "--project", str(project))
        self.assertEqual(code, 0, message)
        self.assertIn("阿狗", message)


if __name__ == "__main__":
    unittest.main()

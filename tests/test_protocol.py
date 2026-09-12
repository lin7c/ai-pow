import copy
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import ai_pow as pow


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aipow-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        self.rec = pow.Recorder(self.root)
        self.rec.init()

    def git(self, *args):
        return pow.git(self.root, *args)

    def commit(self, text="hello"):
        (self.root / "app.txt").write_text(text)
        self.rec.sample()
        self.git("add", "app.txt")
        self.git("commit", "-qm", "test")
        return pow.head(self.root)

    def events(self):
        with self.rec.connection() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT body FROM events ORDER BY seq")]

    def test_seal_export_verify_and_tamper(self):
        self.rec.record("human.message", pow.text_meta("PRIVATE PROMPT"))
        commit = self.commit()
        proof = self.rec.seal()
        self.assertEqual(proof["commit"], commit)
        self.assertTrue(self.rec.verify()["integrity_verified"])
        dest = self.root / "proof.jsonl"
        self.rec.export(dest)
        self.assertNotIn("PRIVATE PROMPT", dest.read_text())
        self.assertTrue(pow.verify_bundle(self.root, dest)["integrity_verified"])
        with self.assertRaises(FileExistsError):
            self.rec.export(dest)
        lines = dest.read_text().splitlines()
        event = json.loads(lines[1])
        event["data"]["tokens"] = 999
        lines[1] = json.dumps(event)
        dest.write_text("\n".join(lines) + "\n")
        with self.assertRaises(ValueError):
            pow.verify_bundle(self.root, dest)

    def test_missing_tail_rejected(self):
        self.rec.record("human.message", pow.text_meta("one"))
        self.commit()
        p = self.rec.seal()
        with self.rec.connection() as db:
            rows = list(self.rec._events(db, p["epoch"]))
        with self.assertRaises(ValueError):
            pow.verify_proof(self.root, p, rows[:-1])

    def test_summary_not_trusted(self):
        self.commit()
        p = self.rec.seal()
        p["summary"]["human"]["tokens_measured"] = 10
        p.pop("proof_hash")
        p["proof_hash"] = pow.digest(p)
        with self.rec.connection() as db:
            with self.assertRaises(ValueError):
                pow.verify_proof(self.root, p, self.rec._events(db, p["epoch"]))

    def test_legacy_proof_verification(self):
        self.rec.record("assistant.visible", pow.text_meta("a"))
        self.rec.record("assistant.visible", pow.text_meta("b"))
        self.commit()
        proof = self.rec.seal()
        with self.rec.connection() as db:
            proof["summary"] = pow.summary(self.rec._events(db, proof["epoch"]), "observed-v1")
            proof.pop("score")  # Legacy releases did not seal a score.
            proof.pop("proof_hash")
            proof["proof_hash"] = pow.digest(proof)
            self.assertTrue(pow.verify_proof(self.root, proof, self.rec._events(db, proof["epoch"]))["integrity_verified"])

    def test_dedup_and_conflicting_duplicate(self):
        data = {"name": "shell", "call_id": "one"}
        self.assertTrue(self.rec.record("tool.call", data, event_id="one"))
        self.assertFalse(self.rec.record("tool.call", data, event_id="one"))
        with self.assertRaises(ValueError):
            self.rec.record("tool.call", {"name": "other"}, event_id="one")
        self.assertEqual(len(self.events()), 1)

    def test_busy_writer_retries_same_event_identity(self):
        original = self.rec._record_once
        identities = []
        def busy_then_write(kind, data, source, event_id):
            identities.append(event_id)
            if len(identities) < 3:
                raise sqlite3.OperationalError("database is locked")
            return original(kind, data, source, event_id)
        with patch.object(self.rec, "_record_once", side_effect=busy_then_write):
            self.assertTrue(self.rec.record("tool.call", {"name": "shell"}))
        self.assertEqual(len(set(identities)), 1)
        self.assertEqual(len(self.events()), 1)

    def test_busy_writer_retry_is_bounded(self):
        with patch.object(self.rec, "_record_once", side_effect=sqlite3.OperationalError("database is locked")) as call:
            with self.assertRaises(sqlite3.OperationalError):
                self.rec.record("tool.call", {"name": "shell"})
            self.assertEqual(call.call_count, 3)

    def test_concurrent_writers(self):
        errors = []
        def writer(n):
            try:
                for i in range(10):
                    self.rec.record("tool.call", {"name": "shell"}, event_id=f"{n}:{i}")
            except Exception as exc:
                errors.append(exc)
        workers = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
        for w in workers:
            w.start()
        for w in workers:
            w.join()
        self.assertFalse(errors, errors)
        self.assertEqual(len(self.events()), 40)
        self.commit()
        self.rec.seal()
        self.assertTrue(self.rec.verify()["integrity_verified"])

    def test_quota_atomic_rollback(self):
        with self.rec.connection() as db:
            used = self.rec.database.stat().st_size
            self.rec.put(db, "max_bytes", used + 16384)
        full = False
        for i in range(100):
            try:
                self.rec.record("task.change", {"task_id": str(i), "metadata": "x" * 8000})
            except sqlite3.DatabaseError:
                full = True
                break
        self.assertTrue(full)
        self.assertLessEqual(self.rec.database.stat().st_size, used + 16384)
        with self.rec.connection() as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_no_float_negative_or_double_reasoning(self):
        for data in ({"tokens": -1}, {"tokens": 2.5}):
            with self.assertRaises(ValueError):
                self.rec.record("human.message", data)
        with self.assertRaises(ValueError):
            self.rec.record("model.usage", {"model": "example", "measurement": "provider_reported",
                                             "output_tokens": 10, "reasoning_tokens": 11})

    def test_price_snapshot_decimal_and_unknown(self):
        price = {"model": "example", "source_url": "https://example.invalid/pricing",
                 "effective_date": "2026-09-12", "input_per_million": "2",
                 "cached_input_per_million": "0.2", "cache_write_per_million": "2.5",
                 "output_per_million": "10"}
        self.rec.set_price(price)
        self.rec.record("model.usage", {"model": "example", "measurement": "provider_reported",
                                         "input_tokens": 1000, "cached_input_tokens": 200,
                                         "output_tokens": 100, "cache_write_tokens": 0,
                                         "reasoning_tokens": 50})
        d = self.events()[-1]["data"]
        self.assertEqual(d["reference_usd"], "0.00264")
        self.assertEqual(d["price_snapshot_hash"], pow.digest(price))
        self.rec.record("model.usage", {"model": "unknown", "measurement": "estimated"})
        totals = self.rec.status()["active"]
        self.assertEqual(totals["unpriced_calls"], 1)
        self.assertIsNone(totals["artifact_survival"])

    def test_file_observations_do_not_store_content(self):
        path = self.root / "app.txt"
        for content in ("a", "b", "a"):
            path.write_text(content)
            self.rec.sample()
        path.unlink()
        self.rec.sample()
        edits = [e for e in self.events() if e["type"] == "file.observed"]
        self.assertEqual(len(edits), 4)
        self.assertIsNone(edits[-1]["data"]["after"])
        self.assertNotIn("path", edits[0]["data"])

    def test_symlink_large_file_and_secret_exclusions(self):
        (self.root / "secret.key").write_text("PRIVATE KEY")
        (self.root / ".env").write_text("SECRET=abc")
        (self.root / "large").write_bytes(b"x" * (pow.MAX_FILE + 1))
        (self.root / "link").symlink_to("/etc/passwd")
        result = self.rec.sample()
        self.assertEqual(result["observed_files"], 0)
        self.assertEqual(result["skipped"], 4)
        count = len(self.events())
        self.rec.sample()
        self.assertEqual(len(self.events()), count, "Idle exclusions must not grow the event log")

    def test_scan_cache_and_bounded_state(self):
        (self.root / "cached").write_text("same")
        self.rec.sample()
        self.assertEqual(self.rec.sample()["bytes_read"], 0)
        (self.root / "cached").write_text("different")
        self.assertGreater(self.rec.sample()["bytes_read"], 0)

    def test_post_commit_hook_and_existing_preserved(self):
        hook = pow.install_hook(self.rec)
        self.assertTrue(hook["installed"])
        self.assertFalse(pow.install_hook(self.rec)["installed"])
        self.commit()
        self.assertTrue(self.rec.verify()["integrity_verified"])

    def test_amend_rejected_and_reset_retains_trace(self):
        self.commit()
        self.rec.seal()
        self.rec.record("task.change", {"task_id": "draft"})
        count = len(self.events())
        self.git("commit", "--amend", "-qm", "amended")
        with self.assertRaises(ValueError):
            self.rec.record("task.change", {"task_id": "wrong interval"})
        self.rec.reset_boundary()
        self.assertGreater(len(self.events()), count)
        self.rec.record("task.change", {"task_id": "new interval"})

    def test_partial_stage_and_worktree_isolation(self):
        self.commit("base")
        self.rec.seal()
        (self.root / "app.txt").write_text("staged")
        self.git("add", "app.txt")
        (self.root / "app.txt").write_text("unstaged")
        self.rec.sample()
        self.git("commit", "-qm", "partial")
        proof = self.rec.seal()
        self.assertEqual(proof["tree"], self.git("rev-parse", "HEAD^{tree}").decode().strip())
        linked = self.root / "linked"
        self.git("worktree", "add", "--detach", str(linked), "HEAD")
        other = pow.Recorder(linked)
        self.assertNotEqual(other.directory, self.rec.directory)
        other.init()
        self.assertEqual(other.status()["proofs"], 0)
        self.assertFalse(pow.install_hook(other)["installed"])

    def test_claude_does_not_count_child_as_human(self):
        base = {"session_id": "s", "agent_id": "child"}
        pow.claude_hook(self.rec, {**base, "hook_event_name": "SubagentStart"})
        pow.claude_hook(self.rec, {**base, "hook_event_name": "SubagentStop", "last_assistant_message": "internal"})
        pow.claude_hook(self.rec, {"session_id": "s", "hook_event_name": "UserPromptSubmit", "prompt": "hi"})
        display = {"session_id": "s", "hook_event_name": "MessageDisplay", "message_id": "m", "index": 0, "delta": "hi"}
        pow.claude_hook(self.rec, display)
        pow.claude_hook(self.rec, display)
        totals = self.rec.status()["active"]
        self.assertEqual(totals["human"]["messages"], 1)
        self.assertEqual(totals["visible_ai"]["events"], 1)
        self.assertEqual(totals["event_counts"]["agent.spawn"], 1)

    def test_wrapper_preserves_exit_and_no_sampler_thread(self):
        before = threading.active_count()
        code = pow.run(self.rec, [sys.executable, "-c", "raise SystemExit(7)"], interval=1)
        self.assertEqual(code, 7)
        self.assertEqual(threading.active_count(), before)

    def test_agent_structure_is_bounded_and_versioned(self):
        def item(kind, **data):
            return {"type": kind, "data": data}
        events = [item("agent.spawn", agent_id="a"), item("agent.spawn", agent_id="b", parent_agent_id="a"),
                  item("agent.spawn", agent_id="c", parent_agent_id="b"), item("agent.stop", agent_id="c"),
                  item("tool.call", name="shell"), item("tool.call", name="shell"), item("tool.call", name="read")]
        block = pow.summary(iter(events))["agent"]
        self.assertEqual(block["graph"], [["a", ""], ["b", "a"], ["c", "b"]])
        self.assertEqual((block["max_depth"], block["nodes"], block["parents_known"]), (3, 3, 2))
        self.assertEqual(block["tool_calls_by_name"], [["shell", 2], ["read", 1]])
        self.assertEqual(block["stops"], 1)
        # The older reducer must keep producing exactly what it produced before.
        self.assertNotIn("agent", pow.summary(iter(events), algorithm="observed-v2"))
        many = [item("agent.spawn", agent_id="n%d" % i) for i in range(pow.MAX_AGENT_NODES + 5)]
        bounded = pow.summary(iter(many))["agent"]
        self.assertEqual((bounded["nodes"], bounded["spawns"]), (pow.MAX_AGENT_NODES, pow.MAX_AGENT_NODES + 5))
        self.assertTrue(bounded["truncated"])
        cycle = [item("agent.spawn", agent_id="x", parent_agent_id="y"),
                 item("agent.spawn", agent_id="y", parent_agent_id="x")]
        self.assertEqual(pow.summary(iter(cycle))["agent"]["max_depth"], 2)
        repeated = [item("agent.spawn", agent_id="a"), item("agent.spawn", agent_id="a")]
        self.assertEqual(pow.summary(iter(repeated))["agent"]["nodes"], 1)
        self.assertFalse(pow.summary(iter(repeated))["agent"]["truncated"])

    def test_interval_activity_and_payment_are_reduced(self):
        def item(kind, when, **payload):
            return {"type": kind, "time_ms": when, "data": payload}
        events = [item("run.start", 1000, run_id="r1", session_id="s1", command="laintas-cli"),
                  item("human.message", 2000, tokens=12, token_method="tokenizer", session_id="s1"),
                  item("model.usage", 3000, model="m", measurement="provider_reported",
                       input_tokens=10, output_tokens=4, actual_usd="0.75"),
                  item("tool.call", 4000, name="shell"), item("tool.result", 5000, name="shell", ok=False),
                  item("coverage.gap", 6000, reason="scan_exclusions_or_limits"),
                  item("run.stop", 905000, run_id="r1", exit_code=2)]
        totals = pow.summary(iter(events))
        self.assertEqual(totals["window"]["span_ms"], 904000)
        self.assertEqual(totals["activity"], {"runs": 1, "run_stops": 1, "nonzero_exits": 1, "sessions": 1,
                                              "sessions_truncated": False, "failed_tool_calls": 1,
                                              "coverage_gaps": 1})
        self.assertEqual(totals["actual_usd_known_subtotal"], "0.75")
        self.assertEqual(totals["actual_priced_calls"], 1)
        # Run ids never inflate the session count, and older reducers stay unchanged.
        self.assertEqual(pow.summary(iter(events))["activity"]["sessions"], 1)
        for algorithm in ("observed-v2", "observed-v3"):
            self.assertNotIn("window", pow.summary(iter(events), algorithm=algorithm))
            self.assertNotIn("actual_usd_known_subtotal", pow.summary(iter(events), algorithm=algorithm))
        empty = pow.summary(iter([]))
        self.assertEqual(empty["window"]["span_ms"], None)
        self.assertIsNone(empty["actual_usd_known_subtotal"])

    def test_commit_diff_stats_come_from_git(self):
        self.commit("one\ntwo\nthree\n")
        self.rec.seal()
        (self.root / "app.txt").write_text("one\n")
        self.rec.sample()
        self.git("add", "app.txt")
        self.git("commit", "-qm", "trim")
        proof = self.rec.seal()
        self.assertEqual(self.rec.diff_stats(proof), {"files": 1, "insertions": 0, "deletions": 2})
        self.assertEqual(self.rec.report_data()["diff"], {"files": 1, "insertions": 0, "deletions": 2})

    def test_iteration_chain_is_t_minus_one_plus_this_commit(self):
        """Each commit appends one hash-linked row; history is not replayed."""
        first = self.commit("one")
        self.rec.seal()
        second = self.commit("two")
        self.rec.seal()
        with self.rec.connection() as db:
            chain, verified = self.rec.iterations(db)
        self.assertTrue(verified)
        self.assertEqual([row["commit"] for row in chain], [second, first])
        latest, earlier = chain
        self.assertEqual(latest["seq"], 2)
        self.assertEqual(latest["parent"], first)
        self.assertEqual(latest["previous"], earlier["hash"])
        self.assertEqual(earlier["previous"], pow.EMPTY_HASH)
        self.assertTrue(latest["continues"])
        # T = T-1 + this commit, field by field.
        for field in ("operations", "retained", "prompts", "tool_calls"):
            self.assertEqual(latest["cumulative"][field],
                             earlier["cumulative"][field] + latest["contribution"][field])
        self.assertEqual(latest["cumulative"]["commits"], 2)
        self.assertEqual(latest["cumulative"]["score_total"],
                         format(Decimal(earlier["cumulative"]["score_total"])
                                + Decimal(latest["contribution"]["score"]["value"]), ".1f"))

    def test_history_survives_a_lost_proof(self):
        """The chain carries the history, so pruning a proof cannot shrink it."""
        self.commit("one")
        self.rec.seal()
        self.commit("two")
        self.rec.seal()
        before = self.rec.index_data()
        with self.rec.connection() as db:
            db.execute("DELETE FROM proofs WHERE commit_id=?", (before["history"][1]["commit"],))
        after = self.rec.index_data()
        self.assertEqual(after["lifetime"]["artifact_operations"], before["lifetime"]["artifact_operations"])
        self.assertEqual(after["iteration"]["value"], before["iteration"]["value"])
        self.assertEqual(after["lifetime"]["commits"], 2)
        self.assertTrue(after["chain_verified"])

    def test_rebuild_reproduces_the_chain_and_marks_breaks(self):
        self.commit("one")
        self.rec.seal()
        self.commit("two")
        self.rec.seal()
        with self.rec.connection() as db:
            original = [row["hash"] for row in self.rec.iterations(db)[0]]
        self.rec.rebuild_iterations()
        with self.rec.connection() as db:
            rebuilt = [row["hash"] for row in self.rec.iterations(db)[0]]
        self.assertEqual(original, rebuilt)
        # A boundary reset leaves a gap, and the next row says so instead of hiding it.
        self.git("commit", "--allow-empty", "-qm", "unobserved")
        self.rec.reset_boundary()
        self.rec.sample()
        self.commit("three")
        self.rec.seal()
        with self.rec.connection() as db:
            chain = self.rec.iterations(db)[0]
        self.assertFalse(chain[0]["continues"])
        self.assertEqual(chain[0]["cumulative"]["commits"], 3)

    def test_sealed_agent_structure_verifies(self):
        self.rec.record("agent.spawn", {"agent_id": "worker", "parent_agent_id": "main"}, "test")
        self.rec.record("tool.call", {"name": "shell", "call_id": "1"}, "test")
        self.commit()
        proof = self.rec.seal()
        self.assertEqual(proof["summary"]["agent"]["graph"], [["worker", "main"]])
        self.assertTrue(self.rec.verify()["integrity_verified"])

if __name__ == "__main__":
    unittest.main()

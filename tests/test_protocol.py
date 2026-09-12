import copy
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


if __name__ == "__main__":
    unittest.main()

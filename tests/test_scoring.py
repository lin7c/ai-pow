import copy
import unittest

import ai_pow as pow
from ai_pow_scoring import collect_evidence, fingerprints, history_stats, score, ladder_step
from ai_pow_report import render
import test_protocol


def fixture(ratio=.9, units=64, prompts=24, tasks=12, cost=2):
    evidence = {"artifact": {"retained": round(100 * ratio), "operations": 100, "checked_operations": 100},
                "human": {"retained_weight": str(ratio * prompts * 100), "observed_weight": prompts * 100,
                          "linked_prompts": prompts, "prompts": prompts, "attribution": "temporal-proxy"},
                "task": {"completed": round(tasks * ratio), "attempts": tasks, "declared": tasks,
                         "basis": "declared-with-committed-evidence"},
                "scope": {"units": units, "files": 4}, "limited": False, "gaps": 0}
    metrics = pow.summary([])
    metrics.update(human={"events": prompts, "messages": prompts, "tokens_measured": 1200, "tokens_estimated": 0, "tokens_complete": True},
                   visible_ai={"events": 5, "tokens_measured": 700, "tokens_estimated": 0, "tokens_complete": True},
                   reference_cost_complete_for_observed_calls=True, reference_usd_known_subtotal=str(cost),
                   priced_calls=24, unpriced_calls=0, event_counts={"tool.call": 30, "agent.spawn": 2})
    return evidence, metrics


class ScoringTests(unittest.TestCase):
    def test_missing_is_neutral(self):
        e = collect_evidence([], {})
        s = score(e, pow.summary([]))
        self.assertEqual(s["value"], "50.0")
        self.assertEqual(s["status"], "provisional")

    def test_retention_monotonic(self):
        values = [float(score(*fixture(ratio=r))["value"]) for r in (0, .2, .5, .8, 1)]
        self.assertEqual(values, sorted(values))
        self.assertGreater(values[-1], values[0] + 25)

    def test_cost_monotonic_and_smooth(self):
        values = [float(score(*fixture(cost=c))["value"]) for c in (.01, 1, 10, 100)]
        self.assertEqual(values, sorted(values, reverse=True))
        a, b = (float(score(*fixture(cost=c))["value"]) for c in (2, 2.01))
        self.assertLess(abs(a-b), .2)

    def test_gap_reduces_confidence(self):
        e, m = fixture()
        before = score(e, m)
        e["gaps"] = 2
        after = score(e, m)
        self.assertLess(float(after["confidence"]), float(before["confidence"]))
        self.assertLess(abs(float(after["value"])-50), abs(float(before["value"])-50))

    def test_empty_small_and_ast_ellipsis(self):
        self.assertEqual(fingerprints(b"def f(): ...", "app.py")["kind"], "python-ast")
        self.assertEqual(fingerprints(b"", "empty")["units"], [])
        self.assertEqual(fingerprints(b"x=1\n", "x.py")["units"], fingerprints(b"x = 1\n", "x.py")["units"])
        e = collect_evidence([{"type": "file.observed", "data": {"path_hash": "p", "units_before": [], "units_after": ["a"]}}], {"p": ["a"]}, 1, 1)
        self.assertLess(float(score(e, pow.summary([]))["value"]), 60)

    def test_rewrite_revert_and_deletion(self):
        def edit(before, after):
            return {"type": "file.observed", "data": {"path_hash": "p", "units_before": before, "units_after": after}}
        events = [{"type": "human.message", "event_id": "h", "data": {"tokens": 10}}, edit(["a"], ["b"]), edit(["b"], ["a"])]
        e = collect_evidence(events, {"p": ["a"]})
        self.assertEqual(e["artifact"]["retained"], 0)
        self.assertEqual(e["artifact"]["operations"], 4)
        e = collect_evidence([edit(["a"], [])], {"p": []})
        self.assertEqual(e["artifact"]["retained"], 1)

    def test_history_cohorts_and_algorithms(self):
        s = score(*fixture())
        peers = [{"score": s}] * 3
        wrong = copy.deepcopy(s)
        wrong["algorithm"] = "other"
        stats = history_stats(s, peers + [{"score": wrong}, {"score": None}])
        self.assertEqual(stats["count"], 3)
        self.assertEqual(stats["percentile"], 50)
        self.assertEqual(stats["delta"], 0)

    def test_html_escapes_payload(self):
        html = render({"title": "</script><img src=x onerror=alert(1)>"})
        self.assertNotIn("</script><img", html)
        self.assertIn("sha256-", html)
        self.assertNotIn("https://", html)

    def test_task_attempts_require_committed_evidence(self):
        events = [{"type": "task.change", "data": {"task_id": "t", "status": status, "evidence": ["p"]}}
                  for status in ("active", "completed", "active", "completed")]
        e = collect_evidence(events, {"p": ["a"]})
        self.assertEqual(e["task"]["attempts"], 2)
        self.assertEqual(e["task"]["completed"], 1)
        self.assertEqual(collect_evidence(events, {})["task"]["completed"], 0)

    def test_task_payload_bounds(self):
        with self.assertRaises(ValueError):
            pow.validate_event("task.change", {"task_id": "t", "status": "completed", "evidence": ["a" * 64] * 33})
        with self.assertRaises(ValueError):
            pow.validate_event("file.observed", {"units_before": [], "units_after": ["z" * 64]})

    def test_ladder_progress_and_diminishing_returns(self):
        s = score(*fixture())
        first = ladder_step(None, s)
        rating = first
        for _ in range(100):
            updated = ladder_step(rating, s)
            self.assertGreaterEqual(float(updated["value"]), float(rating["value"]))
            self.assertLessEqual(abs(float(updated["delta"])), 40)
            rating = updated
        self.assertLess(float(rating["delta"]), float(first["delta"]))
        self.assertLessEqual(float(rating["value"]), float(rating["target"]))

    def test_ladder_weak_results_drop_and_unknown_freezes(self):
        rating = ladder_step(None, score(*fixture()))
        weaker = ladder_step(rating, score(*fixture(ratio=.1, cost=100)))
        self.assertLess(float(weaker["value"]), float(rating["value"]))
        unknown = ladder_step(rating, None)
        self.assertEqual(unknown["value"], rating["value"])
        self.assertEqual(unknown["delta"], "0.0")
        self.assertEqual(unknown["rated_commits"], rating["rated_commits"])


class ReportTests(unittest.TestCase):
    setUp = test_protocol.ProtocolTests.setUp
    git = test_protocol.ProtocolTests.git
    commit = test_protocol.ProtocolTests.commit

    def test_score_evidence_is_not_trusted(self):
        self.commit()
        p = self.rec.seal()
        e = p["score"]["evidence"]
        e["scope"]["units"] += 100
        p["score"] = score(e, p["summary"])
        p.pop("proof_hash")
        p["proof_hash"] = pow.digest(p)
        with self.rec.connection() as db, self.assertRaises(ValueError):
            pow.verify_proof(self.root, p, self.rec._events(db, p["epoch"]))

    def test_modes_and_history(self):
        first = self.commit("first")
        self.rec.seal()
        second = self.commit("second")
        p = self.rec.seal()
        iteration = self.rec.report_data(view="iteration")
        self.assertEqual(iteration["current"]["commit"], second)
        self.assertEqual(iteration["history"][0]["commit"], first)
        self.assertEqual(iteration["statistics"]["count"], 1)
        latest = self.rec.report_data(view="latest")
        self.assertEqual(latest["history"], [])
        self.assertIsNone(latest["statistics"])
        self.assertIsNone(latest["iteration"])
        self.assertEqual(iteration["iteration"]["rated_commits"], 2)
        path = self.rec.html_report(view="latest", destination=self.root / "latest.html")
        self.assertNotIn(first, path.read_text())
        with self.assertRaises(FileExistsError):
            self.rec.html_report(destination=path)
        self.assertEqual(self.rec.proof()["proof_hash"], p["proof_hash"])

    def test_unstaged_edits_do_not_survive(self):
        self.commit("base")
        self.rec.seal()
        (self.root / "app.txt").write_text("staged")
        self.rec.sample()
        self.git("add", "app.txt")
        (self.root / "app.txt").write_text("unstaged")
        self.rec.sample()
        self.git("commit", "-qm", "staged only")
        e = self.rec.seal()["score"]["evidence"]
        self.assertEqual(e["artifact"]["operations"], 4)
        self.assertEqual(e["artifact"]["retained"], 2)

    def test_ladder_does_not_reset_outside_visible_history(self):
        self.commit("first")
        self.rec.seal()
        for _ in range(31):
            self.git("commit", "--allow-empty", "-qm", "unobserved iteration")
        self.rec.reset_boundary()
        self.rec.sample()  # Establish the new interval's uncounted baseline.
        self.commit("latest")
        self.rec.seal()
        data = self.rec.report_data()
        self.assertEqual(len(data["history"]), 30)
        self.assertTrue(all(item["score"] is None for item in data["history"]))
        self.assertEqual(data["iteration"]["rated_commits"], 2)

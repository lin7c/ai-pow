import copy
import unittest

import ai_pow as pow
from ai_pow_scoring import collect_evidence, fingerprints, history_stats, lifetime, score, ladder_step
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

    def test_resource_use_never_changes_the_score(self):
        """Spending less must not look like better work; results are unobservable."""
        values = {score(*fixture(cost=c))["value"] for c in (.01, 1, 10, 1000)}
        self.assertEqual(len(values), 1)
        evidence, metrics = fixture()
        metrics.update(event_counts={"tool.call": 9000, "agent.spawn": 500},
                       reference_usd_known_subtotal="900")
        self.assertEqual(score(evidence, metrics)["value"], score(*fixture())["value"])
        self.assertNotIn("efficiency", score(*fixture())["components"])

    def test_unobserved_dimension_cedes_its_weight(self):
        evidence, metrics = fixture()
        evidence["task"] = {"completed": 0, "attempts": 0, "declared": 0, "basis": "none"}
        ceded = score(evidence, metrics)
        self.assertEqual(ceded["dimensions"], {"scored": ["artifact", "human"], "unscored": ["task"]})
        self.assertEqual(sum(float(c["effective_weight"]) for c in ceded["components"].values()), 1)
        self.assertEqual(ceded["components"]["task"]["effective_weight"], "0.000000")
        # Retained work still reads as retained work when a dimension is absent.
        self.assertGreater(float(ceded["value"]), 70)
        weak = copy.deepcopy(evidence)
        weak["artifact"] = {"retained": 10, "operations": 100, "checked_operations": 100}
        self.assertLess(float(score(weak, metrics)["value"]), 40)

    def test_sparse_evidence_stays_near_the_neutral_prior(self):
        evidence, metrics = fixture(ratio=1, units=1, prompts=1, tasks=1)
        evidence["artifact"] = {"retained": 1, "operations": 1, "checked_operations": 1}
        self.assertLess(float(score(evidence, metrics)["value"]), 70)
        self.assertEqual(score(evidence, metrics)["status"], "provisional")

    def test_lifetime_pools_instead_of_averaging(self):
        def row(retained, operations):
            return {"summary": {"human": {"tokens_measured": 10, "messages": 1, "tokens_complete": True}},
                    "score": {"algorithm": "retention-v2",
                              "evidence": {"artifact": {"retained": retained, "operations": operations},
                                           "task": {"completed": 1, "attempts": 2}}}}
        totals = lifetime([row(9, 10), row(9, 90)])
        self.assertEqual(totals["artifact_survival"], "0.1800")
        self.assertEqual(totals["human_tokens"], 20)
        self.assertEqual(totals["task_fulfillment"], "0.5000")
        self.assertEqual(totals["commits"], 2)

    def test_lifetime_pools_interval_and_payment_facts(self):
        def row(span, sessions, paid):
            return {"summary": {"window": {"span_ms": span}, "activity": {"sessions": sessions, "runs": 1,
                                                                          "failed_tool_calls": 2, "coverage_gaps": 1},
                                "actual_usd_known_subtotal": paid, "actual_priced_calls": 1 if paid else 0}}
        totals = lifetime([row(60000, 2, "1.50"), row(30000, 1, "0.50"), row(None, 1, None)])
        self.assertEqual(totals["span_ms"], 90000)
        self.assertEqual(totals["timed_commits"], 2)
        self.assertEqual(totals["sessions"], 4)
        self.assertEqual(totals["runs"], 3)
        self.assertEqual(totals["failed_tool_calls"], 6)
        self.assertEqual(totals["actual_usd_known_subtotal"], "2.00")
        self.assertEqual(totals["actual_priced_calls"], 2)

    def test_lifetime_keeps_unknown_unknown(self):
        known = {"summary": {"human": {"tokens_measured": 5, "messages": 1, "tokens_complete": True},
                             "priced_calls": 1, "unpriced_calls": 0,
                             "reference_usd_known_subtotal": "1.25"}}
        partial = {"summary": {"human": {"tokens_complete": False}, "priced_calls": 0, "unpriced_calls": 2}}
        totals = lifetime([known, partial])
        self.assertIsNone(totals["human_tokens"])
        self.assertEqual(totals["reference_usd_known_subtotal"], "1.25")
        self.assertFalse(totals["reference_cost_complete"])
        self.assertEqual(totals["scored_commits"], 0)
        self.assertIsNone(totals["artifact_survival"])

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

    def test_ladder_is_exact_sum_from_zero(self):
        rating = None
        for value in ("81.4", "43.6", "50.0"):
            rating = ladder_step(rating, {"value": value})
            self.assertEqual(rating["delta"], value)
        self.assertEqual(rating["value"], "175.0")
        self.assertEqual(rating["starting_rating"], 0)
        self.assertNotIn("tier", rating)
        self.assertNotIn("target", rating)
        for _ in range(100):
            rating = ladder_step(rating, {"value": "81.4"})
        self.assertEqual(rating["value"], "8315.0")

    def test_ladder_has_no_extra_weighting_and_unknown_is_omitted(self):
        rating = ladder_step(None, {"value": "81.4", "confidence": "0"})
        weaker = ladder_step(rating, {"value": "20.0"})
        self.assertEqual(weaker["value"], "101.4")
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

    def test_pages_are_separate_and_carry_different_data(self):
        first = self.commit("first")
        self.rec.seal()
        second = self.commit("second")
        proof = self.rec.seal()
        commit_page = self.rec.report_data()
        # The commit page knows only this commit: no history, no cumulative total.
        self.assertEqual(commit_page["current"]["commit"], second)
        self.assertEqual(commit_page["current"]["parent"], first)
        self.assertEqual(commit_page["kind"], "commit")
        for absent in ("history", "iteration", "lifetime", "statistics"):
            self.assertNotIn(absent, commit_page)
        self.assertIn("files", commit_page["derived"])
        index = self.rec.index_data()
        self.assertEqual(index["kind"], "index")
        self.assertEqual([row["commit"] for row in index["history"]], [second, first])
        self.assertEqual(index["iteration"]["rated_commits"], 2)
        self.assertEqual(index["statistics"]["count"], 1)
        self.assertNotIn("derived", index)
        report = self.rec.html_report(destination=self.root / "commit.html")
        page = report.read_text()
        # The parent hash belongs on the proof; the project total and history do not.
        self.assertNotIn("commit-sum-v1", page)
        self.assertNotIn("Recorded commits", page)
        self.assertNotIn("Project total", page)
        summary_path = self.rec.html_index(destination=self.root / "summary.html")
        self.assertIn(first, summary_path.read_text())
        with self.assertRaises(FileExistsError):
            self.rec.html_report(destination=report)
        self.assertEqual(self.rec.proof()["proof_hash"], proof["proof_hash"])

    def test_derived_file_breakdown_names_and_rework(self):
        (self.root / "app.py").write_text("def a():\n    return 1\n")
        self.rec.sample()
        (self.root / "app.py").write_text("def a():\n    return 2\n\ndef b():\n    return 3\n")
        self.rec.sample()
        self.git("add", "app.py")
        self.git("commit", "-qm", "feature")
        self.rec.seal()
        derived = self.rec.report_data()["derived"]
        row = next(item for item in derived["files"] if item["path"] == "app.py")
        self.assertEqual(row["writes"], 2)
        self.assertTrue(row["checked"])
        self.assertEqual(row["overwritten"], 1)  # The first version of a() was replaced.
        self.assertEqual(row["retained"], 2)  # Both units of the committed file survive.
        self.assertGreaterEqual(row["operations"], 3)
        self.assertEqual(derived["result"]["added"], 1)
        self.assertTrue(any(item["kind"] == "rework" for item in derived["timeline"]))

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

    def test_legacy_algorithms_verify_under_their_own_version(self):
        """An installed newer algorithm must never re-interpret a sealed proof."""
        self.commit()
        sealed = self.rec.seal()
        self.assertEqual(sealed["score"]["algorithm"], "retention-v2")
        self.assertEqual(sealed["summary"]["algorithm"], "observed-v4")
        with self.rec.connection() as db:
            events = list(self.rec._events(db, sealed["epoch"]))
        legacy = {key: value for key, value in sealed.items() if key != "proof_hash"}
        legacy["summary"] = pow.summary(iter(events), algorithm="observed-v2")
        legacy["score"] = pow.evaluate_score(self.root, legacy, events, "balanced-v1")
        legacy["proof_hash"] = pow.digest(legacy)
        self.assertIn("efficiency", legacy["score"]["components"])
        with self.rec.connection() as db:
            checked = pow.verify_proof(self.root, legacy, self.rec._events(db, legacy["epoch"]))
        self.assertTrue(checked["integrity_verified"])
        for algorithm in ("retention-v2", "future-v9"):
            forged = {key: value for key, value in legacy.items() if key != "proof_hash"}
            forged["score"] = {**legacy["score"], "algorithm": algorithm}
            forged["proof_hash"] = pow.digest(forged)
            with self.rec.connection() as db, self.assertRaises(ValueError):
                pow.verify_proof(self.root, forged, self.rec._events(db, forged["epoch"]))

    def test_report_lifetime_pools_the_recorded_history(self):
        self.commit("first")
        first = self.rec.seal()
        self.commit("second")
        second = self.rec.seal()
        data = self.rec.index_data()
        totals = data["lifetime"]
        operations = sum(p["score"]["evidence"]["artifact"]["operations"] for p in (first, second))
        retained = sum(p["score"]["evidence"]["artifact"]["retained"] for p in (first, second))
        self.assertEqual(totals["commits"], 2)
        self.assertEqual(totals["scored_commits"], 2)
        self.assertEqual(totals["artifact_operations"], operations)
        self.assertEqual(totals["artifact_survival"], format(retained / operations, ".4f"))
        self.assertEqual(totals["algorithms"], ["retention-v2"])
        self.assertNotIn("lifetime", self.rec.report_data())

    def test_ladder_does_not_reset_outside_visible_history(self):
        self.commit("first")
        self.rec.seal()
        for _ in range(31):
            self.git("commit", "--allow-empty", "-qm", "unobserved iteration")
        self.rec.reset_boundary()
        self.rec.sample()  # Establish the new interval's uncounted baseline.
        self.commit("latest")
        self.rec.seal()
        data = self.rec.index_data(rows=31)
        self.assertEqual(len(data["history"]), 31)
        self.assertTrue(all(item["score"] is None for item in data["history"][1:]))
        self.assertEqual(data["iteration"]["rated_commits"], 2)

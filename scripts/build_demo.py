#!/usr/bin/env python3
"""Generate the offline examples: this repository's own commits, synthetic evidence."""
import hashlib
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_pow import summary
from ai_pow_scoring import score, history_stats, ladder_step, lifetime
from ai_pow_report import render, render_index

ROOT = Path(__file__).resolve().parents[1]
DAY = 86400000
# Retention, reference cost, interval minutes, sessions. Diff sizes come from Git.
SHAPES = [(.40, 14, 340, 4), (.62, 10, 210, 2), (.54, 12, 265, 3),
          (.76, 7, 120, 2), (.85, 5, 150, 2), (.89, 4, 55, 1), (.98, 2.4, 195, 2)]
FALLBACK = ["Initial recorder, protocol and verification", "Process scoring and offline commit reports",
            "Zero-based cumulative totals", "Report favicon from the masthead mark",
            "Retention-only scoring and the proof vector", "Separated report views",
            "Interval, cost and agent facts in the report"]


def commits(count):
    """Real commits, subjects and per-file diff sizes from this repository."""
    found = []
    try:
        log = subprocess.run(["git", "log", "--first-parent", "-n", str(count), "--numstat",
                              "--format=%x00%H%x1f%s%x1f%cI"], cwd=ROOT, capture_output=True,
                             text=True, timeout=20, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        log = ""
    for block in log.split("\x00")[1:]:
        head, _, rest = block.partition("\n")
        commit, subject, when = (head.split("\x1f") + ["", ""])[:3]
        files = []
        for line in rest.splitlines():
            parts = line.split("\t")
            if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
                files.append({"path": parts[2], "lines": int(parts[0]) + int(parts[1]),
                              "insertions": int(parts[0]), "deletions": int(parts[1])})
        found.append({"commit": commit, "title": subject[:120], "date": when, "files": files})
    found.reverse()
    while len(found) < count:  # A shallow clone still produces a complete example.
        index = len(found)
        title = FALLBACK[index % len(FALLBACK)]
        found.insert(0, {"commit": hashlib.sha1(title.encode()).hexdigest(), "title": title,
                         "date": "2026-08-%02dT18:20:00+00:00" % (index + 1),
                         "files": [{"path": "src/module_%d.py" % i, "lines": 80,
                                    "insertions": 60, "deletions": 20} for i in range(6)]})
    return found[-count:]


def event(kind, when, **payload):
    return {"type": kind, "time_ms": when, "data": payload,
            "event_id": hashlib.sha1(repr((kind, when, payload)).encode()).hexdigest()}


def trace(index, cost, minutes, sessions):
    """Synthetic events, reduced by the production summary reducer."""
    start = 1788000000000 + index * 3 * DAY
    step = max(1, minutes * 60000 // 160)
    clock, events, marks = start, [], []
    def add(kind, **payload):
        nonlocal clock
        clock += step
        events.append(event(kind, clock, **payload))
        return clock
    for session in range(sessions):
        marks.append({"at": add("run.start", run_id="run-%d-%d" % (index, session),
                                session_id="s-%d-%d" % (index, session), command="laintas-cli"),
                      "kind": "session", "label": "session started", "detail": "laintas-cli"})
        for _ in range(40 // sessions):
            add("human.message", tokens=90 + index * 3, token_method="tokenizer",
                session_id="s-%d-%d" % (index, session))
        for _ in range(22 // sessions):
            add("assistant.visible", tokens=80 + index, token_method="tokenizer", channel="final",
                session_id="s-%d-%d" % (index, session))
        for call in range(38 // sessions):
            add("model.usage", model="example-large" if call % 3 else "example-small",
                measurement="provider_reported", input_tokens=5200, cached_input_tokens=1800,
                output_tokens=900, reasoning_tokens=260, cache_write_tokens=400,
                reference_usd=format(cost / 38, ".6f"), actual_usd=format(cost * .55 / 38, ".6f"))
        for call in range(72 // sessions):
            name = ("shell", "read_file", "apply_patch", "search")[call % 4]
            add("tool.call", name=name, call_id="c-%d-%d-%d" % (index, session, call),
                session_id="s-%d-%d" % (index, session))
            add("tool.result", name=name, call_id="c-%d-%d-%d" % (index, session, call), ok=call % 17 != 0)
        marks.append({"at": add("run.stop", run_id="run-%d-%d" % (index, session), exit_code=0),
                      "kind": "session", "label": "session ended", "detail": "exit 0"})
    for name in ("frontend-design", "testing", "release", "review"):
        add("skill.used", name=name, basis="context_injected")
    add("tool.call", name="mcp__docs__lookup", call_id="mcp-%d" % index, mcp_server="docs")
    for child, parent in (("planner", ""), ("builder", "planner"), ("reviewer", "builder"), ("tester", "planner")):
        add("agent.spawn", agent_id=child, parent_agent_id=parent or "unknown")
    if index % 3 == 0:
        add("coverage.gap", reason="scan_exclusions_or_limits")
    return summary(events), marks, start


def derived(commit, retention, marks, start, minutes):
    """Per-file work and a timeline, shaped like the real derived report data."""
    rows, step = [], max(1, minutes * 60000 // max(4, len(commit["files"])))
    timeline = list(marks)
    for position, item in enumerate(sorted(commit["files"], key=lambda f: -f["lines"])):
        operations = max(2, item["lines"] // 4)
        retained = round(operations * min(1, retention + (position % 3) * .04))
        overwritten = operations - retained
        rows.append({"path": item["path"], "id": hashlib.sha256(item["path"].encode()).hexdigest()[:10],
                     "writes": max(1, operations // 3), "operations": operations, "retained": retained,
                     "checked": True, "overwritten": overwritten,
                     "reintroduced": 1 if overwritten > 6 and position % 4 == 0 else 0})
        if overwritten:
            timeline.append({"at": start + step * (position + 1), "kind": "rework", "label": item["path"],
                             "detail": str(overwritten) + " earlier edits overwritten"})
    tasks = ["catalog page", "checkout retry", "release notes"]
    for position, name in enumerate(tasks[:max(1, len(rows) // 4)]):
        for offset, status in enumerate(("active", "completed")):
            timeline.append({"at": start + step * (position * 2 + offset + 1), "kind": "task",
                             "label": name, "detail": status, "repeat": 1})
    timeline.sort(key=lambda item: item["at"])
    result = {"added": sum(1 for f in commit["files"] if not f["deletions"]),
              "modified": sum(1 for f in commit["files"] if f["deletions"] and f["insertions"]),
              "removed": sum(1 for f in commit["files"] if not f["insertions"]), "renamed": 0,
              "tests": sum(1 for f in commit["files"] if re.search(r"(^|/)tests?/|_test\.|\.test\.", f["path"]))}
    return {"files": rows[:40], "files_total": len(rows), "timeline": timeline[:28], "timeline_omitted": 0,
            "mcp_calls": 1, "tool_results": 72, "result": result}


def example(index, commit, shape):
    """Real subject, hash, date and diff; synthetic retention, cost and timing."""
    retention, cost, minutes, sessions = shape
    operations = max(8, min(400, sum(f["lines"] for f in commit["files"]) // 4))
    tasks = max(2, operations // 12)
    evidence = {"artifact": {"retained": round(operations * retention), "operations": operations,
                             "checked_operations": operations},
                "human": {"retained_weight": str(4000 * retention), "observed_weight": 4000,
                          "linked_prompts": 40, "prompts": 40, "attribution": "temporal-proxy"},
                "task": {"completed": round(tasks * retention), "attempts": tasks, "declared": tasks,
                         "basis": "declared-with-committed-evidence"},
                "scope": {"units": max(operations // 2, len(commit["files"])), "files": len(commit["files"])},
                "limited": False, "gaps": 1 if index % 3 == 0 else 0}
    metrics, marks, start = trace(index, cost, minutes, sessions)
    return {"commit": commit["commit"], "title": commit["title"], "date": commit["date"],
            "score": score(evidence, metrics), "summary": metrics,
            "proof_hash": hashlib.sha256(commit["commit"].encode()).hexdigest(),
            "trace_root": hashlib.sha256((commit["commit"] + "trace").encode()).hexdigest(),
            "tree": hashlib.sha256((commit["commit"] + "tree").encode()).hexdigest(),
            "boundary": "head-observed-after-commit",
            "derived": derived(commit, retention, marks, start, minutes),
            "diff": {"files": len(commit["files"]),
                     "insertions": sum(f["insertions"] for f in commit["files"]),
                     "deletions": sum(f["deletions"] for f in commit["files"])}}


def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs/demo"
    (output / "reports").mkdir(parents=True, exist_ok=True)
    for stale in (output / "reports").glob("*.html"):
        stale.unlink()  # Never leave proofs of commits this demo no longer covers.
    found = commits(len(SHAPES))
    rows = [example(i, commit, SHAPES[i]) for i, commit in enumerate(found)]
    running, history = None, []
    for index, row in enumerate(rows):
        running = ladder_step(running, row["score"])
        metrics, evidence = row["summary"], row["score"]["evidence"]
        history.append({"commit": row["commit"], "title": row["title"], "date": row["date"],
                        "score": row["score"], "total": running["value"],
                        "span_ms": metrics["window"]["span_ms"],
                        "human_tokens": metrics["human"]["tokens_measured"] + metrics["human"]["tokens_estimated"],
                        "prompts": metrics["human"]["messages"],
                        "visible_tokens": metrics["visible_ai"]["tokens_measured"] + metrics["visible_ai"]["tokens_estimated"],
                        "awc": metrics["reference_usd_known_subtotal"],
                        "model_calls": sum(b["calls"] for b in metrics["models"].values()),
                        "tool_calls": metrics["event_counts"].get("tool.call", 0),
                        "sub_agents": metrics["event_counts"].get("agent.spawn", 0),
                        "sessions": metrics["activity"]["sessions"],
                        "operations": evidence["artifact"]["operations"],
                        "retained": evidence["artifact"]["retained"]})
    history.reverse()
    for row in rows:
        page = {"project": "ai-pow", "kind": "commit", "demo": True,
                "current": {"commit": row["commit"], "title": row["title"], "date": row["date"],
                            "score": row["score"], "summary": row["summary"], "proof_hash": row["proof_hash"],
                            "parent": None, "tree": row["tree"], "trace_root": row["trace_root"],
                            "boundary": row["boundary"]},
                "verification": {"integrity_verified": False, "git_tree_verified": False,
                                 "events": sum(row["summary"]["event_counts"].values()),
                                 "trust": "local-self-reported"},
                "derived": row["derived"], "diff": row["diff"], "links": {"index": "../index.html"}}
        index = rows.index(row)
        if index:
            page["current"]["parent"] = rows[index - 1]["commit"]
        (output / "reports" / (row["commit"] + ".html")).write_text(render(page), encoding="utf-8")
    summary_page = {"project": "ai-pow", "kind": "index", "demo": True,
                    "lifetime": lifetime(rows), "iteration": running, "history": history,
                    "commits_in_history": len(rows),
                    "statistics": history_stats(history[0]["score"], history[1:]),
                    "span": {"first": {"commit": rows[0]["commit"], "date": rows[0]["date"]},
                             "last": {"commit": rows[-1]["commit"], "date": rows[-1]["date"]}},
                    "links": {"commit": "reports/"}}
    (output / "index.html").write_text(render_index(summary_page), encoding="utf-8")
    for row in rows:
        print(row["score"]["value"], row["score"]["grade"], len(row["derived"]["files"]), "files |", row["title"])
    print("Demo output:", output)


if __name__ == "__main__":
    main()

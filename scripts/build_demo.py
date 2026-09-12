#!/usr/bin/env python3
"""Generate the offline examples: this repository's own commit subjects, synthetic evidence."""
import hashlib
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_pow import summary
from ai_pow_scoring import score, history_stats, ladder_step, lifetime
from ai_pow_report import render

ROOT = Path(__file__).resolve().parents[1]
DAY = 86400000
# Retention, reference cost, observed operations, interval minutes, sessions.
# Retention, reference cost, interval minutes, sessions. Diff size comes from Git.
SHAPES = [(.40, 14, 340, 4), (.62, 10, 210, 2), (.54, 12, 265, 3),
          (.76, 7, 120, 2), (.85, 5, 150, 2), (.89, 4, 55, 1), (.98, 2.4, 195, 2)]
FALLBACK = ["Initial recorder, protocol and verification", "Process scoring and offline commit reports",
            "Zero-based cumulative totals", "Report favicon from the masthead mark",
            "Retention-only scoring and the proof vector", "Separated report views",
            "Interval, cost and agent facts in the report"]


def commits(count):
    """Real commits from this repository, so the example is about this project."""
    try:
        log = subprocess.run(["git", "log", "--first-parent", "--shortstat", "-n", str(count),
                              "--format=%x00%H%x1f%s%x1f%cI"], cwd=ROOT, capture_output=True,
                             text=True, timeout=20, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        log = ""
    found = []
    for block in log.split("\x00")[1:]:
        head, _, rest = block.partition("\n")
        commit, subject, when = (head.split("\x1f") + ["", ""])[:3]
        numbers = {}
        for field, word in (("files", "file"), ("insertions", "insertion"), ("deletions", "deletion")):
            match = re.search(r"(\d+) " + word, rest)
            numbers[field] = int(match.group(1)) if match else 0
        found.append({"commit": commit, "title": subject[:120], "date": when, **numbers})
    found.reverse()
    while len(found) < count:  # A shallow clone still produces a complete example.
        index = len(found)
        title = FALLBACK[index % len(FALLBACK)]
        found.insert(0, {"commit": hashlib.sha1(title.encode()).hexdigest(), "title": title,
                         "date": "2026-08-%02dT18:20:00+00:00" % (index + 1),
                         "files": 6, "insertions": 320, "deletions": 90})
    return found[-count:]


def event(kind, when, **payload):
    return {"type": kind, "time_ms": when, "data": payload,
            "event_id": hashlib.sha1(repr((kind, when, payload)).encode()).hexdigest()}


def trace(index, cost, minutes, sessions):
    """Synthetic events, reduced by the production summary reducer."""
    start = 1788000000000 + index * 3 * DAY
    step = max(1, minutes * 60000 // 160)
    clock, events = start, []
    def add(kind, **payload):
        nonlocal clock
        clock += step
        events.append(event(kind, clock, **payload))
    for session in range(sessions):
        add("run.start", run_id="run-%d-%d" % (index, session), session_id="s-%d-%d" % (index, session),
            command="laintas-cli")
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
        add("run.stop", run_id="run-%d-%d" % (index, session), exit_code=0)
    for name in ("frontend-design", "testing", "release", "review"):
        add("skill.used", name=name, basis="context_injected")
    add("tool.call", name="mcp__docs__lookup", call_id="mcp-%d" % index, mcp_server="docs")
    for child, parent in (("planner", ""), ("builder", "planner"), ("reviewer", "builder"), ("tester", "planner")):
        add("agent.spawn", agent_id=child, parent_agent_id=parent or "unknown")
    if index % 3 == 0:
        add("coverage.gap", reason="scan_exclusions_or_limits")
    return summary(events)


def example(index, commit, shape):
    """Real subject, hash, date and diff size; synthetic retention, cost and timing."""
    retention, cost, minutes, sessions = shape
    operations = max(8, min(400, (commit["insertions"] + commit["deletions"]) // 4))
    tasks = max(2, operations // 12)
    evidence = {"artifact": {"retained": round(operations * retention), "operations": operations,
                             "checked_operations": operations},
                "human": {"retained_weight": str(4000 * retention), "observed_weight": 4000,
                          "linked_prompts": 40, "prompts": 40, "attribution": "temporal-proxy"},
                "task": {"completed": round(tasks * retention), "attempts": tasks, "declared": tasks,
                         "basis": "declared-with-committed-evidence"},
                "scope": {"units": max(operations // 2, commit["files"]), "files": commit["files"]},
                "limited": False, "gaps": 1 if index % 3 == 0 else 0}
    metrics = trace(index, cost, minutes, sessions)
    return {"commit": commit["commit"], "title": commit["title"], "date": commit["date"],
            "score": score(evidence, metrics), "summary": metrics,
            "proof_hash": hashlib.sha256(commit["commit"].encode()).hexdigest(), "diff": commit}


def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs/demo"
    output.mkdir(parents=True, exist_ok=True)
    rows = [example(i, commit, SHAPES[i]) for i, commit in enumerate(commits(len(SHAPES)))]
    rating = None
    for row in rows:
        rating = ladder_step(rating, row["score"])
        row["iteration"] = rating
    current, history = rows[-1], list(reversed(rows[:-1]))
    diff = current["diff"]
    data = {"project": "ai-pow", "view": "iteration", "current": current, "history": history,
            "statistics": history_stats(current["score"], history), "iteration": rating,
            "lifetime": lifetime(rows), "diff": {"files": diff["files"], "insertions": diff["insertions"], "deletions": diff["deletions"]},
            "verification": {"integrity_verified": False}, "demo": True}
    (output / "index.html").write_text(render(data), encoding="utf-8")
    current = {key: value for key, value in current.items() if key != "iteration"}
    data.update(view="latest", current=current, history=[], statistics=None, iteration=None, lifetime=None)
    (output / "latest.html").write_text(render(data), encoding="utf-8")
    for row in rows:
        print(row["score"]["value"], row["score"]["grade"], row["diff"]["files"], "files |", row["title"])
    print("Demo output:", output)


if __name__ == "__main__":
    main()

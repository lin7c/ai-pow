#!/usr/bin/env python3
"""Generate explicitly synthetic, offline examples using the shipping reducers."""
import hashlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_pow import summary
from ai_pow_scoring import score, history_stats, ladder_step, lifetime
from ai_pow_report import render


def event(kind, **data):
    return {"type": kind, "data": data, "event_id": hashlib.sha1(repr((kind, data)).encode()).hexdigest()}


def trace(index, cost):
    """Synthetic events, reduced by the production summary reducer."""
    events = [event("human.message", tokens=90 + index * 3, token_method="tokenizer") for _ in range(40)]
    events += [event("assistant.visible", tokens=80 + index, token_method="tokenizer", channel="final") for _ in range(22)]
    for call in range(38):
        events.append(event("model.usage", model="example-large" if call % 3 else "example-small",
                            measurement="provider_reported", input_tokens=5200, cached_input_tokens=1800,
                            output_tokens=900, reasoning_tokens=260, cache_write_tokens=0,
                            reference_usd=format(cost / 38, ".6f")))
    for call in range(72):
        events.append(event("tool.call", name=("shell", "read_file", "apply_patch", "search")[call % 4],
                            call_id=str(call)))
    events += [event("skill.used", name=name) for name in ("frontend-design", "testing", "release", "review")]
    events += [event("tool.call", name="mcp__docs__lookup", call_id="mcp", mcp_server="docs")]
    for agent, parent in (("planner", ""), ("builder", "planner"), ("reviewer", "builder"), ("tester", "planner")):
        events.append(event("agent.spawn", agent_id=agent, parent_agent_id=parent or "unknown"))
    return summary(events)


def example(ratio, cost, index, title, operations):
    """Commits differ in size, so pooled totals cannot equal a mean of ratios."""
    tasks = max(2, operations // 12)
    evidence = {"artifact": {"retained": round(operations * ratio), "operations": operations,
                             "checked_operations": operations},
                "human": {"retained_weight": str(4000 * ratio), "observed_weight": 4000,
                          "linked_prompts": 40, "prompts": 40, "attribution": "temporal-proxy"},
                "task": {"completed": round(tasks * ratio), "attempts": tasks, "declared": tasks,
                         "basis": "declared-with-committed-evidence"},
                "scope": {"units": operations // 2, "files": max(1, operations // 16)},
                "limited": False, "gaps": 0}
    metrics = trace(index, cost)
    return {"commit": hashlib.sha1(title.encode()).hexdigest(), "title": title,
            "date": f"2026-09-{index + 1:02d}T10:30:00+00:00", "score": score(evidence, metrics),
            "summary": metrics, "proof_hash": hashlib.sha256(title.encode()).hexdigest()}


def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "docs/demo"
    output.mkdir(parents=True, exist_ok=True)
    specs = [(.40, 14, "Establish the catalog and checkout foundation", 240),
             (.62, 10, "Connect product search and inventory state", 150),
             (.54, 12, "Rework checkout around payment retries", 190),
             (.76, 7, "Make checkout failures recoverable", 96),
             (.85, 5, "Add receipt delivery and order tracking", 130),
             (.89, 4, "Improve account flows and test coverage", 44),
             (.98, 2.4, "Ship a calmer, more reliable checkout", 175)]
    rows = [example(ratio, cost, i, title, operations)
            for i, (ratio, cost, title, operations) in enumerate(specs)]
    rating = None
    for row in rows:
        rating = ladder_step(rating, row["score"])
        row["iteration"] = rating
    current, history = rows[-1], list(reversed(rows[:-1]))
    data = {"project": "fieldwork / commerce", "view": "iteration", "current": current, "history": history,
            "statistics": history_stats(current["score"], history), "iteration": rating,
            "lifetime": lifetime(rows), "verification": {"integrity_verified": False}, "demo": True}
    (output / "index.html").write_text(render(data), encoding="utf-8")
    current = {key: value for key, value in current.items() if key != "iteration"}
    data.update(view="latest", current=current, history=[], statistics=None, iteration=None, lifetime=None)
    (output / "latest.html").write_text(render(data), encoding="utf-8")
    for row in rows:
        print(row["score"]["value"], row["score"]["grade"], row["title"])
    print("Demo output:", output)


if __name__ == "__main__":
    main()

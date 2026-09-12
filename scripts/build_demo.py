#!/usr/bin/env python3
"""Generate explicitly synthetic, offline examples using the shipping score policy."""
import hashlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_pow import summary
from ai_pow_scoring import score, history_stats, ladder_step
from ai_pow_report import render


def example(ratio, cost, index, title):
    evidence = {"artifact": {"retained": round(180 * ratio), "operations": 180, "checked_operations": 180},
                "human": {"retained_weight": str(4000 * ratio), "observed_weight": 4000,
                          "linked_prompts": 40, "prompts": 40, "attribution": "temporal-proxy"},
                "task": {"completed": round(20 * ratio), "attempts": 20, "declared": 20,
                         "basis": "declared-with-committed-evidence"},
                "scope": {"units": 96, "files": 12}, "limited": False, "gaps": 0}
    metrics = summary([])
    metrics.update(human={"events": 40, "messages": 40, "tokens_measured": 4210, "tokens_estimated": 0, "tokens_complete": True},
                   visible_ai={"events": 22, "tokens_measured": 1820, "tokens_estimated": 0, "tokens_complete": True},
                   reference_cost_complete_for_observed_calls=True, reference_usd_known_subtotal=str(cost),
                   priced_calls=38, unpriced_calls=0, event_counts={"tool.call": 72, "agent.spawn": 4})
    return {"commit": hashlib.sha1(title.encode()).hexdigest(), "title": title,
            "date": f"2026-09-{index + 1:02d}T10:30:00+00:00", "score": score(evidence, metrics),
            "summary": metrics, "proof_hash": hashlib.sha256(title.encode()).hexdigest()}


def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "docs/demo"
    output.mkdir(parents=True, exist_ok=True)
    specs = [(.40, 14, "Establish the catalog and checkout foundation"),
             (.62, 10, "Connect product search and inventory state"),
             (.54, 12, "Rework checkout around payment retries"),
             (.76, 7, "Make checkout failures recoverable"),
             (.85, 5, "Add receipt delivery and order tracking"),
             (.89, 4, "Improve account flows and test coverage"),
             (.98, 2.4, "Ship a calmer, more reliable checkout")]
    rows = [example(ratio, cost, i, title) for i, (ratio, cost, title) in enumerate(specs)]
    rating = None
    for row in rows:
        rating = ladder_step(rating, row["score"])
        row["iteration"] = rating
    current, history = rows[-1], list(reversed(rows[:-1]))
    data = {"project": "fieldwork / commerce", "view": "iteration", "current": current, "history": history,
            "statistics": history_stats(current["score"], history), "iteration": rating,
            "verification": {"integrity_verified": False}, "demo": True}
    (output / "index.html").write_text(render(data), encoding="utf-8")
    current = {key: value for key, value in current.items() if key != "iteration"}
    data.update(view="latest", current=current, history=[], statistics=None, iteration=None)
    (output / "latest.html").write_text(render(data), encoding="utf-8")
    for row in rows:
        print(row["score"]["value"], row["score"]["grade"], row["title"])
    print("Demo output:", output)


if __name__ == "__main__":
    main()

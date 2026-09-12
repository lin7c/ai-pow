# SPDX-License-Identifier: MIT
"""Versioned process scoring. Evidence is separate from the policy interpreting it."""
import ast
from collections import Counter
import hashlib
import json
import math

ALGORITHM = "balanced-v1"
WEIGHTS = {"human": .28, "artifact": .28, "task": .14, "efficiency": .30}
LABELS = {"human": "Input retention", "artifact": "Artifact survival",
          "task": "Task fulfillment", "efficiency": "Resource discipline"}


def fingerprints(content, name):
    """At most 64 structural/content units; never retain source text."""
    kind = "content-blocks"
    try:
        text = content.decode("utf-8")
        if name.endswith(".py"):
            try:
                tree = ast.parse(text)
                def stable(node):
                    if isinstance(node, ast.AST):
                        return {"node": type(node).__name__, **{key: stable(value) for key, value in ast.iter_fields(node)
                                if value is not None and value != []}}
                    if isinstance(node, list):
                        return [stable(item) for item in node]
                    if isinstance(node, (bytes, complex)) or node is Ellipsis:
                        return repr(node)
                    return node
                units = [json.dumps(stable(node), sort_keys=True, ensure_ascii=True) for node in tree.body]
                kind = "python-ast"
            except (SyntaxError, ValueError, RecursionError):
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                units = ["\n".join(lines[i:i + 8]) for i in range(0, len(lines), 8)]
        else:
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            units = ["\n".join(lines[i:i + 8]) for i in range(0, len(lines), 8)]
        hashes = [hashlib.sha256(unit.encode()).hexdigest() for unit in units[:64]]
    except (UnicodeError, RecursionError):
        kind = "binary-blocks"
        units = range(0, len(content), 4096)
        hashes = [hashlib.sha256(content[i:i + 4096]).hexdigest() for i in list(units)[:64]]
    return {"units": sorted(set(hashes)), "kind": kind, "truncated": len(units) > 64}


def collect_evidence(events, final_units, scope_units=0, scope_files=0, limited=False):
    """Retain final lineage, including deletion tombstones, against the actual tree.

    Input ownership is temporal unless an adapter supplies prompt_id. This is a
    retention proxy, not an assertion of semantic entailment or causality.
    """
    baseline, operations, lineage, prompts, tasks = {}, Counter(), {}, {}, {}
    current_prompt = None
    total_ops = 0
    gaps = 0
    for event in events:
        data, kind = event["data"], event["type"]
        if kind == "human.message":
            current_prompt = event["event_id"]
            prompts[current_prompt] = {"weight": max(1, data.get("tokens") or 1), "raw": 0, "retained": 0}
        elif kind == "coverage.gap":
            gaps += 1
        elif kind == "file.observed":
            path = data["path_hash"]
            if "units_before" not in data or "units_after" not in data:
                limited = True
                continue
            before, after = set(data["units_before"]), set(data["units_after"])
            baseline.setdefault(path, before)
            owner = data.get("prompt_id") or current_prompt
            for action, units in (("add", after - before), ("remove", before - after)):
                for unit in units:
                    total_ops += 1
                    operations[path] += 1
                    lineage[(path, action, unit)] = owner
                    if owner in prompts:
                        prompts[owner]["raw"] += 1
            limited = limited or data.get("units_truncated", False)
        elif kind == "task.change" and data.get("task_id") and data.get("status"):
            key = data["task_id"]
            old = tasks.get(key)
            attempts = (old["attempts"] if old else 1)
            if old and old["status"] in {"completed", "dropped"} and data["status"] == "active":
                attempts += 1
            tasks[key] = {"status": data["status"], "attempts": attempts,
                          "evidence": data.get("evidence", [])}
    retained = 0
    checked_ops = 0
    for path, before in baseline.items():
        if path not in final_units:
            limited = True
            continue
        after = set(final_units[path])
        checked_ops += operations[path]
        for action, units in (("add", after - before), ("remove", before - after)):
            for unit in units:
                key = (path, action, unit)
                if key not in lineage:
                    continue
                retained += 1
                owner = lineage[key]
                if owner in prompts:
                    prompts[owner]["retained"] += 1
    observed_prompts = [p for p in prompts.values() if p["raw"]]
    prompt_weight = sum(p["weight"] for p in observed_prompts)
    kept_weight = sum(p["weight"] * p["retained"] / p["raw"] for p in observed_prompts)
    completed = sum(1 for t in tasks.values() if t["status"] == "completed"
                    and t["evidence"] and all(path in final_units and final_units[path] for path in t["evidence"]))
    return {"artifact": {"retained": retained, "operations": total_ops, "checked_operations": checked_ops},
            "human": {"retained_weight": format(kept_weight, ".6f"), "observed_weight": prompt_weight,
                      "linked_prompts": len(observed_prompts), "prompts": len(prompts), "attribution": "temporal-proxy"},
            "task": {"completed": completed, "attempts": sum(t["attempts"] for t in tasks.values()),
                     "declared": len(tasks), "basis": "declared-with-committed-evidence"},
            "scope": {"units": max(scope_units, retained), "files": scope_files}, "limited": bool(limited), "gaps": gaps}


def grade(score):
    return next(label for threshold, label in ((90, "S"), (80, "A"), (65, "B"), (50, "C"), (35, "D"), (0, "E")) if score >= threshold)


def score(evidence, metrics):
    """Smooth 0–100 score with a neutral 50 prior and explicit confidence.

    Missing dimensions keep their weight and neutral prior. Observed retention
    uses Beta(2,2) smoothing; evidence never silently becomes a perfect score.
    """
    parts = {}
    def retain(key, numerator, denominator, reliability=1):
        ratio = numerator / denominator if denominator else None
        quality = (numerator + 2) / (denominator + 4) if denominator else .5
        confidence = (denominator / (denominator + 4) if denominator else 0) * reliability
        parts[key] = {"label": LABELS[key], "weight": str(WEIGHTS[key]),
                      "ratio": None if ratio is None else format(ratio, ".6f"),
                      "quality": format(quality, ".6f"), "confidence": format(confidence, ".6f")}
    art, human, task = (evidence[k] for k in ("artifact", "human", "task"))
    coverage = art["checked_operations"] / art["operations"] if art["operations"] else 0
    retain("artifact", art["retained"], art["operations"], coverage * (.8 if evidence["limited"] else 1))
    # Token mass weights prompts, but sample confidence depends on prompt count.
    hratio = float(human["retained_weight"]) / human["observed_weight"] if human["observed_weight"] else 0
    retain("human", hratio * human["linked_prompts"], human["linked_prompts"],
           .7 * (human["linked_prompts"] / human["prompts"] if human["prompts"] else 0))
    retain("task", task["completed"], task["attempts"])
    scope = max(1.0, math.sqrt(evidence["scope"]["units"]))
    resources = []
    for label, name, anchor, weight in (("Human input", "human", 800, .25), ("Visible output", "visible_ai", 1200, .15)):
        bucket = metrics[name]
        if bucket.get("events", bucket.get("messages", 0)) and bucket.get("tokens_complete", True):
            tokens = bucket.get("tokens_estimated", 0) + bucket.get("tokens_measured", 0)
            resources.append((label, tokens / (anchor * scope), weight))
    if metrics.get("reference_cost_complete_for_observed_calls"):
        resources.append(("Reference compute", float(metrics["reference_usd_known_subtotal"]) / (.5 * scope), .45))
    elif metrics.get("models") and all(m.get("input_tokens") is not None and m.get("output_tokens") is not None for m in metrics["models"].values()):
        tokens = sum(m["input_tokens"] + m["output_tokens"] + (m.get("cache_write_tokens") or 0) for m in metrics["models"].values())
        resources.append(("Model tokens (fallback)", tokens / (40000 * scope), .45))
    tool_calls = metrics.get("event_counts", {}).get("tool.call", 0)
    if tool_calls:
        resources.append(("Tool dispatches", tool_calls / (12 * scope), .15))
    available = sum(r[2] for r in resources)
    quality = sum(w / (1 + pressure ** .7) for _, pressure, w in resources) + .5 * (1 - available)
    confidence = available * min(1, evidence["scope"]["units"] / 8)
    parts["efficiency"] = {"label": LABELS["efficiency"], "weight": ".3", "ratio": format(quality, ".6f"),
                           "quality": format(quality, ".6f"), "confidence": format(confidence, ".6f"),
                           "resources": [{"name": name, "pressure": format(p, ".5f")} for name, p, _ in resources]}
    if evidence.get("gaps"):
        for part in parts.values():
            part["confidence"] = format(float(part["confidence"]) / (1 + evidence["gaps"]), ".6f")
    # Every component contributes around neutral; retain the missing-data penalty.
    latent = .5 + sum(WEIGHTS[k] * float(p["confidence"]) * (float(p["quality"]) - .5) for k, p in parts.items())
    value = 100 / (1 + math.exp(-5 * (latent - .5)))
    confidence = sum(WEIGHTS[k] * float(p["confidence"]) for k, p in parts.items())
    units = evidence["scope"]["units"]
    cohort = "small" if units < 8 else "medium" if units < 32 else "large" if units < 128 else "extensive"
    return {"algorithm": ALGORITHM, "value": format(value, ".1f"), "grade": grade(round(value, 1)),
            "confidence": format(confidence, ".4f"), "status": "provisional" if confidence < .65 else "established",
            "cohort": cohort, "components": parts, "evidence": evidence,
            "meaning": "process-retention-and-resource-score", "quality_verified": False}


def history_stats(current, history):
    comparable = [p for p in history if p.get("score") and p["score"]["algorithm"] == current["algorithm"]]
    values = [float(p["score"]["value"]) for p in comparable]
    peers = [p for p in comparable if p["score"]["cohort"] == current["cohort"]]
    value = float(current["value"])
    percentile = (sum(float(p["score"]["value"]) < value for p in peers)
                  + .5 * sum(float(p["score"]["value"]) == value for p in peers)) / len(peers) * 100 if peers else None
    return {"count": len(values), "average": round(sum(values) / len(values), 1) if values else None,
            "delta": round(value - values[0], 1) if values else None,
            "peer_count": len(peers), "peer_average": round(sum(float(p["score"]["value"]) for p in peers) / len(peers), 1) if peers else None,
            "percentile": round(percentile, 1) if percentile is not None and len(peers) >= 3 else None,
            "same_grade": sum(p["score"]["grade"] == current["grade"] for p in comparable)}


def ladder_step(previous, commit_score):
    """Project-local, bounded rating movement. Not Elo: there are no opponents.

    Missing evidence never earns a participation bonus. Repeated strong work
    approaches a score-dependent target, with diminishing gains rather than
    unbounded credit for producing commits.
    """
    before = float(previous["value"]) if previous else 1000.0
    count = previous["rated_commits"] if previous else 0
    eligible = bool(commit_score and commit_score["evidence"]["artifact"]["checked_operations"]
                    and commit_score["evidence"]["scope"]["units"])
    movement = 0.0
    target = None
    if eligible:
        target = 1000 + 25 * (float(commit_score["value"]) - 50)
        confidence = float(commit_score["confidence"])
        scope_factor = min(1, commit_score["evidence"]["scope"]["units"] / 8)
        movement = 40 * math.tanh((target - before) / 300) * confidence ** 2 * scope_factor
        count += 1
    value = round(before + movement, 1)
    tiers = ((1750, "Diamond"), (1500, "Platinum"), (1300, "Gold"), (1100, "Silver"), (0, "Bronze"))
    tier = next(label for threshold, label in tiers if value >= threshold)
    next_tier = next(((threshold, label) for threshold, label in reversed(tiers) if threshold > value), None)
    return {"algorithm": "ladder-v1", "value": format(value, ".1f"),
            "previous": format(before, ".1f"), "delta": format(value - before, ".1f"),
            "target": None if target is None else format(target, ".1f"),
            "tier": tier, "next_tier": None if next_tier is None else next_tier[1],
            "next_threshold": None if next_tier is None else next_tier[0],
            "rated_commits": count, "eligible": eligible, "starting_rating": 1000}

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 AI-PoW contributors
"""AI-PoW 0.3: dependency-free process scoring and local provenance.

This file is also vendored into laintas-cli. No daemon, network or model calls.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from contextlib import contextmanager
from decimal import Decimal, localcontext
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import sqlite3
import stat
import subprocess
import sys
import threading
import time
import uuid

VERSION = "0.1.0"
APP_VERSION = "0.3.0"
ZERO = "0" * 64
MAX_EVENT = 16 * 1024
MAX_FILES = 2000
MAX_FILE = 256 * 1024
SCAN_BYTES = 16 * 1024 * 1024
MAX_GIT_OUTPUT = 2 * 1024 * 1024
TYPES = {"human.message", "assistant.visible", "model.usage", "tool.call",
         "tool.result", "agent.spawn", "agent.stop", "skill.used", "task.change",
         "run.start", "run.stop", "file.observed", "coverage.gap"}
EXCLUDED = {".git", ".ai-pow", ".laintas", ".claude", ".codex", "node_modules",
            "vendor", ".venv", "venv", "dist", "build", "__pycache__"}


def canonical(value):
    """Protocol JSON: UTF-8, sorted keys, no whitespace, no floats."""
    def check(v):
        if v is None or isinstance(v, (str, bool)):
            return
        if type(v) is int and abs(v) <= 2**53 - 1:
            return
        if isinstance(v, list):
            for item in v:
                check(item)
            return
        if isinstance(v, dict) and all(isinstance(k, str) for k in v):
            for item in v.values():
                check(item)
            return
        raise ValueError("Protocol values must be strings, safe integers, booleans or null")
    check(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def text_meta(text):
    # No tokenizer is falsely presented as a provider's tokenizer.
    text = str(text or "")
    raw = text.encode("utf-8")
    return {"bytes": len(raw), "characters": len(text),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "tokens": (len(raw) + 3) // 4, "token_method": "utf8-bytes/4-estimate"}


def git(root, *args, limit=MAX_GIT_OUTPUT, allow_fail=False):
    # Spool-free bounded reader; kill and reap even on excessive output/timeouts.
    proc = subprocess.Popen(["git", "-C", str(root), *args], stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)
    timer = threading.Timer(10, proc.kill)
    timer.daemon = True
    timer.start()
    try:
        data = proc.stdout.read(limit + 1)
        if len(data) > limit:
            raise ValueError("Git output exceeds recorder limit")
        code = proc.wait()
        if code and not allow_fail:
            raise ValueError("Git command failed: " + args[0])
        return data if code == 0 else None
    finally:
        timer.cancel()
        timer.join()
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        proc.stdout.close()


def repo_paths(cwd):
    root = Path(git(cwd, "rev-parse", "--show-toplevel").decode().strip())
    gd = Path(git(root, "rev-parse", "--absolute-git-dir").decode().strip())
    return root, gd / "ai-pow"


def head(root):
    raw = git(root, "rev-parse", "--verify", "HEAD", allow_fail=True)
    return raw.decode().strip() if raw else None


def commit_meta(root, ref):
    raw = git(root, "show", "-s", "--format=%H%n%T%n%P", ref).decode().splitlines()
    return {"commit": raw[0], "tree": raw[1], "parents": raw[2].split() if len(raw) > 2 else []}


def validate_event(kind, data):
    if kind not in TYPES or not isinstance(data, dict):
        raise ValueError("Unknown event type or invalid data")
    if len(canonical(data)) > MAX_EVENT - 1024:
        raise ValueError("Event exceeds 16 KiB limit")
    for key in ("tokens", "input_tokens", "output_tokens", "cached_input_tokens",
                "reasoning_tokens", "cache_write_tokens", "bytes", "characters"):
        if key in data and data[key] is not None:
            if type(data[key]) is not int or data[key] < 0:
                raise ValueError("Invalid non-negative token count: " + key)
    if kind in {"human.message", "assistant.visible"}:
        method = data.get("token_method")
        if method is not None and (not isinstance(method, str) or not method):
            raise ValueError("token_method must name a tokenizer or estimation method")
        if method == "utf8-bytes/4-estimate":
            if type(data.get("bytes")) is not int or data.get("tokens") != (data["bytes"] + 3) // 4:
                raise ValueError("Byte-based token estimate is inconsistent")
    if kind == "task.change" and "status" in data:
        if data["status"] not in {"active", "completed", "dropped"} or not isinstance(data.get("task_id"), str) or not 1 <= len(data["task_id"]) <= 256:
            raise ValueError("A task needs a stable task_id and active/completed/dropped status")
        if not isinstance(data.get("evidence", []), list) or len(data.get("evidence", [])) > 32 or any(not isinstance(p, str) or len(p) != 64 or any(c not in "0123456789abcdef" for c in p) for p in data.get("evidence", [])):
            raise ValueError("Task evidence must contain SHA-256 path identifiers")
    if kind == "file.observed" and "units_before" in data:
        for key in ("units_before", "units_after"):
            units = data.get(key)
            if not isinstance(units, list) or len(units) > 64 or any(not isinstance(p, str) or len(p) != 64 or any(c not in "0123456789abcdef" for c in p) for p in units):
                raise ValueError("Artifact units must be bounded SHA-256 identifiers")
    if kind == "model.usage":
        if not data.get("model") or data.get("measurement") not in {"provider_reported", "estimated"}:
            raise ValueError("Model usage needs model and measurement")
        i, c = data.get("input_tokens"), data.get("cached_input_tokens")
        o, r = data.get("output_tokens"), data.get("reasoning_tokens")
        if i is not None and c is not None and c > i:
            raise ValueError("Cache read tokens must be a subset of input_tokens")
        if o is not None and r is not None and r > o:
            raise ValueError("Reasoning must be a subset of output_tokens")
        for key in ("reference_usd", "actual_usd"):
            if data.get(key) is not None:
                cost = Decimal(data[key])
                if not isinstance(data[key], str) or not cost.is_finite() or cost < 0:
                    raise ValueError("Costs must be finite non-negative decimal strings")
        if data.get("reference_usd") is not None and not data.get("price_snapshot"):
            raise ValueError("Reference cost requires an explicit price snapshot")
        if data.get("reference_usd") is not None:
            price = data["price_snapshot"]
            expected = price_usage({k: v for k, v in data.items() if k != "reference_usd"}, price)
            if (price["model"] != data["model"] or data.get("price_snapshot_hash") != digest(price)
                    or expected.get("reference_usd") != data["reference_usd"]):
                raise ValueError("Reference cost does not match usage and price snapshot")


def validate_price(price):
    required = ("model", "source_url", "effective_date", "input_per_million",
                "cached_input_per_million", "cache_write_per_million", "output_per_million")
    if not isinstance(price, dict) or any(k not in price for k in required):
        raise ValueError("Price snapshot missing required fields")
    canonical(price)
    if not str(price["source_url"]).startswith("https://"):
        raise ValueError("Price source must be an HTTPS URL")
    for k in required[3:]:
        value = Decimal(price[k])
        if not isinstance(price[k], str) or not value.is_finite() or value < 0:
            raise ValueError("Price rates must be non-negative decimal strings")


def price_usage(data, price):
    validate_price(price)
    fields = ("input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens")
    if any(data.get(k) is None for k in fields):
        return data
    i, c, w, o = (data[k] for k in fields)
    with localcontext() as ctx:
        ctx.prec = 80
        total = ((i - c) * Decimal(price["input_per_million"])
                 + c * Decimal(price["cached_input_per_million"])
                 + w * Decimal(price["cache_write_per_million"])
                 + o * Decimal(price["output_per_million"])) / Decimal(1000000)
    return {**data, "reference_usd": str(total), "price_snapshot": price,
            "price_snapshot_hash": digest(price)}


def _summary_v1(events):
    counts, models = {}, {}
    human = {"messages": 0, "tokens_estimated": 0, "tokens_measured": 0}
    visible = {"events": 0, "tokens_estimated": 0, "tokens_measured": 0}
    tools, skills, mcps = set(), set(), set()
    total_cost, priced = Decimal(0), 0
    for e in events:
        k, d = e["type"], e["data"]
        counts[k] = counts.get(k, 0) + 1
        if k in {"human.message", "assistant.visible"}:
            dest = human if k == "human.message" else visible
            dest["messages" if k == "human.message" else "events"] += 1
            field = "tokens_estimated" if "estimate" in (d.get("token_method") or "estimate") else "tokens_measured"
            dest[field] += d.get("tokens") or 0
        if k == "tool.call":
            tools.add(d.get("name", "unknown"))
            if d.get("mcp_server"):
                mcps.add(d["mcp_server"])
        if k == "skill.used":
            skills.add(d.get("name", "unknown"))
        if k == "model.usage":
            # Do not combine provider-reported and estimated token totals.
            key = d["model"] + "/" + d["measurement"]
            m = models.setdefault(key, {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                                        "cached_input_tokens": 0, "reasoning_tokens": 0,
                                        "cache_write_tokens": 0, "unknown_fields": []})
            m["calls"] += 1
            for field in ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens", "cache_write_tokens"):
                if d.get(field) is None:
                    if field not in m["unknown_fields"]:
                        m["unknown_fields"].append(field)
                else:
                    m[field] += d[field]
            if d.get("reference_usd") is not None:
                priced += 1
                total_cost += Decimal(d["reference_usd"])
    return {"human": human, "visible_ai": visible, "models": models,
            "reference_usd_known_subtotal": str(total_cost) if priced else None,
            "priced_calls": priced, "unpriced_calls": counts.get("model.usage", 0) - priced,
            "tools_used": sorted(tools), "skills_used": sorted(skills), "mcp_used": sorted(mcps),
            "event_counts": counts,
            "human_survival": None, "artifact_survival": None, "task_survival": None,
            "semantic_edits": None, "quality": None}


def summary(events, algorithm="observed-v2"):
    """Keep unknown totals null and make byte estimates stream-chunk invariant.

    Retain the original reducer for verification of proofs created before the
    accounting review. A new report never silently rewrites an old proof.
    """
    if algorithm == "observed-v1":
        with localcontext() as ctx:
            ctx.prec = 28
            return _summary_v1(events)
    if algorithm != "observed-v2":
        raise ValueError("Unsupported summary algorithm")
    text = {kind: {"events": 0, "methods": {}, "unknown_token_events": 0}
            for kind in ("human.message", "assistant.visible")}
    missing, prices, calls = {}, {}, {}
    def observed():
        for event in events:
            kind, data = event["type"], event["data"]
            if kind in text:
                dest = text[kind]
                dest["events"] += 1
                method = data.get("token_method")
                tokens = data.get("tokens")
                if not isinstance(method, str) or not method or tokens is None:
                    dest["unknown_token_events"] += 1
                else:
                    bucket = dest["methods"].setdefault(method, {"tokens": 0, "bytes": 0, "events": 0})
                    bucket["events"] += 1
                    if method == "utf8-bytes/4-estimate" and type(data.get("bytes")) is int:
                        bucket["bytes"] += data["bytes"]
                        bucket["tokens"] = (bucket["bytes"] + 3) // 4
                    else:
                        bucket["tokens"] += tokens
            if kind == "model.usage":
                key = data["model"] + "/" + data["measurement"]
                counts = missing.setdefault(key, {})
                for field in ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens", "cache_write_tokens"):
                    counts[field] = counts.get(field, 0) + int(data.get(field) is None)
                measurement = data["measurement"]
                priced = data.get("reference_usd") is not None
                counts = calls.setdefault(measurement, {"priced": 0, "unpriced": 0})
                counts["priced" if priced else "unpriced"] += 1
                if priced:
                    prices[measurement] = prices.get(measurement, Decimal(0)) + Decimal(data["reference_usd"])
            yield event
    with localcontext() as ctx:
        ctx.prec = 80
        result = _summary_v1(observed())
    for kind, label in (("human.message", "human"), ("assistant.visible", "visible_ai")):
        dest = text[kind]
        dest["messages" if kind == "human.message" else "events"] = dest["events"]
        estimated = sum(v["tokens"] for k, v in dest["methods"].items() if "estimate" in k)
        measured = sum(v["tokens"] for k, v in dest["methods"].items() if "estimate" not in k)
        dest.update(tokens_estimated=estimated, tokens_measured=measured,
                    tokens_complete=dest["unknown_token_events"] == 0,
                    attention_seconds=None)
        result[label] = dest
    for key, counts in missing.items():
        model = result["models"][key]
        model["known_token_subtotals"] = {field: model[field] for field in counts}
        model["missing_field_calls"] = counts
        for field, count in counts.items():
            if count:
                model[field] = None
    result["algorithm"] = algorithm
    result["reference_usd_by_measurement"] = {
        measurement: {"known_subtotal": format(prices[measurement], "f") if measurement in prices else None,
                      "complete_for_observed_calls": counts["unpriced"] == 0, **counts}
        for measurement, counts in calls.items()}
    result["reference_cost_complete_for_observed_calls"] = bool(calls) and result["unpriced_calls"] == 0
    result["overall_score"] = None
    result["efficiency"] = None
    result["ranking_eligible"] = False
    return result


class Recorder:
    def __init__(self, cwd="."):
        self.root, self.directory = repo_paths(cwd)
        self.database = self.directory / "events.sqlite3"
        if self.directory.is_symlink() or self.database.is_symlink():
            raise ValueError("Recorder storage must not be a symlink")

    @contextmanager
    def connection(self):
        if not self.database.is_file():
            raise ValueError("AI-PoW is not initialized; run aipow init")
        db = sqlite3.connect(self.database, timeout=1.0)
        try:
            # DELETE journal has bounded transient size and no indefinitely growing WAL.
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            limit = db.execute("SELECT value FROM meta WHERE key='max_bytes'").fetchone()
            if limit:
                pagesize = db.execute("PRAGMA page_size").fetchone()[0]
                db.execute("PRAGMA max_page_count=" + str(int(limit[0]) // pagesize))
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def init(self, max_mib=64, report_view="iteration"):
        if not 4 <= max_mib <= 4096:
            raise ValueError("Quota must be between 4 and 4096 MiB")
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.database.exists():
            return {"initialized": True, "existing": True, "storage": str(self.directory)}
        fd = os.open(self.database, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        db = sqlite3.connect(self.database)
        try:
            db.executescript("""
                CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE events(seq INTEGER PRIMARY KEY, epoch TEXT NOT NULL,
                  event_id TEXT UNIQUE NOT NULL, hash TEXT NOT NULL, body TEXT NOT NULL);
                CREATE INDEX event_epoch ON events(epoch, seq);
                CREATE TABLE proofs(commit_id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE files(path TEXT PRIMARY KEY, hash TEXT NOT NULL, signature TEXT NOT NULL);
            """)
            for k, v in {"version": VERSION, "max_bytes": str(max_mib * 1024**2),
                         "epoch": uuid.uuid4().hex, "base": head(self.root) or "",
                         "started_ms": str(time.time_ns() // 1000000), "last_hash": ZERO,
                         "sampled": "0", "report_view": report_view}.items():
                db.execute("INSERT INTO meta VALUES (?,?)", (k, v))
            db.commit()
        finally:
            db.close()
        self.sample()
        return {"initialized": True, "storage": str(self.directory), "quota_mib": max_mib}

    @staticmethod
    def get(db, key):
        return db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()[0]

    @staticmethod
    def put(db, key, value):
        db.execute("INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value WHERE value<>excluded.value", (key, str(value)))

    def _append(self, db, kind, data, source="generic", event_id=None):
        validate_event(kind, data)
        event_id = event_id or uuid.uuid4().hex
        if len(event_id) > 256 or len(source) > 128:
            raise ValueError("Event identity too long")
        old = db.execute("SELECT body FROM events WHERE event_id=?", (event_id,)).fetchone()
        if old:
            previous = json.loads(old[0])
            if previous["type"] != kind or previous["data"] != data or previous["source"] != source:
                raise ValueError("Conflicting duplicate event_id")
            return False
        seq = db.execute("SELECT COALESCE(MAX(seq),0)+1 FROM events").fetchone()[0]
        body = {"v": VERSION, "seq": seq, "epoch": self.get(db, "epoch"),
                "event_id": event_id, "time_ms": time.time_ns() // 1000000,
                "previous": self.get(db, "last_hash"), "type": kind,
                "source": source, "data": data}
        h = digest(body)
        db.execute("INSERT INTO events VALUES (?,?,?,?,?)",
                   (seq, body["epoch"], event_id, h, canonical(body).decode()))
        self.put(db, "last_hash", h)
        return True

    def record(self, kind, data, source="generic", event_id=None):
        event_id = event_id or uuid.uuid4().hex
        for attempt in range(3):
            try:
                return self._record_once(kind, data, source, event_id)
            except sqlite3.OperationalError as exc:
                if attempt == 2 or not any(word in str(exc).lower() for word in ("locked", "busy")):
                    raise
                time.sleep(.02 * (attempt + 1))

    def _record_once(self, kind, data, source, event_id):
        with self.connection() as db:
            self._boundary(db, automatic=True)
            if kind == "model.usage":
                validate_event(kind, data)
                row = db.execute("SELECT value FROM meta WHERE key=?", ("price:" + data["model"],)).fetchone()
                if row and data.get("reference_usd") is None:
                    data = price_usage(data, json.loads(row[0]))
            return self._append(db, kind, data, source, event_id)

    def set_price(self, price):
        validate_price(price)
        if len(canonical(price)) > 4096:
            raise ValueError("Price snapshot exceeds 4 KiB")
        with self.connection() as db:
            self.put(db, "price:" + price["model"], canonical(price).decode())
        return {"model": price["model"], "price_snapshot_hash": digest(price)}

    def set_quota(self, max_mib):
        if not 4 <= max_mib <= 4096:
            raise ValueError("Quota must be between 4 and 4096 MiB")
        if max_mib * 1024**2 < self.database.stat().st_size:
            raise ValueError("Quota cannot be smaller than existing database")
        with self.connection() as db:
            self.put(db, "max_bytes", max_mib * 1024**2)
        return {"quota_mib": max_mib, "health_marker": "retained; prior lost events cannot be recovered"}

    def import_claude_usage(self, path, start_at_end=False):
        """Incremental metadata-only import; never import historic prompts or tool payloads.

        Transcript format is an adapter, not part of the protocol. Model messages
        are deduplicated by provider message id; changed replays mark a gap.
        """
        path = Path(path)
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as stream, self.connection() as db:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("Transcript must be a regular file")
            key = "claude-cursor:" + hashlib.sha256(os.fsencode(path.absolute())).hexdigest()
            row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            identity = f"{info.st_dev}:{info.st_ino}"
            state = json.loads(row[0]) if row else {"offset": 0, "identity": identity}
            if start_at_end and not row:
                self.put(db, key, canonical({"offset": info.st_size, "identity": identity}).decode())
                return {"imported_calls": 0, "baseline": True}
            self._boundary(db, automatic=True)
            if state["identity"] != identity or state["offset"] > info.st_size:
                self._append(db, "coverage.gap", {"reason": "transcript_rotated_or_truncated"}, "claude-transcript")
                state = {"offset": 0, "identity": identity}
            stream.seek(state["offset"])
            used, imported, pending = 0, 0, {}
            while used < 8 * 1024 * 1024:
                offset = stream.tell()
                line = stream.readline(1024 * 1024 + 1)
                if not line:
                    break
                used += len(line)
                if len(line) > 1024 * 1024:
                    raise ValueError("Transcript row exceeds 1 MiB")
                if not line.endswith(b"\n"):
                    stream.seek(offset)
                    break
                try:
                    row = json.loads(line)
                except (ValueError, UnicodeError):
                    self._append(db, "coverage.gap", {"reason": "malformed_transcript_row"}, "claude-transcript")
                    continue
                if not isinstance(row, dict) or row.get("type") != "assistant":
                    continue
                message = row.get("message") or {}
                usage = message.get("usage") or {}
                message_id = message.get("id")
                if not usage or not message_id:
                    continue
                try:
                    timestamp = int(datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")).timestamp() * 1000)
                except (ValueError, KeyError, TypeError):
                    self._append(db, "coverage.gap", {"reason": "transcript_missing_timestamp"}, "claude-transcript")
                    continue
                if timestamp < int(self.get(db, "started_ms")):
                    continue
                ci = usage.get("cache_read_input_tokens")
                fresh = usage.get("input_tokens")
                data = {"model": str(message.get("model") or "unknown")[:128],
                        "input_tokens": fresh + ci if type(fresh) is int and type(ci) is int else None,
                        "cached_input_tokens": ci, "cache_write_tokens": usage.get("cache_creation_input_tokens"),
                        "output_tokens": usage.get("output_tokens"), "reasoning_tokens": None,
                        "measurement": "provider_reported", "observed_from": "local-transcript",
                        "session_id": str(row.get("sessionId", ""))[:128]}
                event_id = "claude-usage:" + digest([data["session_id"], message_id])
                pending[event_id] = data
            for event_id, data in pending.items():
                prior = db.execute("SELECT body FROM events WHERE event_id=?", (event_id,)).fetchone()
                if prior:
                    old = json.loads(prior[0])["data"]
                    if any(old.get(k) != v for k, v in data.items()):
                        self._append(db, "coverage.gap", {"reason": "transcript_usage_changed", "event_id": event_id}, "claude-transcript")
                    continue
                validate_event("model.usage", data)
                price = db.execute("SELECT value FROM meta WHERE key=?", ("price:" + data["model"],)).fetchone()
                if price:
                    data = price_usage(data, json.loads(price[0]))
                self._append(db, "model.usage", data, "claude-transcript", event_id)
                imported += 1
            state["offset"] = stream.tell()
            self.put(db, key, canonical(state).decode())
            return {"imported_calls": imported, "bytes_read": used, "more": stream.tell() < info.st_size}

    def _events(self, db, epoch):
        for body, h in db.execute("SELECT body,hash FROM events WHERE epoch=? ORDER BY seq", (epoch,)):
            yield {**json.loads(body), "hash": h}

    def _boundary(self, db, automatic=False):
        current = head(self.root)
        base = self.get(db, "base") or None
        if current == base:
            return None
        # Rebase/amend/checkout/missed commits cannot be assigned to a fabricated interval.
        meta = commit_meta(self.root, current) if current else None
        linear = meta and ((base and meta["parents"][:1] == [base]) or (not base and not meta["parents"]))
        if not linear:
            raise ValueError("HEAD moved outside the observed parent interval; run aipow reset-boundary")
        epoch = self.get(db, "epoch")
        first = db.execute("SELECT seq,body FROM events WHERE epoch=? ORDER BY seq LIMIT 1", (epoch,)).fetchone()
        last = db.execute("SELECT seq,hash FROM events WHERE epoch=? ORDER BY seq DESC LIMIT 1", (epoch,)).fetchone()
        p = {"v": VERSION, **meta, "base": base, "epoch": epoch,
             "first_seq": first[0] if first else None, "last_seq": last[0] if last else None,
             "anchor": json.loads(first[1])["previous"] if first else self.get(db, "last_hash"),
             "trace_root": last[1] if last else self.get(db, "last_hash"),
             "summary": summary(self._events(db, epoch)),
             "trust": "local-self-reported", "capture": "partial",
             "boundary": "head-observed-after-commit" if automatic else "post-commit",
             "limits": {"max_file_bytes": MAX_FILE, "max_files": MAX_FILES,
                        "max_scan_bytes": SCAN_BYTES},
             "caveats": ["Hashes verify consistency, not truth or completeness",
                         "File observations are sampled; intermediate writes may be missed",
                         "Events are interval-associated, not causally attributed to staged changes",
                         "Worktrees are independent; imported work is not re-counted"]}
        p["score"] = self.evaluate(db, p)
        p["proof_hash"] = digest(p)
        db.execute("INSERT INTO proofs VALUES (?,?)", (current, canonical(p).decode()))
        self.put(db, "base", current)
        self.put(db, "epoch", uuid.uuid4().hex)
        # Snapshot remains the last observed working state; commit does not erase unstaged work.
        return p

    def seal(self):
        with self.connection() as db:
            p = self._boundary(db)
            if not p:
                old = db.execute("SELECT body FROM proofs WHERE commit_id=?", (head(self.root),)).fetchone()
                if not old:
                    raise ValueError("No new commit to seal (the starting commit predates recording)")
                p = json.loads(old[0])
        # Report failures do not roll back a valid proof or the user's commit.
        try:
            path = self.html_report(p["commit"])
            print("AI-PoW " + (p.get("score") or {}).get("value", "unscored") + " | " + str(path), file=sys.stderr)
        except Exception as exc:
            record_error(self, exc)
            print("AI-PoW: proof sealed; HTML report could not be written", file=sys.stderr)
        return p

    def evaluate(self, db, proof):
        return evaluate_score(self.root, proof, self._events(db, proof["epoch"]))

    def report_data(self, ref="HEAD", view="iteration"):
        from ai_pow_scoring import history_stats, ladder_step
        if view not in {"iteration", "latest"}:
            raise ValueError("Report view must be iteration or latest")
        current = self.proof(ref)
        current_sealed_score = current.get("score")
        verification = self.verify(ref)
        with self.connection() as db:
            if not current.get("score"):
                current = {**current, "score": self.evaluate(db, current)}
            def decorate(proof):
                subject = git(self.root, "show", "-s", "--format=%s%n%cI", proof["commit"]).decode("utf-8", "replace").splitlines()
                return {"commit": proof["commit"], "title": subject[0][:240], "date": subject[-1],
                        "score": proof.get("score"), "summary": proof["summary"], "proof_hash": proof["proof_hash"]}
            history = []
            iteration = None
            if view == "iteration":
                # Replay the entire bounded first-parent lineage, not just the
                # visible 30 rows. Never reset ratings as rows leave the view.
                lineage = git(self.root, "rev-list", "--first-parent", current["commit"]).decode().splitlines()
                ancestors = lineage[1:31]
                visible = set(lineage[:31])
                ratings = {}
                for commit in reversed(lineage):
                    row = db.execute("SELECT body FROM proofs WHERE commit_id=?", (commit,)).fetchone()
                    saved = json.loads(row[0]).get("score") if row else None
                    if commit == current["commit"]:
                        saved = current_sealed_score
                    iteration = ladder_step(iteration, saved)
                    if commit in visible:
                        ratings[commit] = iteration
                for commit in ancestors:
                    row = db.execute("SELECT body FROM proofs WHERE commit_id=?", (commit,)).fetchone()
                    if row:
                        history.append(decorate(json.loads(row[0])))
                    else:
                        subject = git(self.root, "show", "-s", "--format=%s%n%cI", commit).decode("utf-8", "replace").splitlines()
                        history.append({"commit": commit, "title": subject[0][:240], "date": subject[-1], "score": None})
                    history[-1]["iteration"] = ratings[commit]
            return {"project": self.root.name, "view": view, "current": decorate(current), "history": history,
                    "iteration": iteration,
                    "statistics": history_stats(current["score"], history) if view == "iteration" else None,
                    "verification": verification, "demo": False}

    def html_report(self, ref="HEAD", view=None, destination=None):
        from ai_pow_report import render
        if view is None:
            with self.connection() as db:
                row = db.execute("SELECT value FROM meta WHERE key='report_view'").fetchone()
                view = row[0] if row else "iteration"
        data = self.report_data(ref, view)
        html = render(data).encode("utf-8")
        if len(html) > 8 * 1024 * 1024:
            raise ValueError("HTML report exceeds 8 MiB")
        if destination:
            with open(destination, "xb") as out:
                os.chmod(destination, 0o600)
                out.write(html)
            return Path(destination)
        directory = self.directory / "reports"
        if directory.is_symlink():
            raise ValueError("Report directory must not be a symlink")
        directory.mkdir(mode=0o700, exist_ok=True)
        path = directory / (data["current"]["commit"] + ".html")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(html)
        # Only remove this recorder's generated HTML cache, never proofs or exports.
        owned = sorted((p for p in directory.iterdir() if p.suffix == ".html" and len(p.stem) in {40, 64}
                        and all(c in "0123456789abcdef" for c in p.stem) and p.is_file() and not p.is_symlink()),
                       key=lambda p: p.stat().st_mtime_ns, reverse=True)
        size = 0
        for index, cached in enumerate(owned):
            size += cached.stat().st_size
            if cached != path and (index >= 20 or size > 16 * 1024 * 1024):
                cached.unlink()
        return path

    def reset_boundary(self):
        with self.connection() as db:
            self._append(db, "coverage.gap", {"reason": "explicit_boundary_reset", "head": head(self.root)})
            # Old events are retained and queryable, never reassigned to another commit.
            self.put(db, "epoch", uuid.uuid4().hex)
            self.put(db, "base", head(self.root) or "")
            self.put(db, "sampled", "0")
            db.execute("DELETE FROM files")
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='file_units'").fetchone():
                db.execute("DELETE FROM file_units")
        return {"reset": True, "unsealed_events": "retained in previous epoch"}

    def sample(self):
        from ai_pow_scoring import fingerprints
        with self.connection() as db:
            self._boundary(db, automatic=True)
            paths = git(self.root, "ls-files", "-c", "-o", "--exclude-standard", "-z").split(b"\0")
            old_rows = {row[0]: (row[1], row[2]) for row in db.execute("SELECT path,hash,signature FROM files")}
            db.execute("CREATE TABLE IF NOT EXISTS file_units(path TEXT PRIMARY KEY, units TEXT NOT NULL)")
            old_units = dict(db.execute("SELECT path,units FROM file_units"))
            new_units = {}
            seen, observed, signatures, skipped, read_bytes = set(), {}, {}, 0, 0
            new_paths = 0
            safe_parents = {self.root: True}
            for raw in paths:
                if not raw:
                    continue
                name = os.fsdecode(raw)
                parts = Path(name).parts
                if (any(p in EXCLUDED for p in parts) or any(p.startswith(".env") for p in parts)
                        or name.endswith((".pem", ".key", ".p12"))):
                    skipped += 1
                    continue
                if name in seen:
                    continue
                seen.add(name)
                if len(seen) > MAX_FILES:
                    skipped += 1
                    continue
                path = self.root / name
                try:
                    # Reject directories, special files, and symlinked ancestors.
                    if path.parent not in safe_parents:
                        resolved = path.parent.resolve()
                        safe_parents[path.parent] = resolved == path.parent and resolved.is_relative_to(self.root)
                    if not safe_parents[path.parent]:
                        skipped += 1
                        continue
                    info = path.lstat()
                    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE:
                        skipped += 1
                        continue
                    path_id = hashlib.sha256(raw).hexdigest()
                    if path_id not in old_rows:
                        if len(old_rows) + new_paths >= MAX_FILES:
                            skipped += 1
                            continue
                        new_paths += 1
                    signature = f"{info.st_dev}:{info.st_ino}:{info.st_size}:{info.st_mtime_ns}:{info.st_ctime_ns}"
                    if old_rows.get(path_id, (None, None))[1] == signature and path_id in old_units:
                        observed[path_id] = old_rows[path_id][0]
                        signatures[path_id] = signature
                        if path_id in old_units:
                            new_units[path_id] = json.loads(old_units[path_id])
                        continue
                    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
                    with os.fdopen(fd, "rb") as stream:
                        info = os.fstat(stream.fileno())
                        signature = f"{info.st_dev}:{info.st_ino}:{info.st_size}:{info.st_mtime_ns}:{info.st_ctime_ns}"
                        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE or read_bytes + info.st_size > SCAN_BYTES:
                            skipped += 1
                            continue
                        content = stream.read(MAX_FILE + 1)
                        read_bytes += len(content)
                        if len(content) > MAX_FILE:
                            skipped += 1
                            continue
                    # Content hashes deliberately omit source text and file names from exported traces.
                    observed[path_id] = hashlib.sha256(content).hexdigest()
                    signatures[path_id] = signature
                    new_units[path_id] = fingerprints(content, name)
                except FileNotFoundError:
                    continue
                except OSError:
                    skipped += 1
            old = {key: value[0] for key, value in old_rows.items()}
            initial = self.get(db, "sampled") == "0"
            # When scan is partial we must not call absent files deletions.
            for path_id in sorted(set(observed) | (set(old) if not skipped else set())):
                before, after = old.get(path_id), observed.get(path_id)
                if before != after and not initial:
                    data = {"path_hash": path_id, "before": before, "after": after}
                    previous_units = json.loads(old_units[path_id]) if path_id in old_units else None
                    following_units = new_units.get(path_id)
                    if (before is None or previous_units is not None) and (after is None or following_units is not None):
                        data.update(units_before=(previous_units or {}).get("units", []),
                                    units_after=(following_units or {}).get("units", []),
                                    unit_kind=(following_units or previous_units or {}).get("kind", "content-blocks"),
                                    units_truncated=bool((previous_units or {}).get("truncated") or (following_units or {}).get("truncated")))
                    self._append(db, "file.observed", data, "sampler")
                if after:
                    if old_rows.get(path_id) != (after, signatures[path_id]):
                        db.execute("INSERT OR REPLACE INTO files VALUES (?,?,?)", (path_id, after, signatures[path_id]))
                elif not skipped:
                    db.execute("DELETE FROM files WHERE path=?", (path_id,))
                    db.execute("DELETE FROM file_units WHERE path=?", (path_id,))
                if path_id in new_units:
                    packed = canonical(new_units[path_id]).decode()
                    if old_units.get(path_id) != packed:
                        db.execute("INSERT OR REPLACE INTO file_units VALUES (?,?)", (path_id, packed))
            if skipped:
                last_gap = db.execute("SELECT value FROM meta WHERE key='last_scan_skipped'").fetchone()
                if not last_gap or last_gap[0] != str(skipped):
                    self._append(db, "coverage.gap", {"reason": "scan_exclusions_or_limits", "skipped": skipped}, "sampler")
            self.put(db, "last_scan_skipped", skipped)
            self.put(db, "sampled", "1")
            return {"observed_files": len(observed), "skipped": skipped, "bytes_read": read_bytes, "baseline": initial}

    def status(self):
        with self.connection() as db:
            return {"version": VERSION, "storage": str(self.directory),
                    "database_bytes": self.database.stat().st_size,
                    "quota_bytes": int(self.get(db, "max_bytes")),
                    "base": self.get(db, "base") or None, "head": head(self.root),
                    "proofs": db.execute("SELECT COUNT(*) FROM proofs").fetchone()[0],
                    "capture": "partial", "trust": "local-self-reported",
                    "recording_error": (self.directory / "recording-error").exists(),
                    "active": summary(self._events(db, self.get(db, "epoch")))}

    def proof(self, ref="HEAD"):
        commit = commit_meta(self.root, ref)["commit"]
        with self.connection() as db:
            row = db.execute("SELECT body FROM proofs WHERE commit_id=?", (commit,)).fetchone()
            if not row:
                raise ValueError("No proof recorded for " + commit)
            return json.loads(row[0])

    def verify(self, ref="HEAD"):
        p = self.proof(ref)
        with self.connection() as db:
            return verify_proof(self.root, p, self._events(db, p["epoch"]))

    def export(self, destination, ref="HEAD"):
        p = self.proof(ref)
        # Single streaming JSONL artifact: proof header followed by hash-chained events.
        with self.connection() as db:
            verify_proof(self.root, p, self._events(db, p["epoch"]))
            with open(destination, "xb") as out:
                os.chmod(destination, 0o600)
                out.write(canonical({"proof": p}) + b"\n")
                for e in self._events(db, p["epoch"]):
                    out.write(canonical(e) + b"\n")
        return {"exported": str(destination), "proof_hash": p["proof_hash"]}


SCORING_TYPES = {"human.message", "file.observed", "task.change", "coverage.gap"}


def evaluate_score(root, proof, events):
    from ai_pow_scoring import collect_evidence, fingerprints, score
    selected = []
    for event in events:
        if event["type"] in SCORING_TYPES:
            selected.append(event)
            if len(selected) > 4096:
                break
    truncated = len(selected) > 4096
    selected = selected[:4096]
    wanted = set()
    for event in selected:
        if event["type"] == "file.observed":
            wanted.add(event["data"]["path_hash"])
        elif event["type"] == "task.change":
            wanted.update(event["data"].get("evidence", []))
    # Only inspect bounded blobs from the committed tree, never the worktree.
    args = ("diff", "--name-only", "--no-renames", "-z", proof["base"], proof["commit"]) if proof["base"] else (
        "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", "-z", proof["commit"])
    changed = {p for p in git(root, *args).split(b"\0") if p}
    units, known_paths = {}, set()
    scope_units, read_bytes, inspected = 0, 0, 0
    limited = truncated
    for entry in git(root, "ls-tree", "-r", "-l", "-z", proof["commit"]).split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, kind, oid, size = metadata.split()
        path_id = hashlib.sha256(raw_path).hexdigest()
        known_paths.add(path_id)
        if path_id not in wanted and raw_path not in changed:
            continue
        if (kind != b"blob" or mode not in {b"100644", b"100755"} or int(size) > MAX_FILE
                or read_bytes + int(size) > SCAN_BYTES or inspected >= 128):
            limited = True
            continue
        content = git(root, "cat-file", "blob", oid.decode(), limit=MAX_FILE)
        read_bytes += len(content)
        inspected += 1
        result = fingerprints(content, os.fsdecode(raw_path))
        limited = limited or result["truncated"]
        units[path_id] = result["units"]
        if raw_path in changed:
            scope_units += len(result["units"])
    for path_id in wanted - known_paths:
        units[path_id] = []  # A verified deletion is a surviving outcome too.
    evidence = collect_evidence(selected, units, scope_units, len(changed), limited)
    return score(evidence, proof["summary"])


def verify_proof(root, proof, events):
    p = dict(proof)
    h = p.pop("proof_hash")
    if digest(p) != h or p["v"] != VERSION:
        raise ValueError("Proof hash/version mismatch")
    meta = commit_meta(root, p["commit"])
    if any(meta[k] != p[k] for k in ("commit", "tree", "parents")):
        raise ValueError("Git commit/tree/parent mismatch")
    git(root, "fsck", "--strict", "--no-reflogs", "--no-dangling", p["commit"])
    if (p["parents"][:1] or [None])[0] != p["base"]:
        raise ValueError("Proof base does not match first parent")
    previous, sequence, count = p["anchor"], p["first_seq"], 0
    scoring_events = []
    def checked():
        nonlocal previous, sequence, count
        for item in events:
            e = dict(item)
            eh = e.pop("hash")
            validate_event(e["type"], e["data"])
            if (digest(e) != eh or e["previous"] != previous or e["seq"] != sequence
                    or e["epoch"] != p["epoch"] or e["v"] != VERSION):
                raise ValueError("Trace hash/sequence/epoch mismatch")
            previous = eh
            sequence += 1
            count += 1
            if p.get("score") and e["type"] in SCORING_TYPES and len(scoring_events) < 4097:
                scoring_events.append(e)
            yield e
    totals = summary(checked(), algorithm=p["summary"].get("algorithm", "observed-v1"))
    if previous != p["trace_root"] or (sequence - 1 if count else None) != p["last_seq"]:
        raise ValueError("Trace missing or truncated")
    if bool(count) != (p["first_seq"] is not None) or totals != p["summary"]:
        raise ValueError("Summary/range mismatch")
    if p.get("score"):
        if evaluate_score(root, p, scoring_events) != p["score"]:
            raise ValueError("Score calculation/version mismatch")
    return {"integrity_verified": True, "git_tree_verified": True, "events": count,
            "proof_hash": h, "trust": "local-self-reported", "completeness_verified": False,
            "work_authenticity_verified": False, "quality_verified": False}


def verify_bundle(root, path):
    with open(path, "rb") as stream:
        first = stream.readline(1024 * 1024 + 1)
        if len(first) > 1024 * 1024:
            raise ValueError("Proof header exceeds limit")
        proof = json.loads(first)["proof"]
        def rows():
            while True:
                line = stream.readline(MAX_EVENT + 1)
                if not line:
                    break
                if len(line) > MAX_EVENT:
                    raise ValueError("Bundle event exceeds limit")
                yield json.loads(line)
        return verify_proof(root, proof, rows())


def invocation():
    if getattr(sys, "frozen", False):
        return [sys.executable, "pow"]
    return [sys.executable, str(Path(__file__).resolve())]


def install_hook(recorder):
    hook = Path(git(recorder.root, "rev-parse", "--git-path", "hooks/post-commit").decode().strip())
    if not hook.is_absolute():
        hook = recorder.root / hook
    command = shlex.join(invocation() + ["--cwd", ".", "seal"])
    body = "#!/bin/sh\n# AI-PoW 0.1 (local integrity only)\n" + command + " >/dev/null || echo 'AI-PoW: proof not sealed; run aipow status' >&2\nexit 0\n"
    # A shared/custom hooksPath must not be overwritten or silently used for other worktrees.
    custom = git(recorder.root, "config", "--get", "core.hooksPath", allow_fail=True)
    gd = recorder.directory.parent
    common = git(recorder.root, "rev-parse", "--git-common-dir").decode().strip()
    common = (recorder.root / common).resolve()
    if custom or common != gd:
        return {"installed": False, "reason": "shared/custom hooks path", "manual_command": command}
    if hook.exists() or hook.is_symlink():
        return {"installed": False, "reason": "existing hook preserved", "manual_command": command}
    hook.parent.mkdir(parents=True, exist_ok=True)
    with open(hook, "x") as out:
        out.write(body)
    hook.chmod(0o700)
    return {"installed": True, "path": str(hook)}


def claude_hook(recorder, payload):
    kind = payload.get("hook_event_name")
    data = {"session_id": str(payload.get("session_id", ""))[:128],
            "agent_id": str(payload.get("agent_id", "main"))[:128]}
    event_id = None
    if kind == "UserPromptSubmit":
        typ = "human.message"
        data.update(text_meta(payload.get("prompt", "")))
    elif kind == "MessageDisplay":
        typ = "assistant.visible"
        data.update(text_meta(payload.get("delta", "")))
        data["channel"] = "display"
        event_id = digest([data["session_id"], kind, payload.get("message_id"), payload.get("index")])
    elif kind in {"PreToolUse", "PostToolUse", "PostToolUseFailure"}:
        typ = "tool.call" if kind == "PreToolUse" else "tool.result"
        name = str(payload.get("tool_name", "unknown"))[:128]
        data.update(name=name, call_id=str(payload.get("tool_use_id", ""))[:128])
        if name.startswith("mcp__"):
            data["mcp_server"] = name.split("__")[1]
        if typ == "tool.result":
            data["ok"] = kind == "PostToolUse"
        if data["call_id"]:
            event_id = digest([data["session_id"], data["call_id"], typ])
    elif kind in {"SubagentStart", "SubagentStop"}:
        typ = "agent.spawn" if kind == "SubagentStart" else "agent.stop"
        data["parent_agent_id"] = "unknown"
    elif kind in {"SessionStart", "Stop", "SessionEnd"}:
        typ = "run.start" if kind == "SessionStart" else "run.stop"
    else:
        return
    recorder.record(typ, data, "claude-hooks", event_id)
    transcript = payload.get("agent_transcript_path") if kind == "SubagentStop" else payload.get("transcript_path")
    if transcript and kind in {"SessionStart", "Stop", "SessionEnd", "SubagentStop"}:
        try:
            recorder.import_claude_usage(transcript, start_at_end=kind == "SessionStart")
        except FileNotFoundError:
            pass  # SessionStart can precede the creation of the transcript.
    if kind in {"PostToolUse", "PostToolUseFailure", "Stop"}:
        recorder.sample()


def run(recorder, command, interval=2):
    if not command:
        raise ValueError("Provide a command after --")
    recorder.sample()
    run_id = uuid.uuid4().hex
    recorder.record("run.start", {"run_id": run_id, "command": Path(command[0]).name}, "wrapper")
    env = dict(os.environ, AIPOW_ROOT=str(recorder.root), AIPOW_RUN_ID=run_id)
    proc = subprocess.Popen(command, env=env)
    previous_handlers = {}
    def forward(sig, frame):
        if proc.poll() is None:
            proc.send_signal(sig)
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[sig] = signal.signal(sig, forward)
        while True:
            try:
                code = proc.wait(timeout=interval)
                break
            except subprocess.TimeoutExpired:
                try:
                    recorder.sample()
                except Exception as exc:
                    record_error(recorder, exc)
        try:
            recorder.sample()
            recorder.record("run.stop", {"run_id": run_id, "exit_code": code}, "wrapper")
        except Exception as exc:
            record_error(recorder, exc)
        return code
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        proc.wait()


def record_error(recorder, exc):
    # Fixed-size health marker survives SQLITE_FULL; no accumulating error log.
    try:
        path = recorder.directory / "recording-error"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "w") as out:
            out.write(type(exc).__name__ + ": recorder lost coverage; inspect boundary/quota\n")
    except OSError:
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd", default=os.environ.get("AIPOW_ROOT", "."))
    parser.add_argument("--version", action="version", version=APP_VERSION)
    sub = parser.add_subparsers(dest="action", required=True)
    init = sub.add_parser("init")
    init.add_argument("--max-mib", type=int, default=64)
    init.add_argument("--no-hook", action="store_true")
    init.add_argument("--view", choices=("iteration", "latest"), default="iteration")
    for name in ("status", "sample", "seal", "reset-boundary", "install-hook", "hook-claude"):
        sub.add_parser(name)
    for name in ("report", "verify", "export"):
        p = sub.add_parser(name)
        p.add_argument("--commit", default="HEAD")
        if name == "verify":
            p.add_argument("--bundle")
        if name == "export":
            p.add_argument("destination")
        if name == "report":
            p.add_argument("--html", action="store_true", help="Generate a self-contained HTML report")
            p.add_argument("--view", choices=("iteration", "latest"))
            p.add_argument("--output", help="Export HTML to a new file; existing files are preserved")
    config = sub.add_parser("report-config")
    config.add_argument("--view", choices=("iteration", "latest"), required=True)
    task = sub.add_parser("task")
    task.add_argument("task_id")
    task.add_argument("--status", choices=("active", "completed", "dropped"), required=True)
    task.add_argument("--evidence", nargs="*", default=[], help="Repository-relative committed artifact paths")
    emit = sub.add_parser("emit")
    emit.add_argument("type", choices=sorted(TYPES))
    emit.add_argument("--source", default="generic")
    emit.add_argument("--event-id")
    price = sub.add_parser("price-set")
    price.add_argument("path")
    transcript = sub.add_parser("import-claude")
    transcript.add_argument("path")
    quota = sub.add_parser("quota")
    quota.add_argument("--max-mib", type=int, required=True)
    for name in ("run", "claude"):
        p = sub.add_parser(name)
        p.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    recorder = None
    try:
        recorder = Recorder(args.cwd)
        action = args.action
        if action == "init":
            result = recorder.init(args.max_mib, args.view)
            if not args.no_hook:
                result["hook"] = install_hook(recorder)
        elif action == "install-hook":
            result = install_hook(recorder)
        elif action == "price-set":
            with open(args.path, "rb") as source:
                raw = source.read(4097)
            if len(raw) > 4096:
                raise ValueError("Price snapshot exceeds 4 KiB")
            result = recorder.set_price(json.loads(raw))
        elif action == "import-claude":
            result = recorder.import_claude_usage(args.path)
        elif action == "quota":
            result = recorder.set_quota(args.max_mib)
        elif action == "report-config":
            with recorder.connection() as db:
                recorder.put(db, "report_view", args.view)
            result = {"report_view": args.view}
        elif action == "task":
            evidence = []
            for name in args.evidence:
                path = Path(name)
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError("Evidence paths must be repository-relative")
                evidence.append(hashlib.sha256(os.fsencode(path.as_posix())).hexdigest())
            result = {"recorded": recorder.record("task.change", {"task_id": args.task_id,
                       "status": args.status, "evidence": evidence}, "task-cli")}
        elif action in {"status", "sample", "seal", "reset-boundary"}:
            result = getattr(recorder, action.replace("-", "_"))()
        elif action == "report":
            result = {"report": str(recorder.html_report(args.commit, args.view, args.output))} if args.html or args.output else recorder.proof(args.commit)
        elif action == "verify":
            result = verify_bundle(recorder.root, args.bundle) if args.bundle else recorder.verify(args.commit)
        elif action == "export":
            result = recorder.export(args.destination, args.commit)
        elif action in {"emit", "hook-claude"}:
            raw = sys.stdin.buffer.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("Input exceeds 1 MiB")
            payload = json.loads(raw)
            if action == "hook-claude":
                if payload.get("cwd"):
                    target = Recorder(payload["cwd"])
                    if target.directory != recorder.directory:
                        if not target.database.is_file():
                            recorder.record("coverage.gap", {"reason": "uninitialized_claude_worktree"}, "claude-hooks")
                            return 0
                        recorder = target
                claude_hook(recorder, payload)
                return 0
            result = {"recorded": recorder.record(args.type, payload, args.source, args.event_id)}
        elif action in {"run", "claude"}:
            command = args.args[1:] if args.args[:1] == ["--"] else args.args
            if action == "claude":
                hooks = {}
                for event in ("SessionStart", "UserPromptSubmit", "MessageDisplay", "PreToolUse",
                              "PostToolUse", "PostToolUseFailure", "SubagentStart", "SubagentStop", "Stop", "SessionEnd"):
                    hooks[event] = [{"hooks": [{"type": "command", "command": shlex.join(invocation() + ["--cwd", str(recorder.root), "hook-claude"]), "timeout": 5}]}]
                command = ["claude", "--settings", json.dumps({"hooks": hooks}), *command]
            return run(recorder, command)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError, ArithmeticError) as exc:
        if recorder and args.action in {"hook-claude", "seal", "emit", "sample"}:
            record_error(recorder, exc)
        print("AI-PoW: " + str(exc), file=sys.stderr)
        return 0 if args.action == "hook-claude" else 1


if __name__ == "__main__":
    raise SystemExit(main())

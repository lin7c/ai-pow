# Validation

The initial implementation was exercised on Linux with Python 3.12.3. This document distinguishes observed checks from untested claims.

## Automated checks

The standalone suite covers:

- Event-chain tampering, missing trace suffixes, summary recomputation, and Git-bound proofs.
- Identical retries, conflicting event IDs, concurrent threads, and concurrent processes.
- Database quota exhaustion and SQLite integrity after rollback.
- File sampling, unchanged-content caching, secret/symlink exclusions, and idle-log growth.
- Partial staging, independent worktrees, commit hooks, and explicit boundary resets.
- Incremental Claude transcript parsing, historical filtering, and usage deduplication.
- Wrapper exit codes, child-process reaping, and timer cleanup.
- Stream-chunk-invariant estimates, unknown usage totals, separate pricing bases, deterministic decimal arithmetic, and legacy summary compatibility.
- CLI init, capture, commit, report, export, and verify. A local laintas-cli checkout is exercised when available; standalone tests do not require it.

Run the current suite with:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

Related laintas-cli integration tests were also run in the development workspace. No paid model call was made. Claude hook fixtures and local version/help checks are not a substitute for testing every Claude release.

## Reproducible local overhead probe

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/benchmark.py
```

The initial benchmark created 1,000 files of 1 KiB, established a baseline, sampled unchanged files, and recorded 1,000 simple tool-call events:

| Measurement | Observed value |
| --- | ---: |
| Unchanged-file sample | 137.96 ms |
| Source content reread | 0 bytes |
| Event write latency, median | 14.20 ms |
| Event write latency, P95 | 19.98 ms |
| Database including file state | 880,640 bytes |
| Current traced Python allocations | 215.16 KiB |
| Peak traced Python allocations | 2,313.47 KiB |
| Python threads after completion | 1 |

This is a local short-duration measurement, not a latency or leak guarantee. System load, filesystem layout, hardware, event payloads, and validation depth affect results. `tracemalloc` excludes SQLite native allocations, interpreter RSS, and Git subprocess memory. Journal files and exports are not included in the database size.

## Cleanup and limitations

Tests and the benchmark own their temporary repositories, transcripts, exports, and preference directories. They use `TemporaryDirectory`, reap subprocesses, and cancel/join timers. No permanent recorder daemon is started.

Long-running soak tests, every supported platform, every provider schema, and adversarial remote attestation have not been validated. CI results apply only to the environments and tests actually run.

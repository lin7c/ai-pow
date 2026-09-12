# Validation

The implementation was exercised on Linux with Python 3.12.3. This document distinguishes observed checks from untested claims.

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
- Score monotonicity, small-sample smoothing, neutral missingness, capture-gap confidence, AST constants, reverts, and surviving deletions.
- Forged score evidence rejected even after recomputing its score and proof hash; verification rebuilds evidence from the trace and Git tree.
- Latest-only data isolation, first-parent history averages, cohort/algorithm separation, and refusing to overwrite exports.
- Scores use committed blobs rather than unstaged working-tree content.
- Zero-based exact addition of existing commit scores, no extra weighting or cap, omitted unscored commits, and preservation of contributions older than the 30 visible history rows.
- Resource quantities leaving the score unchanged, weight ceding when a dimension has no evidence, and sparse evidence staying near the neutral prior.
- Proofs sealed with balanced-v1/observed-v2 verifying under their own algorithms, and rejection of a proof relabelled with another or an unknown algorithm.
- Pooled repository totals: ratios recomputed from pooled quantities rather than averaged, unknown values never counted as zero.
- Agent-structure reduction: parent links, depth, per-tool counts, node/name bounds, repeated spawns, and reported parent cycles.
- Interval windows, session/run counting across separate id namespaces, failed tool results, non-zero exits, coverage gaps, and amounts actually paid kept separate from reference prices.
- Commit diff statistics read from Git, and older reducers left unchanged by the newer one.
- Page separation: the commit run view carries no history or cumulative total, the dashboard carries no per-commit derived detail, and each page leads with its corresponding score and keeps supporting metrics collapsed.
- Per-file breakdown: real paths resolved from the committed tree, write events, overwritten edits and survival.
- Iteration chain: T = T-1 + this commit field by field, hash linkage between rows, rebuild reproducing the same hashes, gaps marked after a boundary reset, and totals surviving the deletion of an older proof.

The optional Playwright check exercises exact primary score values, collapsed detail groups and their expansion, no external requests, overflow checks at 375, 720, 1024, and 1440 pixels, the eight dashboard rates and six run-view rates, session timelines, agent trees, per-file tables, provenance, trend charts, commit links, and pooled lifetime ratios. Desktop and mobile previews are inspected visually. Synthetic demo data is labeled; it is not a real project benchmark.

Run the current suite with:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

Related laintas-cli integration tests were also run in the development workspace. No paid model call was made. Claude hook fixtures and local version/help checks are not a substitute for testing every Claude release.

## Reproducible local overhead probe

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/benchmark.py
```

The 0.4.0 benchmark created 1,000 files of 1 KiB, established a baseline, sampled unchanged files, recorded 1,000 simple tool-call events, and sealed a commit with an HTML report:

| Measurement | Observed value |
| --- | ---: |
| Unchanged-file sample | 191.68 ms |
| Source content reread | 0 bytes |
| Event write latency, median | 13.72 ms |
| Event write latency, P95 | 20.38 ms |
| Database including file state | 1,175,552 bytes |
| Current traced Python allocations after recording | 208.74 KiB |
| Peak traced Python allocations while recording | 2,275.77 KiB |
| Commit sealing, verification, and HTML generation | 2,935.02 ms |
| Peak traced Python allocations while sealing | 2,331.86 KiB |
| Generated HTML | 42,480 bytes |
| Python threads after completion | 1 |

The report grew from roughly 33 KB to 42 KB with the proof vector and repository totals. Sampling and sealing timings vary between runs on this machine; the previous release measured 123.60 ms and 2,766.84 ms for the same two steps.

This is a local short-duration measurement, not a latency or leak guarantee. System load, filesystem layout, hardware, event payloads, and validation depth affect results. `tracemalloc` excludes SQLite native allocations, interpreter RSS, and Git subprocess memory. Journal files and exports are not included in the database size.

## Cleanup and limitations

Tests and the benchmark own their temporary repositories, transcripts, exports, and preference directories. They use `TemporaryDirectory`, reap subprocesses, and cancel/join timers. No permanent recorder daemon is started.

Long-running soak tests, every supported platform, every provider schema, and adversarial remote attestation have not been validated. CI results apply only to the environments and tests actually run.

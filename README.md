# AI-PoW

### Work, made visible.

A versioned process score and a verifiable work journal for every Git commit.

[![Tests](https://github.com/lin7c/ai-pow/actions/workflows/tests.yml/badge.svg)](https://github.com/lin7c/ai-pow/actions/workflows/tests.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**[Explore the interactive report](https://lin7c.github.io/ai-pow/demo/)** · **[Latest-only example](https://lin7c.github.io/ai-pow/demo/latest.html)** · [Scoring specification](docs/METRICS.md) · [Protocol](docs/PROTOCOL-v0.1.md)

[![AI-PoW commit report: score, evidence, and iteration history](docs/demo/preview.png)](https://lin7c.github.io/ai-pow/demo/)

*The preview uses clearly labeled synthetic history evaluated by the production scoring algorithm.*

## The idea

A Git diff shows what changed. AI-PoW records more of the work behind it: human input, visible AI responses, model usage, agent activity, and sampled artifact revisions. It binds those observations to the resulting commit, computes a transparent process score, and creates an offline HTML report.

**v0.2 includes:**

- A smooth 0–100 score with four visible components, evidence confidence, and explicit uncertainty.
- A designed commit report with grade, resource breakdown, scoring explanations, and proof identity.
- Two views: **Iteration history** and **Latest commit**.
- A cumulative project ladder starting at 1,000, with tiers, bounded rating changes, and a switchable rating/commit-score chart.
- Historical averages, same-scope comparisons, local percentiles, grade filters, and commit inspection.
- A bounded local recorder, hash-chained export, and verification against actual Git objects.
- A Claude Code adapter, generic agent wrapper, and shared core for the laintas-cli development integration.

Python 3.10+ and Git. **No third-party runtime dependencies, hosted account, permanent daemon, background model calls, or telemetry.**

## Start recording

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install "git+https://github.com/lin7c/ai-pow.git"

cd /path/to/your/git-project
aipow init --view iteration
aipow claude
```

Work normally and commit:

```bash
git add src/app.py
git commit -m "Implement the feature"
```

The post-commit hook seals the proof and prints the score and local HTML report path. Open that file in your browser. It works offline and does not need a preview server.

Existing or shared hooks are never replaced. If automatic hook installation is unavailable, integrate the printed command yourself or run `aipow seal` after each commit. For explicitly manual operation, initialize with `aipow init --no-hook`.

## Choose the report you want

```bash
# Latest commit remains the focus; include up to 30 prior commits.
aipow report --html --view iteration

# Only this commit. No historical commit data is embedded.
aipow report --html --view latest

# Change the default for future commit reports.
aipow report-config --view latest

# Export a shareable standalone page; existing files are not overwritten.
aipow report --html --view iteration --output /path/outside/project/report.html

# Machine-readable proof and independent verification.
aipow report
aipow verify
aipow export /path/outside/project/commit-proof.jsonl
```

Iteration reports can switch views interactively. A latest-only export disables history mode because it contains no history. Reports include keyboard focus states, mobile layouts, a commit-detail dialog, and Print / PDF.

History follows the current commit's first-parent ancestry, not all branches. Averages exclude the current commit and incompatible scoring algorithms. Same-scope comparisons match the approximate scope cohort; the local percentile requires at least three prior peers. “Same grade” means the same score band, not a global skill ranking.

Reports are generated after committing and remain outside the tracked source tree. They are **not automatically uploaded to GitHub**. Share an explicit export only after reviewing its contents.

### Two scores, two different questions

**Latest commit: 0–100.** How did this observed development interval perform?

**Iteration history: project rating, starting at 1,000.** How has the project's recorded process developed over successive versions?

The project ladder rises gradually after strong, well-evidenced iterations and can fall after weaker ones. Each update is bounded to 40 points and scaled by evidence confidence squared and scope. Missing artifact evidence freezes the rating. Repeating the same performance approaches a target rather than yielding unlimited points for more commits.

| Project tier | Rating |
| --- | --- |
| Bronze | Below 1,100 |
| Silver | 1,100–1,299.9 |
| Gold | 1,300–1,499.9 |
| Platinum | 1,500–1,749.9 |
| Diamond | 1,750+ |

Rating uses the complete locally available first-parent score history, even when only 30 rows are visible. It is project-local and separately versioned as `ladder-v1`: **not opponent-based Elo, a global rank, or proof that code gets better with age**. The latest-only export contains neither historical rows nor a cumulative rating.

## What makes the score higher?

| Component | Weight | Higher score |
| --- | ---: | --- |
| Input retention | 28% | More observed edits linked to human messages remain |
| Artifact survival | 28% | Less observed rewriting is discarded before the commit |
| Task fulfillment | 14% | More declared attempts finish with committed artifact evidence |
| Resource discipline | 30% | Lower scope-adjusted input, visible output, compute, and tool pressure |

The retention weights preserve the original 40:40:20 proportions within their 70% share. Installing more Skills or spawning more agents does not earn points.

Small samples are smoothed toward **50**, and missing evidence stays neutral rather than receiving 100%. A smooth logistic curve avoids easy extremes. Evidence confidence below 65% is marked **provisional**.

| Grade | Score |
| --- | --- |
| S | 90+ |
| A | 80–89.9 |
| B | 65–79.9 |
| C | 50–64.9 |
| D | 35–49.9 |
| E | Below 35 |

The included calibration examples range from **43.6** for low retention and high resource pressure to **81.4** for strong retention and modest resource pressure at the same scope. These are examples, not a claim about the distribution of real developers.

**This is a process score, not a code-quality score.** A necessary experiment can reduce survival. Removing bad code can improve the software. Temporal prompt attribution is not semantic understanding, file units are only structural/content proxies, and declared task completion is not a passed acceptance test. Never retain bad code to improve a number.

Read the [complete formulas, normalization anchors, missing-data policy, and limitations](docs/METRICS.md). Raw measurements remain separate; the score is stored at `proof.score.value`.

### Record task outcomes explicitly

```bash
aipow task checkout --status active
# Work on the task...
aipow task checkout --status completed --evidence src/checkout.py tests/test_checkout.py
```

Use stable IDs. Reopening a completed or dropped task starts another attempt. Evidence paths must be repository-relative and exist with inspectable content in the final commit. Tasks are not silently inferred by a paid scoring model.

## Use your preferred agent

```bash
aipow claude
aipow run -- your-agent
aipow run -- bash
aipow sample
```

| Integration | Capture | Limits |
| --- | --- | --- |
| Claude Code | Prompt/display hooks, tool and sub-agent events, incremental model-usage metadata | Hook/transcript fields vary by version; late events can cross boundaries |
| laintas-cli development integration | Native input/display, usage, tools, Skill injection, child creation | Requires a build bundling this integration; auxiliary workflows may leave gaps |
| Generic wrapper | Run boundaries and sampled files | Detailed prompt, token, and tool accounting needs an adapter |
| Manual editing | File samples through a wrapped shell or sample command | Rapid/unobserved writes cannot be recovered |

For a compatible laintas-cli build:

```bash
laintas-cli pow init
laintas-cli
laintas-cli pow report --html
laintas-cli pow verify
```

Both frontends share the per-worktree store. AI-PoW is independent of laintas-cli. Claude settings are invocation-scoped; the adapter does not change global settings or tool permissions. There is no dedicated Codex/OpenCode transcript parser in this release.

## What verification proves

```bash
aipow verify --bundle /path/to/commit-proof.jsonl
```

Verification checks the proof hash, event chain and sequence, recomputed measurements and prices, Git commit/tree/parents, and the score rebuilt from trace evidence and committed blobs.

It proves **local consistency**, not truthful execution, complete capture, accurate timestamps, or correct software. An operator can fabricate an entire local chain. Unqualified payment systems and developer leaderboards should not rely on it.

The protocol retains version 0.1 and supports legacy unscored proofs. Scoring is separately versioned as `balanced-v1`; changing policy must not silently rewrite old sealed scores.

## Storage, privacy, and overhead

```text
<worktree-git-directory>/ai-pow/
  events.sqlite3
  reports/
    <commit>.html
  recording-error       # present after an observed recorder failure
```

| Resource | Bound / behavior |
| --- | --- |
| Event database | 64 MiB default per worktree; no automatic evidence deletion |
| Event payload | Approximately 16 KiB |
| File scan | 2,000 candidates; 256 KiB/file; 16 MiB content/scan |
| Fingerprints | Up to 64 units/file; unchanged-file metadata cache |
| Scoring | Up to 4,096 relevant events and 128 committed blobs |
| HTML cache | Newest 20 reports, up to 16 MiB; one report at most 8 MiB |
| History | Up to 30 previous first-parent commits |
| Wrapper | Samples every two seconds; no permanent daemon |
| Git commands | Output bounds and ten-second per-command timeout |

The database cap excludes SQLite journals, explicit exports, and reports. Scoring memory is bounded by selected events and fingerprints, but is not a hard process-RSS cap. Commit scoring can invoke multiple Git commands; large repositories may take longer. Run `python scripts/benchmark.py` on your workload. Raise database capacity with `aipow quota --max-mib 128`; this does not recover previously missed events.

Built-in adapters retain hashes, sizes, and metadata, not prompt/source bodies, tool arguments/output, or reasoning. Reports include commit subjects and dates. Hashes are not anonymization. Generic event payloads are caller-controlled. Review exports before sharing; see [SECURITY.md](SECURITY.md).

Amend, rebase, checkout, and missed intervals can make attribution ambiguous. Use `aipow reset-boundary` when requested; old events are retained, not reassigned. Worktrees are independent. Partial staging is checked against committed blobs, but interval association is not proof of causal ownership.

## Reference prices and event API

Prices are opt-in snapshots; no live rates are bundled. Replace the fictional rates in [the example](examples/price.example.json) before running:

```bash
aipow price-set /path/to/price.json
```

Reference cost is list-price accounting, not actual payment or measured intelligence. Missing usage stays unknown. Estimated usage stays distinguishable. Cached input and reasoning are not counted twice.

Adapters can emit metadata directly:

```python
from ai_pow import Recorder, text_meta

recorder = Recorder("/path/to/repository")
recorder.record("human.message", text_meta("Implement search"), source="my-agent")
recorder.record("tool.call", {"name": "test-runner"}, source="my-agent")
```

`aipow emit TYPE --source NAME` also accepts JSON on stdin. Stable event IDs deduplicate identical retries and reject conflicting replays. See the [protocol](docs/PROTOCOL-v0.1.md).

## Develop and contribute

```bash
git clone https://github.com/lin7c/ai-pow.git
cd ai-pow
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 python3 scripts/build_demo.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/benchmark.py
```

Browser checks are optional development tooling: install Playwright and Chromium, then run `node scripts/test_report_browser.cjs`. Set CHROME_PATH to use an existing Chrome binary. Reports themselves have no dependencies.

Tests clean up temporary repositories and processes. See [validation](docs/VALIDATION.md) and [contribution guidelines](CONTRIBUTING.md). Useful next contributions include stronger adapters, explicit requirement provenance, cross-worktree links, external attestations, and controlled quality benchmarks.

## License

[MIT](LICENSE). Embed it in your own agent, or use it independently.

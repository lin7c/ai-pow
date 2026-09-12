# AI-PoW

**A verifiable work history for AI-assisted software.**

[![Tests](https://github.com/lin7c/ai-pow/actions/workflows/tests.yml/badge.svg)](https://github.com/lin7c/ai-pow/actions/workflows/tests.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

AI-PoW records the human input, model usage, agent activity, and file versions observed during development, then binds that history to a Git commit. Another person can verify that an exported trace, its reported measurements, and the referenced Git objects agree.

It answers **“What work was observed while this version was being made?”** It does not assign developers a productivity score or claim that a local log proves honest execution.

**Status:** v0.1, an experimental local recorder and protocol. Python 3.10+ and Git are required. There are no third-party runtime dependencies, hosted services, or background scoring models.

## Why AI-PoW?

A Git diff shows the result. It usually does not show the prompts, repeated attempts, model usage, tool calls, or intermediate file versions that preceded it. A chat transcript captures some of that history, but is often detached from the version it helped produce.

AI-PoW brings those observations together without reducing them to an arbitrary number:

| Dimension | Recorded observations |
| --- | --- |
| Human input | Message counts, text metadata, explicitly labeled token estimates |
| Visible AI output | User-facing text, including progress updates |
| Machine work | Model calls, reported or estimated usage, optional reference prices |
| Agent activity | Tool calls and results, MCP identifiers, Skill context use, parent/child events |
| Artifacts and tasks | Sampled file-version transitions and explicitly supplied task events |

The implementation includes a bounded SQLite event store, a SHA-256 event chain, per-commit proofs, streaming export and verification, a Claude Code adapter, and a generic command wrapper. The same core is bundled into the development version of laintas-cli.

## Quick start

Install from this repository into a virtual environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install "git+https://github.com/lin7c/ai-pow.git"

cd /path/to/your/git-project
aipow init
aipow claude
```

Work normally, then commit and inspect the proof:

```bash
git add src/app.py
git commit -m "Implement the feature"

aipow report
aipow verify
aipow export /path/outside/project/commit-proof.jsonl
```

`init` installs a post-commit hook when it can do so without replacing an existing or shared hook. Otherwise, it prints the command to integrate manually. Use `aipow init --no-hook` for manual sealing, followed by `aipow seal` after each commit.

No data is recorded for a project until it is initialized. Proofs are stored in the worktree's Git metadata directory, not in the application source tree.

### Use another agent or capture manual edits

```bash
aipow run -- your-agent
aipow run -- bash
# Or capture a single file observation without a wrapper:
aipow sample
```

The generic wrapper captures run boundaries and file samples. It does **not** infer prompts, token usage, or tool calls from terminal output. Agent authors can provide those through the event API.

### Use the bundled laintas-cli integration

```bash
laintas-cli pow init
laintas-cli
laintas-cli pow report
laintas-cli pow verify
```

This requires a laintas-cli build containing AI-PoW. Its native adapter and the standalone command share the same per-worktree store. The standalone project can be used independently of laintas-cli.

## What verification means

A successful verification returns fields such as:

```json
{
  "integrity_verified": true,
  "git_tree_verified": true,
  "trust": "local-self-reported",
  "completeness_verified": false,
  "work_authenticity_verified": false,
  "quality_verified": false
}
```

The verifier checks the proof hash, event sequence and hash chain, recomputed measurements and prices, commit metadata, and Git object integrity. An exported bundle can be checked against a repository containing the referenced commit:

```bash
aipow verify --bundle /path/to/commit-proof.jsonl
```

**A local operator can fabricate or omit events and rebuild the entire chain.** Hash consistency is not proof of execution, accurate timestamps, complete capture, or useful work. AI-PoW is not a consensus proof-of-work mechanism and should not be used as an unqualified basis for payments or rankings.

## Measurements, not a universal score

AI-PoW deliberately leaves `overall_score`, `efficiency`, and Human/Artifact/Task Survival unset in v0.1. `ranking_eligible` is false.

Dividing a weighted survival score by “normalized work” has several unresolved problems: survival is not quality; the weights and denominator need an external definition; incomplete capture can look efficient; and splitting tasks or commits can change the result without changing the work.

The current accounting rules are:

- **Unknown is not zero.** Incomplete model-token totals are `null`, with separate known subtotals and missing-field counts.
- **Estimates stay identifiable.** Model usage is grouped by model and measurement basis. Text counts retain their tokenizer or estimation method.
- **Streaming does not inflate byte estimates.** The built-in UTF-8 bytes/4 heuristic rounds after aggregating bytes, rather than rounding every display chunk independently. It remains a rough estimate, not the provider's tokenizer.
- **Reasoning and cached input are subsets.** They are not added a second time to their parent token buckets.
- **Price is not intelligence.** Reference USD reflects the supplied price snapshot, not physical compute, output quality, or agent capability. Estimated and provider-reported pricing subtotals remain separate.
- **Activity is not an achievement score.** Extra tools, agents, calls, or edits do not earn points.

For fair comparisons, first fix the task, starting state, acceptance tests, measurement requirements, and pricing basis. Compare resource tradeoffs among results that meet the quality threshold. See [Metrics and scoring](docs/METRICS.md) for the proposed benchmark layer and worked counterexamples.

## Agent support

| Integration | Available capture | Important limits |
| --- | --- | --- |
| Claude Code | Prompt and display hooks, tool events, sub-agent events, incremental transcript usage | Fields vary by version; late usage can cross commit boundaries |
| laintas-cli development integration | Native inputs, interactive visible text, usage-tracker records, tool events, Skill context injection, child creation | Auxiliary workflows and missing provider fields can leave gaps |
| Other agents | Run boundaries and file sampling through `aipow run` | Detailed accounting requires explicit events; no dedicated Codex/OpenCode parser is included |
| Manual work | File samples inside a wrapped shell or through `aipow sample` | Unobserved intermediate writes cannot be reconstructed |

Claude is configured with invocation-scoped `--settings`; AI-PoW does not modify global Claude settings or relax tool permissions. The adapter uses [official Claude Code hooks](https://code.claude.com/docs/en/hooks). Transcript imports collect usage metadata, not conversation text. Existing transcript content is skipped at session start; rows predating recorder initialization are excluded.

## Reference pricing

Pricing is opt-in. Supply a snapshot for the exact model and applicable pricing tier:

```bash
aipow price-set /path/to/ai-pow/examples/price.example.json
```

The example contains **fictional rates**. Replace them with the appropriate rates and source before use. No current provider prices are bundled or fetched automatically.

```text
reference USD = (
    (input - cached input) * input rate
  + cached input * cache-read rate
  + cache creation * cache-write rate
  + output * output rate
) / 1,000,000
```

The full snapshot and its hash are embedded in each priced event. Missing usage buckets leave the call unpriced. Cache creation is separate from normalized input; reasoning is already included in output. Multi-tier, batch, region, or cache-TTL pricing must be represented correctly by the adapter or left unpriced.

## Storage and overhead

Data is stored at:

```text
<git rev-parse --absolute-git-dir>/ai-pow/
  events.sqlite3
  recording-error       # Present after an observed recorder failure
```

| Resource | Default behavior |
| --- | --- |
| Database | 64 MiB per worktree; no automatic evidence deletion |
| Event payload | Approximately 16 KiB maximum |
| File sampling | Up to 2,000 candidates, 256 KiB per file, 16 MiB content per scan |
| Unchanged files | Metadata cache avoids repeated content reads |
| Command wrapper | Samples every two seconds; no permanent daemon |
| SQLite | Short transactions, one-second write-lock timeout, FULL synchronization |
| Git subprocesses | Bounded output and a ten-second timeout |
| Transcript importer | Incremental offsets; approximately 8 MiB per pass and 1 MiB per row |

SQLite's rollback journal and exported bundles require additional disk space: **the database cap is not a cap on total disk use**. Increase the quota with `aipow quota --max-mib 128`. Previous recording failures remain visible; raising the quota does not recover lost events.

One local 1,000-event benchmark measured a 14.2 ms median write, a 138 ms scan of 1,000 unchanged files with zero source bytes reread, and a 0.84 MiB database including file state. These are workload-specific measurements, not performance guarantees. See [Validation](docs/VALIDATION.md), or run `python scripts/benchmark.py` yourself.

## Privacy and boundaries

Built-in adapters store text hashes, sizes, usage, and bounded event metadata. They do not retain prompt bodies, source contents, tool arguments, tool output, or reasoning text. File paths are hashed. Hashes are not anonymization: short text or known paths may be guessed. Generic `emit` payloads are caller-controlled; inspect a bundle before sharing it.

Common dependency/build directories, environment files, key files, symlinks, and special files are excluded. Exclusions and limits mean capture is partial. See [Security](SECURITY.md).

Proofs are generated **after** a commit and bind its actual commit, tree, and parent hashes. This avoids embedding a proof containing a commit's own hash inside that same commit.

The supported interval is the recorder's observed base to its direct successor. Merge commits retain all parents and use the first parent as the base. Ambiguous history changes such as amend, rebase, or missed commits require `aipow reset-boundary`; old events are retained.

**Window association is not causal attribution.** Unstaged work, concurrent edits, and late usage may belong to a different logical task than the staged diff. Separate worktrees have separate stores; child work is not automatically charged again when merged. File transitions are sampled revisions, not semantic edit units.

## Event API

Python integrations can emit metadata directly:

```python
from ai_pow import Recorder, text_meta

recorder = Recorder("/path/to/repository")
recorder.record("human.message", text_meta("Implement search"), source="my-agent")
recorder.record(
    "tool.call",
    {"name": "test-runner", "call_id": "call-42"},
    source="my-agent",
    event_id="my-agent:session-7:call-42",
)
```

`aipow emit TYPE --source NAME` accepts a JSON payload on standard input. Stable event IDs deduplicate identical retries and reject conflicting replays. The [protocol specification](docs/PROTOCOL-v0.1.md) defines event types, token normalization, serialization, pricing, and verification.

## Development

```bash
git clone https://github.com/lin7c/ai-pow.git
cd ai-pow
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 python3 scripts/benchmark.py
```

Tests create temporary repositories and clean them up. GitHub Actions runs the standalone tests across supported Python versions. No provider credentials or paid model calls are required.

Contributions are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md); protocol and measurement changes should include counterexamples and compatibility tests. The roadmap includes richer adapters, semantic provenance with explicit uncertainty, linked worktree proofs, signed external checkpoints, and benchmark-specific evaluation.

## License

[MIT](LICENSE). AI-PoW can be embedded into other agents without depending on laintas-cli.

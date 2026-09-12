# AI-PoW Protocol 0.1.0

Status: implemented local MVP, not a consensus or remote-attestation protocol.

## 1. Event

```json
{
  "v": "0.1.0",
  "seq": 1,
  "epoch": "uuid-hex",
  "event_id": "unique-id",
  "time_ms": 1789171200000,
  "previous": "0000000000000000000000000000000000000000000000000000000000000000",
  "type": "tool.call",
  "source": "laintas-native",
  "data": {"name": "shell", "call_id": "call-1"},
  "hash": "sha256-of-canonical-event-excluding-hash"
}
```

Canonical serialization: JSON, recursively sorted object keys, UTF-8, literal Unicode,
no optional whitespace, no NaN/infinity/floats, integers within ±(2^53−1).
Amounts/rates use decimal strings. SHA-256 is over canonical bytes, excluding the `hash` field.
Array order is significant. Event IDs are immutable; identical replays deduplicate, conflicting replays fail.
Sequence is globally increasing in one recording database. Each worktree has a separate database.
Timestamps are local observation times, not authenticated execution times.

Implemented types:

| Type | Payload |
| --- | --- |
| human.message | tokens, token_method, bytes, characters, sha256, optional session/run/agent IDs |
| assistant.visible | same text metadata, channel (`commentary`, `final`, or `display`) |
| model.usage | model, measurement, normalized token buckets, optional actual/reference price |
| tool.call | name, call_id, optional mcp_server and session/run IDs |
| tool.result | name, call_id, ok |
| skill.used | name, basis (e.g. context_injected) |
| agent.spawn / agent.stop | agent_id, parent_agent_id where known |
| task.change | explicit caller-supplied task metadata, no automatic correctness assertion |
| run.start / run.stop | run_id/session_id, executable basename/exit_code where observed |
| file.observed | path_hash, before, after (null represents absence) |
| coverage.gap | reason plus bounded non-content metadata |

Adapter identities, IDs, status booleans and usage counts are claims from a local collector.
Observation is not attestation. A `tool.call` is a dispatch attempt, not proof of successful execution.
`skill.used` means supplied to context/observed invocation, not proof the model followed the instructions.

## 2. Machine usage and pricing

`measurement` is `provider_reported` or `estimated`; reports MUST keep these separate.
Provider-reported means obtained from a local response/transcript, not provider-signed.

- `input_tokens`: uncached input + cache-read input.
- `cached_input_tokens`: subset of input, never separately added to total input.
- `cache_write_tokens`: cache creation input, excluded from input_tokens in this normalized format.
- `output_tokens`: all billed output, including any reasoning already billed as output.
- `reasoning_tokens`: subset of output; null when undisclosed.
- Missing buckets remain null/unknown; no inference that absent means zero.

Current summaries use `algorithm: observed-v2`. A model bucket with missing usage
reports a null total for that field, its `known_token_subtotals`, and a
`missing_field_calls` count. Text buckets retain per-method observations and
unknown-event counts. UTF-8 byte estimates aggregate bytes before rounding, so
stream fragmentation does not inflate the estimate. Reference prices are also
broken down by measurement basis. Completeness refers only to observed calls.

Proofs without an explicit summary algorithm retain the `observed-v1` reducer.
Verifiers MUST select the recorded interpretation, not rewrite old summaries.
An unknown algorithm is rejected. See [Metrics and scoring](METRICS.md).

Example price file (illustrative rates, NOT real provider prices):

```json
{
  "model": "example-model",
  "source_url": "https://example.invalid/pricing",
  "effective_date": "2026-09-12",
  "input_per_million": "2",
  "cached_input_per_million": "0.2",
  "cache_write_per_million": "2.5",
  "output_per_million": "10"
}
```

Install with `aipow price-set price.json`. Rates are not fetched automatically.
The snapshot and its hash are copied into every priced event, making later price changes irrelevant.
If a provider has mixed cache TTLs, batch/priority/region/context tiers, the adapter must first separate those
calls/buckets or leave them unpriced; a single blended rate must not be passed off as exact standard billing.

Reference USD = `((input-cached)*input_rate + cached*cached_rate + cache_write*write_rate + output*output_rate)/1000000`.
Decimal arithmetic with an explicit 80-digit context is used for new pricing; reasoning is NOT added again. The verifier recomputes the cost.
The sum is labeled `reference_usd_known_subtotal` alongside priced/unpriced call counts.
An actual payment and an estimated reference price are separate concepts.

## 3. Commit proof

The proof stores protocol version, commit, tree, all parents, first-parent base, epoch,
first/last sequence, previous-chain anchor, terminal trace hash, derived summary,
capture/trust limits and `proof_hash`.
`proof_hash` hashes the canonical object excluding itself. Null first/last sequence denotes an empty interval.

Proof generation occurs after a commit. The proof is stored outside the tracked tree. It does not require
embedding a commit-dependent proof into that same commit. A future pre-commit commitment would instead
bind the preselected staged tree and pre-commit trace root, with a separate post-commit envelope.

Epochs cover observation windows, not unique causal attribution of costs to lines.
Initial worktree contents form an uncounted baseline, including pre-existing uncommitted changes.
Unstaged edits can span several windows. Checkouts/amends/rebases/missed windows fail closed for attribution,
with explicit reset preserving old records. Manual reset creates an unsealed historical epoch.
Git post-commit can be bypassed; all capture is partial in v0.1.

## 4. Export and verification

One JSONL bundle: first line `{"proof": <proof>}`, followed by canonical event lines including their hashes.
Export refuses to overwrite an existing file. The destination Git repository must contain the referenced commit.

```bash
aipow verify --bundle /path/to/commit-proof.jsonl
```

Verifier MUST:

1. Check proof version and canonical SHA-256.
2. Resolve commit metadata and compare commit, tree, all parents and first-parent base.
3. Check Git object integrity (`git fsck --strict`; errors/timeouts fail).
4. Stream the event range, recomputing each hash and checking sequence, epoch and previous-hash linkage.
5. Check terminal hash and exact range; reject a missing suffix/prefix.
6. Recompute summaries and reference prices; compare them with the proof.
   For proofs carrying the optional application-0.2 `score` extension, rebuild
   scoring evidence from trace events and committed blobs, and compare the
   versioned score as well. Unknown score algorithms fail verification.
7. Report integrity separately from authenticity, completeness, task quality and efficiency.

The anchor of a partial exported range is self-reported. Without a trusted previous proof/signature or external
publication, rewriting the entire proof and trace is undetectable. Full local consistency MUST NOT be rendered as
remote attestation, timestamp proof, proof of non-omission, or measured useful computation.

## 5. Application 0.2 scoring extension

Protocol version remains 0.1.0. New proofs optionally include `score`, covered by
the existing proof hash. Its `algorithm` is `balanced-v1`; decimal quantities use
strings, preserving canonical JSON rules. Legacy proofs without this extension
remain verifiable without being rewritten.

`file.observed` may include `units_before`, `units_after` (up to 64 SHA-256 hashes
each), `unit_kind`, `units_truncated`, and an explicit `prompt_id`. Python units
are top-level AST fingerprints; other files use content blocks. These are
bounded proxies, not universal semantic edit units. Samples omit source text.

`task.change` may include a stable `task_id`, `status` (active/completed/dropped),
and `evidence` (up to 32 hashed repository-relative paths). Task completion
requires committed artifact evidence but does not attest acceptance tests.

See [the scoring specification](METRICS.md) for formulas, limits, confidence,
scope cohorts, history rules, and the missing-data policy. HTML reports are
derived application artifacts, not an additional source of proof authority.

Semantic requirement provenance, robust rename/move attribution, external
receipts, signed checkpoints, and controlled quality benchmarks remain future
layers. H/A text counts are attention proxies, not measured human time.

## References

- [Git hooks](https://git-scm.com/docs/githooks)
- [Git notes](https://git-scm.com/docs/git-notes)
- [Claude Code Hooks reference](https://code.claude.com/docs/en/hooks)

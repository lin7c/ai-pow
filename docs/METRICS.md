# Metrics and scoring

AI-PoW v0.1 measures observed resource use and provenance. It deliberately provides no universal score.

## Why the original efficiency formula is insufficient

The proposed expression was:

```text
E = (human_survival^0.4 * artifact_survival^0.4 * task_survival^0.2)
    / normalized_work
```

It has no defensible interpretation until each numerator term, the work denominator, the quality requirement, and capture requirements are defined.

| Problem | Counterexample | Consequence |
| --- | --- | --- |
| Survival is not quality | Removing vulnerable code lowers surviving edits | A successful repair can score worse |
| Exploration has value | A test disproves an approach and is later removed | Discarded work may be necessary evidence |
| Output quality is absent | A cheap incomplete solution uses fewer resources | Cost alone can reward failure |
| Units are incompatible | Tokens, dollars, and tool calls are added directly | The denominator has no meaningful unit |
| Missing capture looks efficient | One adapter misses half the model calls | A less complete recorder can appear better |
| Task granularity is mutable | One requirement is split into ten tasks | Counts change without a different outcome |
| Commit boundaries are mutable | A developer squashes or splits commits | Per-commit rankings become manipulable |
| Zero and unknown differ | There were no measured artifact operations | The survival ratio is undefined, not 100% |
| Costs vary by baseline | Providers change list prices or discount a tier | A price change can masquerade as an efficiency change |
| Weighted products have edge cases | One survival term is zero | A useful result receives a zero numerator |

Even a fixed weighted score expresses preferences rather than an objective measure of developer ability. The protocol must not silently choose those preferences.

## Corrections implemented in observed-v2

### Text accounting

The built-in heuristic is `ceil(UTF-8 bytes / 4)`. It is language-dependent and is not an exact tokenizer or a measurement of human reading time.

Previously, displaying eight one-byte chunks yielded eight estimated tokens, while displaying the same eight bytes at once yielded two. The new summary aggregates bytes within each text direction and estimation method before rounding. Event counts still reflect the actual number of observations.

Different tokenizer/method totals remain visible in `methods`. `unknown_token_events` and `tokens_complete` identify missing text accounting. Convenience token subtotals are not evidence that different tokenizers are comparable.

### Missing model usage

If one observed call reports 10 input tokens and another omits its input usage, the total is:

```json
{
  "input_tokens": null,
  "known_token_subtotals": {"input_tokens": 10},
  "missing_field_calls": {"input_tokens": 1}
}
```

The known subtotal is a partial observation, not the true total. Reported and estimated usage use different model buckets. Neither capture absence nor a null value should be converted to zero when ranking systems.

### Reference pricing

Prices are frozen per event. Pricing arithmetic has an explicit decimal precision rather than inheriting an embedding application's decimal settings. Cache reads and reasoning remain subsets, not extra tokens.

`reference_usd_by_measurement` separates prices calculated from provider-reported usage and estimated usage. Completeness applies only to observed calls; it does not prove that all calls were captured. A provider-reported value read from a local transcript is not a signed provider receipt.

### Versioned interpretation

New summaries include `algorithm: observed-v2`. The original `observed-v1` reducer remains available for proofs without that field, so an existing proof is not silently rewritten under a newer metric definition.

## A better benchmark layer

This is a proposal for future benchmark tooling, not a feature shipped in v0.1.

1. Define the task and immutable starting state, including accepted inputs and allowed tools.
2. Define a quality gate with acceptance tests and explicit failure/security criteria. Compare resources only for results meeting it.
3. Declare required capture capabilities and reject runs missing required measurements. `complete_for_observed_calls` alone is insufficient.
4. Use a fixed evaluation window across commits, with run IDs, provenance links, and a non-duplicating allocation policy.
5. Report a resource vector first: human input, visible text, reference cost, elapsed time, and any independently measured human time. Display unknown components explicitly.
6. Compare tradeoffs using Pareto dominance: one result dominates another only if it is no worse on every comparable resource and strictly better on at least one.
7. If a benchmark needs a scalar, publish positive normalization baselines, non-negative weights, a quality definition, and a missing-data policy in a versioned specification before evaluating runs.

A possible benchmark-specific scalar is:

```text
normalized_cost = sum(weight[j] * resource[j] / baseline[j])
efficiency = quality / (1 + normalized_cost)
```

All required resources must be known, `baseline[j] > 0`, weights sum to one, and quality is independently defined on a fixed scale. Runs failing the quality gate are ineligible, not cheap winners. This is one policy choice, not a standard AI-PoW score. Report sensitivity to weights and do not charge correlated dimensions twice without justification.

## Future survival analysis

Human survival requires stable requirement identities and evidence links through split, merge, revision, and withdrawal. Artifact survival requires a declared unit, rename/delete/revert semantics, and provenance through transformations. Task survival requires fixed granularity.

Keep observations separate from inferences. Publish the algorithm/version, denominator, coverage, uncertainty, and correction history. A zero denominator yields `null`. Never equate “not retained” with “not useful,” and keep survival out of a quality score unless the benchmark can justify that relationship.

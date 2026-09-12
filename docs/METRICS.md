# Scoring specification: balanced-v1

AI-PoW 0.2 ships a **process score**, separate from immutable event measurements. It expresses a preference: retain more observed work while using fewer resources for a similar-sized outcome. It does not measure correctness, developer ability, or commercial value.

Missing evidence is neutral, not perfect. Small samples stay near 50. More tools, Skills, sub-agents, tokens, or edits do not directly earn points.

## Weights and direction

| Component | Weight | Higher when |
| --- | ---: | --- |
| Input retention | 28% | More edits linked to human messages survive |
| Artifact survival | 28% | More observed structural/content operations survive |
| Task fulfillment | 14% | More declared attempts finish with committed evidence |
| Resource discipline | 30% | Scope-adjusted input, output, compute, and tool pressure is lower |

The original 40:40:20 retention proportions remain inside a 70% retention share. These are explicit policy choices, not empirically established universal weights.

## Evidence definitions

**Artifact operations.** Python files use top-level AST fingerprints. Other UTF-8 files use groups of eight nonempty, stripped lines. Binary files use 4 KiB blocks. Each sampled file retains at most 64 unique fingerprints. These are structural/content proxies, not interchangeable semantic work units. Modification counts as removal plus addition. Identical units are deduplicated.

The first observed before-state is compared with the actual committed after-state. Only observed operations in that final difference survive. A full revert retains zero operations; deletion of existing code can survive. Latest lineage prevents repeated additions from counting as multiple surviving additions. Renames currently appear as deletion plus addition.

**Input retention.** A file event belongs to its explicit prompt_id, if supplied, or the most recent human message. Each linked prompt's retained/raw operation fraction is token-weighted (minimum weight one). This is a temporal attribution proxy, **not semantic information survival**. Unlinked prompts reduce confidence. Concurrent work can make attribution wrong.

**Task fulfillment.** Stable task IDs carry active, completed, or dropped statuses. Reopening a completed/dropped task starts another attempt. Completion counts only with a nonempty evidence list whose paths contain inspectable, nonempty committed units. Existence is not an acceptance test. Task granularity and completion are local claims. Pure-deletion tasks need another evidence artifact, such as a committed test, in this version.

**Scope.** Final structural/content units in changed files, or retained operations if larger. This is size, not complexity. Editing one line in a large existing file may increase the resource allowance. Cohorts: small <8, medium <32, large <128, extensive otherwise. Cross-language and cross-project rankings are unsupported.

## Smoothing and confidence

For retained count k out of n observations:

```text
raw ratio  = k / n                    # null when n = 0
quality    = (k + 2) / (n + 4)        # Beta(2,2) smoothing
confidence = n / (n + 4) * reliability
```

Input confidence uses linked prompt count, not token mass; effective k is its token-weighted ratio times that count. Input reliability is 0.7 times linked/all prompts. Artifact reliability is checked/observed operations, multiplied by 0.8 when capture limits apply. Task reliability is one for the declared evidence basis, not objective task truth.

For resources, scale = max(1, sqrt(scope_units)):

| Resource | Pressure denominator | Resource share |
| --- | --- | ---: |
| Human input tokens | 800 × scale | 25% |
| User-visible tokens | 1,200 × scale | 15% |
| Reference USD | 0.5 × scale | 45% |
| Tool calls | 12 × scale | 15% |

If pricing is incomplete but observed model input/output buckets are complete, model tokens use 40,000 × scale instead. Cache creation is included once; reasoning is already in output. Different measurement/pricing bases mean even same-scope comparisons are descriptive, not controlled benchmarks.

```text
resource_quality = 1 / (1 + pressure^0.7)
efficiency_quality = sum(available_share * resource_quality)
                   + 0.5 * missing_share
efficiency_confidence = available_share_total * min(1, scope_units / 8)
```

No observed events means unknown, not zero cost. Completeness covers observed calls only. Missing dimensions keep their weights at neutral quality with zero confidence. Every explicit gap divides all component confidences by 1 + gap_count.

```text
L = 0.5 + sum(weight * confidence * (quality - 0.5))
score = 100 / (1 + exp(-5 * (L - 0.5)))
```

The result is rounded to one decimal. The theoretical outer envelope is approximately 7.6–92.4; conservative attribution narrows practical reach. Zero and 100 are not intended milestones. Missing evidence starts at 50, meaning **uncertain**, not average-quality code. Aggregate confidence below 65% is labeled provisional. Confidence is a policy-based indicator, not a calibrated probability.

Grades: S ≥90, A ≥80, B ≥65, C ≥50, D ≥35, E below35. These are descriptive bands, not population percentiles.

## Reproducible examples

Run `python scripts/build_demo.py`. Explicitly synthetic fixtures use the production algorithm:

| Retention input | Reference cost | Score | Grade |
| ---: | ---: | ---: | --- |
| 40% | $14 | 43.6 | D |
| 62% | $10 | 58.7 | C |
| 76% | $7 | 68.2 | B |
| 85% | $5 | 74.0 | B |
| 98% | $2.40 | 81.4 | A |

Scope and other resources are held fixed; task counts are rounded. These demonstrate the policy, not a measured real-world score distribution. With other inputs fixed, higher cost lowers the score and higher retention raises it. Deleting a faulty feature may lower retention while improving the software: never keep faulty code to protect a score.

## History and verification

Iteration reports include up to 30 previous first-parent commits. Averages exclude this commit, unscored commits, and other algorithms. Same-scope averages additionally match the scope cohort. Local percentile requires at least three matching prior commits and uses midpoint ranks for ties. It is not a global ranking.

Proofs include the algorithm, score, components, and evidence in their hash. Verification rebuilds measurements from the trace, evidence against Git blobs, and the score. It does not trust a supplied evidence subtotal. Scoring analyzes up to 4,096 relevant events and 128 bounded committed blobs; limits are explicit. The complete trace is still verified.

Application 0.2 retains protocol 0.1 and accounting reducer observed-v2. Legacy observed-v1 proofs verify without adding a score to their sealed data. Viewing a legacy proof may calculate a separate provisional display score; that score was not sealed by the old release.

## Cumulative project score: commit-sum-v1

The cumulative score starts at **0**. Each recorded commit contributes its
existing score exactly once, unchanged:

```text
total[0] = 0
total[n] = total[n-1] + recorded_commit_score[n]
```

Example: 81.4 + 43.6 + 50.0 = 175.0. There is no additional code-line calculation,
confidence or scope weighting, eligibility threshold, deduction, tier, or upper
limit. All weighting belongs to the existing single-commit score, not this sum.

The full locally available first-parent history is replayed; only the latest
30 historical rows are displayed. Missing scores contribute nothing and are
not inferred. Existing scores from earlier algorithms are added as recorded,
not recomputed or filtered out. History averages still use their separately
documented comparison rules. Reopening a report does not add another iteration.

Totals are derived report data, not an additional value sealed into the latest
single-commit proof. Reproduction requires the relevant historical scores.
Restoring missing proofs or changing the Git lineage changes the available sum.
Oversized history fails explicitly rather than silently restarting from zero.

This is a cumulative total, not a quality rating or an anti-gaming mechanism.
It inherits the limitations of the per-commit scores and grows with recorded
commits. The latest-only export omits both historical rows and the total.

## Accounting remains separate

Unknown usage totals are null with known subtotals. Estimates retain their basis. Text estimates aggregate UTF-8 bytes before rounding by four, avoiding stream-chunk inflation. Reference prices are frozen per event, use explicit decimal precision, and separate estimated from provider-reported usage. Cached input and reasoning are subsets, not extra parent-bucket tokens. Price is money, not measured intelligence or physical computation.

The raw summary's legacy overall_score and efficiency fields remain null for compatibility. The implemented score is at `proof.score.value`. Ranking eligibility remains false because this is not a controlled benchmark.

## Limitations

Local operators can omit events or fabricate a history. Selective missingness can move a poor score toward neutral; hashes cannot prevent that. Splitting tasks or commits, padding files, choosing price snapshots, or missing rapid writes can change scores without improving work. More observations can move scores away from the prior at an unchanged ratio. No local score makes gaming impossible.

Competitive ranking or payment requires fixed tasks, starting states, acceptance tests, capture capabilities, prices, and external attestations. This release does not claim those. Future scoring changes must use a new algorithm ID and preserve old sealed scores.

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

## Project iteration ladder: ladder-v1

The per-commit score above remains 0–100. Iteration reports additionally replay
the full available first-parent history of locally stored, matching-algorithm
scores to derive a project rating. Its initial value is 1,000. Unscored commits
and commits with no checked artifact operations or no scope do not move it.

```text
target = 1000 + 25 * (commit_score - 50)
scope_factor = min(1, scope_units / 8)
delta = 40 * tanh((target - previous_rating) / 300)
           * confidence^2 * scope_factor
rating = round(previous_rating + delta, 1)
```

Each iteration moves by at most 40 points. Small or uncertain observations have
very little influence; missing artifact evidence has none. Strong repeated
results move toward a target with diminishing gains. A weaker result can lower
an established rating even if its single-commit score is above 50. There is no
automatic participation bonus and no permanent guarantee of upward movement.

Tiers: Bronze below 1,100; Silver from 1,100; Gold from 1,300; Platinum from
1,500; Diamond from 1,750. These are product thresholds, not calibrated skill
bands. With an identical commit score of 80, confidence of 0.8, and scope at
least eight, successive updates start near +25.3, +25.2, and +25.1; eventually
they approach a rating of 1,750 rather than growing without bound.

This is not Elo because there are no opponents or match outcomes. Ratings are
derived report data, not an extra claim sealed inside the single-commit proof.
Reproducing one requires the relevant local historical proofs, not only the
latest exported bundle. Missing proofs freeze updates and restoring historical
proofs can change the derived rating. History rewrites likewise change its
input lineage. Oversized Git-history output fails explicitly rather than
silently resetting the baseline. Only 30 historical rows are displayed; the
calculation does not discard earlier available scores.

Current-commit verification rebuilds its evidence and score. Historical rating
inputs are locally stored sealed scores, not external attestations. Cross-project
ratings are not comparable. Commit/task splitting and selective capture remain
gaming risks; the ladder is a progress indicator, not a reward currency.

## Accounting remains separate

Unknown usage totals are null with known subtotals. Estimates retain their basis. Text estimates aggregate UTF-8 bytes before rounding by four, avoiding stream-chunk inflation. Reference prices are frozen per event, use explicit decimal precision, and separate estimated from provider-reported usage. Cached input and reasoning are subsets, not extra parent-bucket tokens. Price is money, not measured intelligence or physical computation.

The raw summary's legacy overall_score and efficiency fields remain null for compatibility. The implemented score is at `proof.score.value`. Ranking eligibility remains false because this is not a controlled benchmark.

## Limitations

Local operators can omit events or fabricate a history. Selective missingness can move a poor score toward neutral; hashes cannot prevent that. Splitting tasks or commits, padding files, choosing price snapshots, or missing rapid writes can change scores without improving work. More observations can move scores away from the prior at an unchanged ratio. No local score makes gaming impossible.

Competitive ranking or payment requires fixed tasks, starting states, acceptance tests, capture capabilities, prices, and external attestations. This release does not claim those. Future scoring changes must use a new algorithm ID and preserve old sealed scores.

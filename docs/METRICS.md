# Scoring specification: retention-v2

AI-PoW records a **proof vector** — human input, AI visible output, machine work, agent
architecture, artifact work and task work — and derives one **process score** from part of
it. The vector is the primary record; the score is a policy on top of it.

The score expresses a single preference: **more of the observed work survived into the
commit**. It does not measure correctness, developer ability, or commercial value.

Missing evidence is never treated as perfect, and small samples stay near 50. More tools,
Skills, sub-agents, tokens, or edits do not earn points.

## What is deliberately not scored

Machine cost, token volume, tool-call count and visible output length are recorded as
facts and carry **no weight in the score**. Calling one of them "efficient" requires a
comparable result, and this recorder cannot observe results: it sees the process, not
whether the software works. A resource term would also reward doing less AI work, which
inverts what a proof of work is for.

`Project = (Result, PoW)`. Result — tests, review, performance, users — stays a separate
axis that this tool does not claim to measure.

## Weights and direction

| Dimension | Weight | Higher when |
| --- | ---: | --- |
| Input retention | 40% | More edits linked to human messages survive |
| Artifact survival | 40% | More observed structural/content operations survive |
| Task fulfillment | 20% | More declared attempts finish with committed evidence |

These are explicit policy choices, not empirically established universal weights.

**Weight ceding.** A dimension with no evidence at all does not keep its weight at a
neutral value — that would pull every sparse commit toward 50 regardless of what was
observed. Its weight is redistributed proportionally across the dimensions that do have
evidence, and the score states which dimensions it was computed from:

```text
effective_weight[i] = weight[i] / sum(weight[j] for observed j)
```

Ceding changes which evidence the score is based on; it never invents evidence. Sparse
evidence still produces low confidence, which independently keeps the score near 50.

## Evidence definitions

**Artifact operations.** Python files use top-level AST fingerprints. Other UTF-8 files use groups of eight nonempty, stripped lines. Binary files use 4 KiB blocks. Each sampled file retains at most 64 unique fingerprints. These are structural/content proxies, not interchangeable semantic work units. Modification counts as removal plus addition. Identical units are deduplicated, so reformatting and moving code within a file produce no operations.

The first observed before-state is compared with the actual committed after-state. Only observed operations in that final difference survive. A full revert retains zero operations; deletion of existing code can survive. Latest lineage prevents repeated additions from counting as multiple surviving additions. Renames currently appear as deletion plus addition.

**Input retention.** A file event belongs to its explicit prompt_id, if supplied, or the most recent human message. Each linked prompt's retained/raw operation fraction is token-weighted (minimum weight one). This is a temporal attribution proxy, **not semantic information survival**. Unlinked prompts reduce confidence. Concurrent work can make attribution wrong, and a long prompt carries more weight than a short one.

**Task fulfillment.** Stable task IDs carry active, completed, or dropped statuses. Reopening a completed/dropped task starts another attempt. Completion counts only with a nonempty evidence list whose paths contain inspectable, nonempty committed units. Existence is not an acceptance test. Task granularity and completion are local claims. Adapters that never report tasks leave this dimension unscored, and its weight cedes to the others. Pure-deletion tasks need another evidence artifact, such as a committed test, in this version.

**Scope.** Final structural/content units in changed files, or retained operations if larger. This is size, not complexity. Cohorts: small <8, medium <32, large <128, extensive otherwise. Cross-language and cross-project rankings are unsupported.

## Smoothing and confidence

For retained count k out of n observations:

```text
raw ratio  = k / n                    # null when n = 0
quality    = (k + 2) / (n + 4)        # Beta(2,2) smoothing
confidence = n / (n + 4) * reliability
```

Input confidence uses linked prompt count, not token mass; effective k is its token-weighted ratio times that count. Input reliability is 0.7 times linked/all prompts. Artifact reliability is checked/observed operations, multiplied by 0.8 when capture limits apply. Task reliability is one for the declared evidence basis, not objective task truth. Every explicit coverage gap divides all component confidences by 1 + gap_count.

```text
L     = 0.5 + sum(effective_weight * confidence * (quality - 0.5))
score = 100 / (1 + exp(-5 * (L - 0.5)))
```

The result is rounded to one decimal. The theoretical outer envelope is approximately 7.6–92.4; conservative attribution narrows practical reach. Zero and 100 are not intended milestones. Missing evidence starts at 50, meaning **uncertain**, not average-quality code. Reported confidence uses the same effective weights as the score; below 65% the score is labeled provisional. Confidence is a policy-based indicator, not a calibrated probability.

Grades: S ≥ 90, A ≥ 80, B ≥ 65, C ≥ 50, D ≥ 35, E below 35. These are descriptive bands, not population percentiles.

## Reproducible examples

Run `python scripts/build_demo.py`. Explicitly synthetic fixtures use the production algorithm:

| Retention input | Observed operations | Score | Grade |
| ---: | ---: | ---: | --- |
| 40% | 240 | 40.6 | D |
| 54% | 190 | 53.7 | C |
| 62% | 150 | 60.2 | C |
| 76% | 96 | 70.9 | B |
| 85% | 130 | 77.0 | B |
| 89% | 44 | 76.7 | B |
| 98% | 175 | 85.6 | A |

Reference cost varies across these fixtures and does not move the score. The 89%/44-operation row scores below the 85%/130-operation row: less evidence means less confidence, which keeps the result closer to 50. Deleting a faulty feature may lower retention while improving the software: never keep faulty code to protect a score.

## Repository totals

Iteration reports show two repository-level numbers, and they answer different questions.

**Cumulative project score (commit-sum-v1)** starts at **0** and adds each recorded commit
score exactly once, unchanged:

```text
total[0] = 0
total[n] = total[n-1] + recorded_commit_score[n]
```

Example: 81.4 + 43.6 + 50.0 = 175.0. There is no code-line calculation, confidence or scope
weighting, eligibility threshold, deduction, tier, or upper limit. All weighting belongs to
the per-commit score. The full locally available first-parent history is replayed; only the
latest 30 historical rows are displayed. Missing scores contribute nothing. Scores from
earlier algorithms are added as recorded, not recomputed. Because every commit contributes
its own score, this total grows with the number of recorded commits.

**Pooled lifetime totals** aggregate the raw quantities instead: human tokens, visible
tokens, model calls and tokens, reference cost, tool calls, sub-agents, and artifact and
task operations. Ratios are recomputed from the pooled numerators and denominators:

```text
artifact_survival = sum(retained) / sum(operations)
```

never an average of per-commit percentages, which would give a one-line commit the same
weight as a large one. Unknown values stay unknown and are never counted as zero; the
totals report how many commits were recorded and how many carried a sealed score.

Both are derived report data, not values sealed into the latest proof. Restoring missing
proofs or changing the Git lineage changes what can be summed.

## History and verification

Iteration reports include up to 30 previous first-parent commits. Averages exclude this commit, unscored commits, and other algorithms. Same-scope averages additionally match the scope cohort. Local percentile requires at least three matching prior commits and uses midpoint ranks for ties. It is not a global ranking.

Proofs include the algorithm, score, components, and evidence in their hash. Verification rebuilds measurements from the trace, evidence against Git blobs, and the score **under the algorithm the proof recorded** — an installed newer algorithm never reinterprets an older proof, and an unknown algorithm fails. It does not trust a supplied evidence subtotal. Scoring analyzes up to 4,096 relevant events and 128 bounded committed blobs; limits are explicit. The complete trace is still verified.

Application 0.4 retains protocol 0.1. Proofs sealed with `balanced-v1` (which included a 30% resource-discipline term) keep verifying with that algorithm and are not rewritten. Accounting reducers `observed-v1` and `observed-v2` remain available for older proofs; new proofs use `observed-v3`, which adds the agent-architecture block.

## Accounting remains separate

Unknown usage totals are null with known subtotals. Estimates retain their basis. Text estimates aggregate UTF-8 bytes before rounding by four, avoiding stream-chunk inflation. Reference prices are frozen per event, use explicit decimal precision, and separate estimated from provider-reported usage. Cached input and reasoning are subsets, not extra parent-bucket tokens. Price is money, not measured intelligence or physical computation.

The agent block records observed spawns, parent links where the adapter reports them, maximum observed depth, and per-tool call counts, bounded to 128 agents and 32 tool names. Adapters that do not report parent links produce a flat structure; that is a capture limit, not a claim about the run.

The raw summary's legacy overall_score and efficiency fields remain null for compatibility. The implemented score is at `proof.score.value`. Ranking eligibility remains false because this is not a controlled benchmark.

## Limitations

Local operators can omit events or fabricate a history. Selective missingness can move a poor score toward neutral; hashes cannot prevent that. Weight ceding means a commit scored on one dimension is easier to move than one scored on three — the report names the scored dimensions for that reason. Splitting tasks or commits, padding files, or missing rapid writes can change scores without improving work; the cumulative total in particular rises with commit count. No local score makes gaming impossible.

Competitive ranking or payment requires fixed tasks, starting states, acceptance tests, capture capabilities, prices, and external attestations. This release does not claim those. Future scoring changes must use a new algorithm ID and preserve old sealed scores.

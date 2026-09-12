# Changelog

## 0.5.0

- Record and show the facts a process record needs and the report was dropping: elapsed interval between the first and last recorded event, sessions and wrapped runs, non-zero exits, failed tool results, coverage gaps, cache-read tokens, and what was actually paid next to the reference price (summary reducer observed-v4).
- Show the commit's own Git diff (files, insertions, deletions) in the latest-commit header.
- Draw the agent structure as a real tree with branch connectors instead of a flat indented list.
- Restore the bolder report styling - angular tabs, display type, the cream score panel and the orange total card - on top of the separated views.
- Generate the demo from this repository's own commits and diff sizes instead of a fictional project.
- Fix a stylesheet precedence bug that shrank the project total and its equation to body text.

## 0.4.1

- Rebuild the report around one headline per view: the latest-commit view shows the 0-100 commit score, the iteration view shows the cumulative project total, and neither shows the other.
- Calmer layout: a single accent, restrained type, clearer section titles, and labels that state what each number is and is not.
- Fix a fragment/id collision that scrolled the page past its own header on load.
- Draw the cumulative chart at pixel size so axis labels stay legible on narrow screens, and keep each commit's contribution visible there.
- Show one decimal on every score that feeds the sum, so the reported arithmetic matches the displayed numbers.

## 0.4.0

- Make the proof vector the body of the report: human input, AI visible output, machine work, agent architecture, artifact work and task work, each with its own recorded quantities.
- Replace balanced-v1 with retention-v2: retention only, at the original 40:40:20 weights. Resource use is recorded as fact and no longer scored, because efficiency needs a comparable result that the recorder cannot observe.
- Cede the weight of a dimension without evidence to the observed dimensions, and report which dimensions a score was computed from.
- Verify every proof under the algorithms it recorded; balanced-v1 and observed-v2 proofs keep verifying unchanged, and an unknown algorithm fails instead of being reinterpreted.
- Add summary reducer observed-v3 with an observed agent structure: spawns, reported parent links, depth, and per-tool call counts, bounded to 128 agents and 32 tool names.
- Add pooled repository totals whose ratios are recomputed from pooled quantities instead of averaging per-commit percentages; unknown values stay unknown.
- Stop reporting a parent agent link the Claude adapter never received.
- Use the masthead mark as the report favicon.

## 0.3.0

- Replace project-rating updates with commit-sum-v1: start at zero and add each recorded commit score exactly once.
- Remove cumulative-score tiers, confidence weighting, deductions, target convergence, and growth limits. Single-commit scoring remains unchanged.
- Redesign reports with dark slate surfaces, orange/white contrast, angular controls, and compact typography.
- Show the exact previous-total + commit-score = new-total calculation in iteration reports.
- Refresh English documentation, interactive demos, and browser checks.
- Retry transient event-writer lock contention with a stable event ID and a bounded retry count.

## 0.2.0

- Introduce balanced-v1, a smooth four-component process score with explicit confidence and neutral missing evidence.
- Add bounded AST/content fingerprints and committed-tree retention checks, including deletion and revert handling.
- Rebuild score evidence during verification instead of trusting supplied subtotals.
- Add explicit task attempts and committed evidence paths.
- Generate designed, self-contained offline HTML reports after commit sealing.
- Support iteration-history and latest-only modes, responsive layouts, filtering, historical inspection, and print/PDF.
- Add ladder-v1: a project-local cumulative rating starting at 1,000, bounded updates, diminishing gains, and Bronze-to-Diamond tiers.
- Replay full available first-parent score history for the ladder while showing at most 30 historical rows.
- Keep old protocol/accounting proofs verifiable and raw measurements separate from scoring policy.
- Bound scoring inputs and HTML cache storage; package all modules for standalone and embedded use.
- Add an English interactive demo, scoring specification, browser checks, and calibration fixtures.

## 0.1.0

- Initial local recorder, hash-chained events, Git-bound proofs, streaming export/verification, bounded storage, and agent adapters.
- Explicit observed-v2 accounting with legacy observed-v1 compatibility.

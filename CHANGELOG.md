# Changelog

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

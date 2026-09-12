# Contributing

Thank you for helping make AI-assisted work easier to inspect.

## Development setup

Python 3.10+ and Git are sufficient to run the tests:

```bash
git clone https://github.com/lin7c/ai-pow.git
cd ai-pow
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

To test the installed command, create a virtual environment and run `python -m pip install -e .`.

## Changes that need particular care

- Preserve event and proof compatibility, or define an explicit migration/version boundary.
- Keep unknown measurements distinct from zero and estimates distinct from provider-reported values.
- Describe adapter coverage and failure behavior. Do not infer hidden reasoning or usage from terminal output.
- Add meaningful tests for concurrency, resource bounds, or integrity changes.
- For metric changes, include counterexamples showing why the new interpretation is preferable.
- Keep user-facing documentation, code comments, issue reports, and pull request descriptions in English.
- Never include real transcripts, API keys, private source code, or customer proofs in fixtures.
- Own and clean up temporary files, processes, and repositories created by tests.

The standalone project must not depend on laintas-cli. Its core is vendored there separately; when both checkouts are present, the integration suite can check byte-for-byte consistency.

Open an issue for major protocol proposals before implementing them. Small fixes can go directly to a pull request with a concise problem statement, resulting behavior, and test evidence.

Contributions are provided under the repository's [MIT license](LICENSE).

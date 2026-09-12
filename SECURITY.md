# Security policy

AI-PoW is an experimental local recorder. It is not a trusted-execution environment or a tamper-proof audit service.

Application 0.2 HTML reports embed commit subjects, dates, resource metadata, and scoring evidence. Iteration reports additionally embed up to 30 previous commit summaries; switching to latest mode only hides that data. Export with `--view latest` to omit history entirely. Reports escape embedded data, use a script-hash Content Security Policy, and fetch no external resources. Review explicit exports before publishing them. Local consistency and a high process score do not imply secure or correct software.

## Trust model

- A local operator can change the code, remove events, and construct another internally consistent proof.
- Local timestamps and provider-reported usage are not externally authenticated.
- Hooks, sampling, transcript parsing, and process failures can leave gaps.
- Git object verification checks integrity, not the safety or quality of the code in those objects.
- Generic event payloads are caller-controlled and may contain sensitive information.

Built-in adapters omit raw prompt, source, tool, and reasoning content, but hashes and metadata can still disclose information. Review an exported bundle before publishing it. Do not assume a hash anonymizes a short prompt or known path.

Storage uses restrictive POSIX permissions and bounded inputs. The database quota does not include the rollback journal or exported bundles. These safeguards are not a substitute for OS isolation when recording untrusted workloads.

## Reporting a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/lin7c/ai-pow/security/advisories/new) for issues involving confidential details. If private reporting is unavailable, open a minimal public issue requesting a private contact, without including exploit details or secrets.

Include the version, platform, reproduction steps using synthetic data, expected behavior, and observed impact. There is no guaranteed response SLA.

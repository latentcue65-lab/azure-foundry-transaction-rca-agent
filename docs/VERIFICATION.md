# Verification record

The local implementation was verified on Windows with Python 3.12.10 using the dependencies pinned in `uv.lock`.

| Check | Result |
|---|---|
| Automated tests | 40 passed: source/agent/API contracts plus history and evaluation checks |
| Local scenario evaluation | 8/8 cases passed in explicitly labelled replay mode |
| Browser smoke test | Passed in installed Microsoft Edge |
| Browser scenarios | Identified RCA, recovery, uncertainty, customer-only discovery/selection, rejected foreign transaction and history |
| Browser output | Clickable evidence, trace correlation, six-field JSON, print/PDF, tool activity and responsive mobile layout verified |
| JavaScript errors during browser smoke | None |
| Foundry SDK contract | Installed SDK serializes registered agent/version and function-call outputs correctly against a mocked HTTP transport |
| Live Azure Foundry evaluation | 8/8 saved live runs passed the final rubric with `sphere-transaction-rca` version 3 and deployed `gpt-5-mini` |
| Live Foundry evidence coverage | Passed: agent called the file, HTTP API and direct SQLite tools before returning a schema-valid RCA |
| Live browser end-to-end test | Passed: browser → API → registered Foundry agent → three source tools → report/audit, including mobile and JSON/PDF exports |
| Distribution build | Source distribution and wheel built successfully; submission ZIP uses an explicit allowlist |

Replay evaluation uses real local file reads, direct read-only SQLite queries and real loopback HTTP requests. Its reasoning is a deterministic test double; these results are not an LLM accuracy measurement. SDK transport tests verify client request/response handling, not acceptance by a live Azure service.

The test suite reported one third-party deprecation warning from Starlette's test client regarding an AnyIO alias; it did not affect test outcomes. No application test failed.

Reproduce the automated checks with `uv run pytest` and `uv run python scripts/evaluate.py --mode replay`. With the app running in replay mode, reproduce browser checks with `uv run --with playwright python scripts/browser_smoke.py` on a machine with Microsoft Edge installed. Screenshots and downloaded output are saved under ignored `outputs/browser/`.

The [live evaluation summary](examples/evaluation-foundry-summary.json) records statuses, checks, agent versions and timings. The eight `examples/rca-foundry-TX*.json` files contain actual six-field LLM reports over synthetic data. Full run IDs, conversations, usage and snapshots remain in ignored `outputs/`.

Version 1 initially classified a generic timeout as an identified cause. Version 2 clarified that observed timeout propagation and complete retrieval do not establish the underlying cause. Reviewing its reports also found speculation about a replication race in the conflict scenario. Version 3 requires insufficient evidence when nothing explains contradictory terminal records. All eight scenarios were run again through version 3. The recovery phrase check was corrected to recognize both “A retry (PA2) completed successfully” and “allowing the checkout to recover”; it additionally requires citations to the failed and successful attempt outcomes. Saved version-3 audits were re-scored without changing their reports or repeating model calls; `rescoredSavedAudits` records this explicitly. These are eight case checks, not a claim of general or production RCA accuracy.

The source ZIP was extracted into a separate directory and its pinned dependencies installed. Fixture generation and the eight replay scenarios were checked from that directory. The project uses uv copy mode after the Windows/OneDrive filesystem rejected hardlinks during the initial clean installation.

Reproduce the real browser test with `uv run --with playwright python scripts/browser_smoke.py --mode foundry` against the Foundry server on port 8000. The replay browser supports `--base-url http://127.0.0.1:8001` when both modes are running. Browser artifacts are under `outputs/browser/foundry/` and `outputs/browser/replay/`. Run `uv run python scripts/evaluate.py --mode foundry` for fresh cloud calls, or add `--rescore` to recheck saved run artifacts.

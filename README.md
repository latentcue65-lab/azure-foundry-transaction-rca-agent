# Azure Foundry Transaction RCA Agent

**Start here:** Follow the [end-to-end demo runbook](docs/DEMO_RUNBOOK.md). Use the offline setup below for a credential-free integration demonstration, or configure [Azure Foundry](docs/AZURE_SETUP.md) for real LLM execution. See [verification results](docs/VERIFICATION.md) for measured checks.

The browser includes customer-only transaction discovery, saved investigation history, trace/attempt correlation, clickable evidence, JSON download and print/PDF export. Each report displays its own execution mode and outcome. `GET /api/investigations?customerId=C1001&limit=20` lists recent report summaries for the local user; this filter is not a replacement for authenticated authorization in a shared deployment.

A working Python assessment POC that investigates customer transactions using JSONL files, a real HTTP mock API, and direct read-only SQLite queries. A named Microsoft Foundry agent chooses tools and produces an evidence-grounded six-field RCA. The local application validates scope, correlations and evidence references, and records the investigation audit.

**Two explicit modes:** `foundry` uses a registered Azure agent and a real LLM. `replay` is a deterministic integration-test double that exercises the same real source adapters without an LLM. Replay never substitutes for a failed Foundry call. Live Azure acceptance requires a configured project, model deployment and authenticated access.

**Run the local demonstration.** From this directory in PowerShell, with Python 3.12+ and [uv](https://docs.astral.sh/uv/) installed:

```powershell
git clone https://github.com/latentcue65-lab/azure-foundry-transaction-rca-agent.git
cd azure-foundry-transaction-rca-agent
uv sync --frozen
uv run rca seed
uv run rca serve --mode replay --with-mock
```

Open **http://127.0.0.1:8000**. The UI displays the runtime mode, findings, failure flow, evidence, coverage and tool calls. `--with-mock` starts a real HTTP service on an available loopback port and shuts it down with the application. If data already exists, skip `seed`; `uv run rca seed --reset` explicitly replaces only generated demo fixtures.

Alternatively run `./scripts/Start-Demo.ps1`. To run one investigation without a browser:

```powershell
uv run rca demo --transaction TX9001
uv run rca demo --transaction TX9005
```

These commands explicitly default to replay. JSON goes to stdout; the runtime mode and audit-file location go to stderr. A provider, validation or budget failure returns a nonzero CLI exit code. Findings such as insufficient evidence can be legitimate completed investigations.

**Run with Azure Foundry.** Follow [AZURE_SETUP.md](docs/AZURE_SETUP.md). Copy `.env.example` to `.env`, configure the project endpoint and deployment name, and authenticate through Azure CLI or a supported Entra credential. Then:

```powershell
uv run rca doctor --live
uv run rca register
uv run rca demo --mode foundry --transaction TX9001
uv run rca serve --mode foundry --with-mock
```

`register` creates a versioned prompt agent with four read-only function definitions and a strict final JSON schema. Its name/version and definition hash are saved in ignored `.foundry-agent.json`. The application uses the registered version through the Foundry Responses/Conversations APIs and executes requested tools locally. New model, prompt or tool definitions require registering a new version. Cloud conversations remain available for interview inspection; credentials and generated run artifacts are excluded from the source bundle.

**Use Mocki or another HTTP mock.** The bundled mock is a runnable alternative permitted by the assessment. For a hosted Mocki endpoint, paste the generated `data/api-events.json` payload into the service and put its actual HTTPS URL in `RCA_MOCK_API_URL`. The adapter accepts either an `events` array inside an object or a top-level array. Do not put real customer information in a public mock.

Start the application **without** `--with-mock` to use the configured remote endpoint:

```powershell
uv run rca serve --mode foundry
```

For two independent local processes, start `uv run rca mock-api --port 8091` in one terminal and `uv run rca serve --mode replay` in another. The default configured HTTP URL is `http://127.0.0.1:8091/events`. Query parameters `?fault=unavailable` and `?fault=malformed` on the bundled mock demonstrate retrieval failures. The adapter records the failure; it does not silently switch sources. `rca demo` intentionally starts its own local mock; use `rca analyze --input docs/examples/request.json` to test the configured remote source.

**API contract.** `POST /api/analyze` accepts:

```json
{
  "customerId": "C1001",
  "transactionId": "TX9001",
  "fromTime": "2026-09-14T09:55:00Z",
  "toTime": "2026-09-14T10:05:00Z",
  "issueDescription": "Investigate this transaction and explain its outcome."
}
```

The response has exactly `customerId`, `transactionId`, `rootCause`, `failureFlow`, `evidence`, and `recommendation`. See the [application schema](docs/contracts/rca-output.schema.json). The `X-Investigation-Id`, `X-RCA-Mode`, and `X-RCA-Outcome` headers identify the run and its execution status. Fetch `/api/investigations/{id}` for the audit and normalized evidence snapshot. `/docs` provides interactive API documentation; `/health` reports local configuration, not proof of cloud connectivity.

Omit `transactionId` to discover candidates in the requested window. Multiple candidates return HTTP 409; missing/unauthorized customer-transaction combinations return 404 without revealing another customer's data. Timestamps require timezones, and the requested window is limited to 24 hours. This small POC discovers transactions by their creation time within that window; use a window including transaction creation. Input errors return 422, and missing Foundry setup returns 503.

**Included scenarios.** All data is synthetic and reproducibly generated. The dated demo window is explicit so results do not depend on today's date.

| Transaction | Scenario | Expected replay finding |
|---|---|---|
| TX9001 | Historical wallet decline | Identified cause; INR 50 available against INR 125 requested |
| TX9002 | Connection acquisition failure | Identified pool exhaustion; reason for occupied connections remains unknown |
| TX9003 | Upstream timeout without provider details | Insufficient evidence for the underlying cause |
| TX9004 | Successful checkout | No failure, with positive success evidence |
| TX9005 | Timeout then successful retry with another trace | Qualified historical finding and explicit recovery |
| TX9006 | No observations | Insufficient evidence |
| TX9007 | Contradictory terminal records for the same attempt | Conflict disclosed; insufficient evidence |
| TX9008 | Instructions embedded in a log | Log is treated as data; tools cannot read arbitrary files or customers |

TX9999 belongs to C2001 and serves as a scope-isolation distractor. Expected findings are evaluation criteria; they are not supplied to the Foundry agent as answers. The original `docs/examples/rca-identified.json` is an illustrative architecture example, not a live run. Actual reports and audits are written to `outputs/` with their real mode labels.

**Code walkthrough.** Follow these modules in order during the interview:

| Module | Responsibility |
|---|---|
| `models.py`, `config.py` | Typed request, event, report, settings and bounds |
| `sources.py` | Parameterized scope resolution, actual SQL/file/HTTP retrieval and filtering |
| `tools.py` | Tool schemas, allowlisted dispatch, cursor coverage and argument enforcement |
| `evidence.py` | Deduplication, immutable snapshots, explicit causal references and attempt groups |
| `foundry.py`, `prompts/investigator.txt` | Registered agent definition, Entra authentication and Responses calls |
| `engine.py` | Bounded tool loop, report repair, error handling and audit persistence |
| `validation.py` | Six-field schema, scope, evidence fidelity and consistency checks |
| `backends.py` | Explicit replay test double for offline integration testing |
| `api.py`, `static/index.html`, `cli.py` | HTTP API, interview UI and commands |
| `seed.py`, `mock_api.py` | Synthetic fixtures and separately runnable HTTP mock |

The LLM chooses follow-up queries and interprets correlated evidence. Python enforces exact trace/attempt mappings and creates causal edges only when a source record explicitly references a predecessor. Timestamp ordering alone is not considered proof. The implementation uses a general historical `events` table with structured audit attributes; a separate wallet audit table is unnecessary for this POC.

**Validation.** Run:

```powershell
uv run ruff check
uv run ruff format --check
uv run pytest
uv run python scripts/evaluate.py --mode replay
```

Tests exercise real loopback HTTP, direct SQLite, file reads, pagination, scope isolation, missing/malformed sources, retries, conflicting outcomes, fabricated citations, prompt-injection tool attempts, schema repair and budgets. An installed-SDK test verifies actual Foundry request serialization using a mocked HTTP transport; it does not claim Azure service acceptance. `scripts/evaluate.py --mode foundry` runs the same scenarios through the live configured agent and saves a mode-labelled evaluation. Review causal correctness and recommendations as well as automated status/reference checks.

**Practical limits.** This is a single-user local POC, bound to `127.0.0.1`. Add authenticated authorization and per-user audit access before shared hosting. It deliberately uses bounded reads (2 MB per source, 8 KB per event, configurable pagination and event limits), in-process execution, and local audit files. Source limits produce incomplete coverage. Textual causal correctness still needs a case-based evaluation; a valid citation alone cannot prove a natural-language claim. Full managed hosting is a separate deployment mode; the implemented Azure baseline is a registered agent with local tool execution.

The detailed design is in [ARCHITECTURE.md](ARCHITECTURE.md). [INTERVIEW_GUIDE.md](docs/INTERVIEW_GUIDE.md) provides a short explanation and demo sequence.

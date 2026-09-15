# Azure Foundry Transaction RCA Agent

An AI agent that investigates customer transactions across file logs, an HTTP API and a local SQLite database, then returns an evidence-backed root cause analysis.

The registered Azure Foundry agent chooses read-only tools and analyzes their results. Python executes the tools, enforces customer scope, correlates trace/attempt IDs and validates the final report. The agent and LLM run in Azure; the UI and data tools run locally.

## Assignment coverage

| Requirement | Implementation |
|---|---|
| Accept customer details | Customer ID, optional transaction ID, time window and issue description |
| Retrieve file logs | JSONL reader with file and line references |
| Integrate a mock API | Real HTTP calls to a bundled mock server; supports a configured Mocki-compatible URL |
| Connect directly to a lightweight database | Read-only SQLite connection with parameterized queries |
| Correlate and analyze failures | Foundry LLM with exact trace/attempt mappings, failure flow and evidence citations |
| Required output | `customerId`, `transactionId`, `rootCause`, `failureFlow`, `evidence`, `recommendation` |

## Run the application

Prerequisites: Git, Python 3.12+ and [uv](https://docs.astral.sh/uv/). Commands below use PowerShell.

```powershell
git clone https://github.com/latentcue65-lab/azure-foundry-transaction-rca-agent.git
cd azure-foundry-transaction-rca-agent
uv sync --frozen
uv run rca seed
```

### Azure Foundry — real LLM

Use an existing Foundry project with a deployed model supporting function calling and structured output. Copy `.env.example` to `.env` and set `FOUNDRY_PROJECT_ENDPOINT` and `FOUNDRY_MODEL_NAME` to your project endpoint and deployment name. Authenticate with [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-windows):

```powershell
az login
uv run rca doctor --live
uv run rca register
uv run rca serve --mode foundry --with-mock
```

Credentials are not included. See [Azure setup](docs/AZURE_SETUP.md) for configuration and troubleshooting.

### Offline verification — no Azure credentials

```powershell
uv run rca serve --mode replay --with-mock
```

Replay uses deterministic reasoning, **not an LLM**. It exercises the same real file, HTTP and SQLite integrations. `--with-mock` starts the bundled HTTP server in either mode.

## What to check

Open **http://127.0.0.1:8000**. Use customer `C1001` and keep the prefilled historical time window.

| Transaction | Demonstrates |
|---|---|
| `TX9001` | Wallet decline: INR 50 available against INR 125 requested |
| `TX9005` | Failed attempt followed by a successful retry with a different trace ID |
| `TX9003` | Upstream timeout with an unknown underlying cause |
| `TX9007` | Conflicting records reported as insufficient evidence |

Check the execution mode, root cause, failure flow, clickable evidence, source coverage and tool calls. Download the six-field JSON or reopen a saved investigation. All demo data is synthetic.

For API testing, open **http://127.0.0.1:8000/docs** and submit the [sample request](docs/examples/request.json) to `POST /api/analyze`. Review an [actual Foundry response](docs/examples/rca-foundry-TX9001.json) and the [output schema](docs/contracts/rca-output.schema.json).

## Verification

Recorded results: **40 automated tests passed**, **8/8 live Foundry scenario checks passed**, and browser tests covered the real LLM flow, evidence navigation and exports. The live evaluation used `gpt-5-mini`; these checks are not a general RCA accuracy score. See the [evaluation summary](docs/examples/evaluation-foundry-summary.json) and [verification record](docs/VERIFICATION.md).

```powershell
uv run pytest
uv run python scripts/evaluate.py --mode replay
# With Azure configured; invokes the deployed model:
uv run python scripts/evaluate.py --mode foundry
```

## Code and design

Start with [engine.py](src/rca_agent/engine.py) for the investigation loop, [foundry.py](src/rca_agent/foundry.py) for the registered agent, [sources.py](src/rca_agent/sources.py) for retrieval and [validation.py](src/rca_agent/validation.py) for report checks. See [Architecture](ARCHITECTURE.md) and the [demo runbook](docs/DEMO_RUNBOOK.md) for the full walkthrough.

Scope: a local, single-user assessment POC. Shared hosting requires authentication and per-user authorization; recommendations do not execute remediation.

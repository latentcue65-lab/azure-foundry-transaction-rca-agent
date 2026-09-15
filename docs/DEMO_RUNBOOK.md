# End-to-end interview demo

## Run with a configured Foundry project

```powershell
./scripts/Start-Demo.ps1 -Mode foundry
```

Open **http://127.0.0.1:8000**. If it is already running in Foundry mode, use that instance. The launcher installs pinned dependencies, generates missing synthetic fixtures and starts the app and real HTTP mock. Stop a foreground instance with Ctrl+C. Existing data and configuration are preserved.

The badge must say **Foundry agent · live LLM mode**. Saved replay reports remain labelled replay when reopened on a Foundry server.

## Ten-minute demonstration

1. Show the requirement mapping in [ARCHITECTURE.md](../ARCHITECTURE.md): three source adapters and six-field response.
2. Submit TX9001 / C1001 with the seeded September 14, 2026 time window. Historical logs intentionally do not depend on today's date.
3. Read root cause, flow and limitations. Click a citation to open its source excerpt. The wallet decision records INR 50 available versus INR 125 requested.
4. Expand tool activity: show file, API and database calls, completed execution and Foundry conversation ID. The model chooses calls; Python constrains arguments.
5. Select TX9005. PA1 and PA2 have different mapped traces. Explain historical failure, successful retry and unknown original timeout cause.
6. Select TX9003 for uncertainty or TX9007 for contradictory records. Qualified findings are correct outcomes here.
7. Clear Transaction ID and submit. Choose a displayed customer transaction.
8. Reopen a recent investigation without another LLM call. Download six-field JSON or use Print / PDF.
9. Inspect `sphere-transaction-rca` in the Foundry project: registered version, instructions and four function definitions. The laptop executes custom functions; an isolated portal chat cannot open its SQLite file.
10. Show [VERIFICATION.md](VERIFICATION.md) and walk through the implementation modules.

## Independent API demonstration

```powershell
$rcaRequest = Get-Content -Raw docs/examples/request.json
$rcaResponse = Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:8000/api/analyze -Method Post -ContentType application/json -Body $rcaRequest
$rcaResponse.Content
$rcaResponse.Headers['X-Investigation-Id']
```

Open **http://127.0.0.1:8000/docs** for interactive API documentation. `X-RCA-Outcome` distinguishes completed analysis from execution failure; `rootCause.status` describes the business finding.

## Standalone mock integration

The standard demo uses real HTTP. For independent processes, use two terminals and available ports:

```powershell
# Terminal 1
uv run rca mock-api --port 8091
```

```powershell
# Terminal 2: uses RCA_MOCK_API_URL from .env
uv run rca serve --mode foundry --port 8002
```

The default URL is `http://127.0.0.1:8091/events`. A hosted Mocki-compatible endpoint can return generated `data/api-events.json`. Configure its URL and start without `--with-mock`. The bundled mock is the verified integration; a hosted Mocki account is optional.

## Clean setup for the reviewer

1. Extract the ZIP and open its folder.
2. Install Python 3.12+ and uv; run `uv sync --frozen` and `uv run rca seed`.
3. Run `./scripts/Start-Demo.ps1 -Mode replay` for offline integration checks.
4. For the real LLM, copy `.env.example` to `.env`, set the reviewer's endpoint/deployment and sign in with Azure CLI. Run `uv run rca doctor --live` and `uv run rca register`.
5. Launch with `-Mode foundry`; see [AZURE_SETUP.md](AZURE_SETUP.md).

The repository and submission ZIP exclude credentials, `.env`, agent registration metadata, generated databases and local logs. Seed regenerates synthetic data. Selected six-field synthetic live reports and summarized verification results are included as interview evidence.

The project sets uv's [link-mode](https://docs.astral.sh/uv/reference/settings/#link-mode) to `copy`: the fresh-install check on this Windows/OneDrive workspace encountered a hardlink compatibility error with the default installation mode.

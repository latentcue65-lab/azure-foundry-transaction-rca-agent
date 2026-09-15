# Azure Foundry setup and live verification

The implemented Azure mode uses a **named, versioned Foundry prompt agent and local Python tools**. Foundry hosts the agent/model; Python opens local SQLite and files and calls the mock API. No inbound tunnel to the laptop is required. A portal-only session does not execute the laptop's functions by itself. Microsoft's [function-calling documentation](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/function-calling) describes this execution boundary.

**Information required from the Azure account owner.** These values are not secrets:

1. The Foundry **project endpoint**, copied from the project overview, usually shaped like `https://<resource>.services.ai.azure.com/api/projects/<project>`.
2. The **deployment name** of a model available in that project that supports function calling and JSON Schema structured outputs. Supply the deployment name, not only a catalog model name.
3. Working **Microsoft Entra access** to that project, including permissions to create/read agent versions and invoke the deployment. The exact assignment depends on existing project configuration; use the current [Foundry role documentation](https://learn.microsoft.com/en-us/azure/ai-foundry/concepts/rbac-azure-ai-foundry).

If a project/deployment does not exist, the account owner also needs to identify the subscription, resource group and allowed region, with sufficient deployment permissions and available model quota. No Azure resources are provisioned by local replay or by `rca seed`. `rca register` creates an agent version in the configured existing project.

**Local authentication.** Install the [Azure CLI for Windows](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-windows) if `az` is unavailable. Sign in from your own terminal:

```powershell
az login
```

Choose the intended account/subscription if prompted. If browser sign-in is unavailable, use `az login --use-device-code`. Do not paste passwords, access tokens or client secrets into chat. The application uses `DefaultAzureCredential`; a properly configured service principal is another option, but an interactive Azure CLI login is simpler for the interview. The [Azure AI Projects SDK documentation](https://learn.microsoft.com/en-us/python/api/overview/azure/ai-projects-readme?view=azure-python) describes project authentication and endpoints.

**Project configuration.** From the repository root, copy `.env.example` to `.env` if `.env` does not already exist. Preserve existing values. Fill these entries:

```dotenv
RCA_MODE=foundry
FOUNDRY_PROJECT_ENDPOINT=https://YOUR-RESOURCE.services.ai.azure.com/api/projects/YOUR-PROJECT
FOUNDRY_MODEL_NAME=YOUR-DEPLOYMENT-NAME
FOUNDRY_AGENT_NAME=sphere-transaction-rca
```

Use the exact endpoint from the portal even if its hostname differs from the illustrative pattern. Keep `.env` and `.foundry-agent.json` local. `uv.lock` records the tested SDK versions, including `azure-ai-projects` 2.6.0. This code uses the current prompt-agent and Responses APIs, not classic Threads/Runs examples.

**Verify and register.** These commands are implemented:

```powershell
uv sync --frozen
uv run rca doctor
uv run rca doctor --live
uv run rca register
```

The offline doctor prints only configuration booleans. The live doctor authenticates and checks that the configured deployment is visible. Registration creates the prompt agent, read-only tool schemas and strict RCA output format. Its returned version is stored with a definition hash. It does not deploy a new model or start a cloud container.

**Complete the live assessment run.** If synthetic data has not been generated, run `uv run rca seed`. Then:

```powershell
uv run rca demo --mode foundry --transaction TX9001
uv run rca demo --mode foundry --transaction TX9005
uv run rca serve --mode foundry --with-mock
```

Open http://127.0.0.1:8000. Show the Foundry agent/version in the portal, submit a transaction from the local UI, and inspect its tool activity, response IDs, evidence and final six-field JSON. `demo` and `--with-mock` use a real locally hosted HTTP mock. To use a hosted Mocki URL instead, configure `RCA_MOCK_API_URL`, omit `--with-mock`, and use the UI or `rca analyze`.

For reproducible live evaluation, run `uv run python scripts/evaluate.py --mode foundry`. This invokes the configured deployment and consumes model quota; results are saved with the live mode and run IDs. A local replay or SDK transport test is never reported as a successful live LLM evaluation.

**Troubleshooting.** A missing endpoint/model means `.env` is incomplete. Authentication failures require checking the signed-in account and tenant. A 403 usually requires checking permissions at the appropriate resource/project scope. A missing deployment or unsupported structured-output configuration requires checking the deployment name and model capabilities. Rate/quota errors require checking deployment capacity. Review the local run outcome and source coverage as well as the Foundry response/conversation IDs; the app never replaces a failing model with replay.

**If full Foundry hosting is explicitly required.** This repository implements the registered-agent/local-tools mode used to reconcile the assessment's local DB requirement with an Azure agent demo. A fully hosted application additionally packages or relocates those tools and synthetic data. Follow the current [hosted-agent quickstart](https://learn.microsoft.com/en-us/azure/foundry/agents/quickstarts/quickstart-hosted-agent) for that separate deployment; cloud copies of SQLite/logs are not the laptop's files. Hosting is not represented as completed by this repository's registration command.

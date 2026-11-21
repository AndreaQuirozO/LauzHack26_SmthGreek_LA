# Enterprise migration assistant demo

A local hackathon prototype for source-grounded enterprise software migration assistance. It offers role-specific guides and follow-up answers, plus a separate administrator-approved update demonstration in a disposable Docker container. The built-in migration scenario demonstrates moving spreadsheet work from Microsoft Excel to LibreOffice Calc; the provider and grounding architecture support additional migration scenarios.

## Scope and safety

- Roles, tasks, and session data are fictional and temporary; a server restart clears in-memory state.
- Do not enter confidential company or employee information. Guide and chat prompts, the selected fictional role, and curated notes are sent to the configured model provider.
- Answers are grounded in the small source corpus and include links resolved by the server. The model may still make mistakes; verify important work against the linked official documentation.
- The `certifi` scenario is a fixed demonstration, not a reading of the host machine and not a claim that the baseline is vulnerable. It never updates the host or employee devices.
- This prototype has no live company integrations, document uploads, device management, production authentication, or multi-tenant support. Do not expose the server beyond loopback.
- Docker is an isolation aid for this demonstration, not a production security boundary or endpoint-management system.

## Requirements

- Python 3.11 or newer.
- Docker Desktop or another Docker installation is needed only to build and run the update demonstration.
- An API key and model identifier for an OpenAI-compatible provider are needed to generate guides and answers.

## Install and configure (PowerShell)

From the project directory, create an environment and install the app with its tests:

```powershell
python --version
python -m venv lauzhack.venv
.\lauzhack.venv\Scripts\python.exe -m pip install -e ".[test]"
```

### Persistent configuration (recommended)

Copy the example file and add your API key:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and replace `your-together-api-key` with your actual key. The file is ignored by git and persists across sessions. The app loads it automatically on startup. See `.env.example` for all available options.

### Together.AI

Configure Together.AI in the same PowerShell window:

```powershell
$env:TOGETHER_API_KEY = "your-together-api-key"
```

`TOGETHER_MODEL` is optional and defaults to `moonshotai/Kimi-K3.1-Pro`.
`TOGETHER_BASE_URL` is optional and defaults to `https://api.together.xyz/v1`.

### OpenAI-compatible provider

Alternatively, configure an OpenAI-compatible provider:

```powershell
$env:OPENAI_API_KEY = "your-model-provider-key"
$env:OPENAI_MODEL = "your-model-name"
$env:OPENAI_BASE_URL = "https://api.openai.com/v1"
```

The app requests JSON-formatted responses from a model that supports JSON mode, allows up to two minutes for a response, and reports a clear configuration or availability error if model settings are missing or the provider cannot be reached. The configured administrator secret is separate from the model key:

```powershell
$env:DEMO_ADMIN_SECRET = "choose-a-long-local-demo-secret"
```

Do not commit or share either secret. The admin secret is sent only in the approval request header and is not included in application logs or request bodies.

## Build and run

Build the fixed update image before trying the approval workflow. The build downloads only the pinned `certifi` wheels and verifies their SHA-256 hashes; the approved container execution itself uses no network.

```powershell
docker build --tag excel-calc-certifi-demo:2026.11.20 .\demo\update
```

If PowerShell reports `docker: The term 'docker' is not recognized`, Docker is not installed or is not on `PATH`.

1. Install Docker Desktop for Windows.
2. Start Docker Desktop and wait until it reports that the Docker Engine is running.
3. Open a new PowerShell window so the updated `PATH` is loaded.
4. Verify the installation:

```powershell
docker --version
docker run --rm hello-world
```

The demo update workflow can start even while Docker is unavailable, but approval will fail safely with an actionable Docker error.

Start the web app bound to IPv4 loopback:

```powershell
.\lauzhack.venv\Scripts\python.exe -m app.main
```

Open <http://127.0.0.1:8000>. The server rejects non-loopback hosts and cross-origin state-changing requests. Keep the terminal open while using the demo.

## Walkthrough

1. Select one of the fictional roles and start a temporary onboarding session.
2. Select a migration task and generate a source-grounded guide. Follow the links to verify product details.
3. Ask a task-related follow-up. If the curated notes do not support an answer, the assistant says so instead of inventing one.
4. Review the separate `certifi` proposal. It always describes the catalog's fixed baseline `2024.8.30` and target `2026.11.20`; it does not inspect the host.
5. An authorized demo administrator enters `DEMO_ADMIN_SECRET` and approves once. The server runs the prebuilt image with fixed arguments, no mounts, no network, a read-only root filesystem, a non-root UID, bounded temporary storage, resource limits, and a time limit.
6. The container installs the pinned baseline wheel, upgrades offline to the pinned target wheel, verifies the version, and is removed. The UI reports the verified version or a safe failure (for example, if Docker is unavailable).

Each session can create only one proposal, and a proposal is consumed before execution begins. Missing administrator configuration, a wrong secret, cross-session approval, replay, timeout, Docker failure, or a version mismatch fails closed. The demo secret is not a substitute for production authentication.

## Tests

Run the API, grounding, session, approval, and isolation-argument tests:

```powershell
.\lauzhack.venv\Scripts\python.exe -m pytest -q
```

The real Docker integration test is opt-in. It builds a uniquely tagged image, checks the approved offline update and container cleanup, then removes the image it built:

```powershell
$env:RUN_DOCKER_INTEGRATION = "1"
.\lauzhack.venv\Scripts\python.exe -m pytest tests\test_updates.py -k docker_update_integration -q
Remove-Item Env:\RUN_DOCKER_INTEGRATION
```

## Cleanup

- Stop the server with `Ctrl+C`; this clears all in-memory sessions and proposals.
- The update container uses Docker's `--rm` option and its temporary virtual environment is removed when execution completes.
- Remove the demo image when it is no longer needed: `docker image rm excel-calc-certifi-demo:2026.11.20`.
- Close the PowerShell window or remove its environment variables when finished.
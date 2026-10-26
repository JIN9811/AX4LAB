# API Key Setup

This repository must not store real API keys.

Use `.env.example` only as a tracked list of supported environment variable
names. Keep real values in `.env` or the local root `env` file, which are
ignored by Git.

## Local `.env`

Create a local `.env` from the example:

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Then set only the keys you actually use:

```text
AX4LAB_BACKEND=openai
OPENAI_API_KEY=<your-key-here>
OPENAI_BASE_URL=https://api.openai.com/v1
```

For a local backend that can also use the API, keep the local backend:

```text
AX4LAB_BACKEND=vllm
OPENAI_API_KEY=<your-key-here>
```

The Main GUI API-key state takes precedence over the static fallback order in
`configs/models.yaml`: loading a saved key makes OpenAI the first route; unloading
it disables API use and restores local inference. Switching to `openai` alone
does not re-enable a saved disabled key.

## Main GUI API Key Store

The Main GUI `Current Models` panel includes an `API Key` control. Use it when
this checkout does not have a local `.env` yet or when a new operator needs to
save the OpenAI key from the browser. Loading that key makes the API route
primary, as described below.

- `API Key` opens a small local input dialog.
- `Loading` enables the saved key and makes OpenAI API the first inference route.
- `Unloading` disables runtime API use, restores local inference as the first
  route, and keeps the saved key for later.
- Status refreshes only report and silently reapply the stored setting; they do
  not emit runtime load/unload events.
- Server startup also silently applies the saved setting before the first
  browser status request, so first-call inference uses the saved API route when
  it is loaded.
- If the API route fails or returns an empty response, the selected local endpoint
  is tried next, followed by its explicitly configured fallback endpoint, if any.
- The key is stored in `memory/api_keys.json`, which is ignored by Git.
- If `OPENAI_API_KEY` is already present in `.env` or the local root `env`
  file, the first GUI status load imports it into `memory/api_keys.json` and
  marks it enabled.
- API responses only return registration state such as `registered`; key
  characters are never sent back to the browser after saving.
- A previously saved disabled state is preserved during migration and restart.
  `registered` does not mean enabled, authenticated, or sufficient API quota.
- API-key loading updates only the OpenAI client. Local/custom inference servers
  retain their own credentials and never receive the saved cloud key.
- Modules inheriting the runtime route follow the same API-first order. Explicit
  module backend/model overrides remain authoritative.

## Connection editor and endpoint binding

`/llm-connections` reuses the Main GUI's model and key controls. In **API Connection**
or **Local LLM Connection**, **Add Endpoint** registers a stable endpoint ID,
display name, API base URL, manually entered served model ID, optional token,
text/vision capabilities and optional server-management target. Two registrations
may serve the same model ID without sharing their address, credential or lifecycle
identity. The GUI does not discover model names from a server.

GET `/api/runtime/llm-connections` returns public endpoint records, management
targets and role profiles. PUT on the same route assigns `orchestrator_endpoint`,
`worker_endpoint` and optional fallback endpoint IDs for the chosen provider.
PUT `/api/runtime/llm-connections/endpoints/{id}` saves an endpoint; DELETE on the
same path removes only its registration. Assigned endpoints require replacement
role and fallback assignments first. Neither operation deletes model files.
Saves require an idle runtime and update endpoint-backed routing without starting a run.
POST `/api/runtime/llm-connections/test` tests the selected `orchestrator` or `worker` role.
Probes reserve the existing LLM lease non-blockingly and call only the selected
endpoint/model, with a 60-second timeout and no inference fallback.

Endpoint registrations, role assignments and endpoint tokens are atomically stored
as `llm_connections.v2` in `memory/llm_connections.json` with mode `0600`.
Legacy settings are imported in memory; only an explicit save writes the new schema.
The startup hook restores settings before applying the private API-key settings.
Malformed saved settings leave deployment defaults active and report a load error;
missing or ambiguous endpoint references must not silently select another model.

The API-key store records its `base_url`. Changing the API connection disables
use of a key bound to another address. Key dialogs submit `expected_base_url`;
a concurrently changed endpoint returns HTTP 409 before storing the new key.
Neither key values nor endpoint tokens are returned by the settings APIs. A blank
token on Edit preserves the stored token only for the same provider and address;
changing either clears it unless a replacement token is explicitly supplied.
An API endpoint can use its own token; the global API key is a fallback only for
its matching bound address. API Loading/Unloading still controls whether API
endpoints may participate in normal inference, including those with their own tokens.
Connection tests are explicit, isolated requests, not a change to that routing gate.

A local endpoint's `management_id` refers to an operator-configured server target,
not its served model name. Main and Current Mode cards retain **Loading / Unloading**
for managed endpoints; the existing model lifecycle routes accept `endpoint_id`.
External endpoints without a management target show **Registered** and do not
provision a server. Start or stop those services on their own hosts. Request routing
uses `endpoint:<id>` internally and resolves the served model ID at the HTTP boundary.
Credential-bearing requests must not follow redirects to another endpoint;
probe responses redact stored tokens.

## Local-only key notes

If you want a written note of which key belongs to which machine or project,
create:

```text
docs/runtime/api_keys.local.md
```

That file is ignored by Git. Do not commit it.

## Supported Variables

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_ORG_ID`
- `OPENAI_PROJECT_ID`
- `TAVILY_API_KEY`
- `SERPER_API_KEY`

Device bridge credentials, PrusaLink credentials, tokens, and passwords should
also stay in ignored local files such as `.env`, `memory/*.json`, or bridge-local
configuration files.

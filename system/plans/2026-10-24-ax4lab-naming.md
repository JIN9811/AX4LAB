# AX4LAB Naming Implementation Plan

> **For agentic workers:** Use focused parallel tasks with test-first implementation.

**Goal:** Consistent AX4LAB terminology and an independent ax4lab CLI.

**Architecture:** Separate the public identity from stable serialized contracts.
Keep the structured runtime/system/docs layout and original installation intact.

**Tech Stack:** Bash, Python, Jinja/JavaScript, Markdown, pytest and Node tests.

**Spec:** ../specs/2026-10-24-ax4lab-naming.md

## Global constraints

- Desktop AX4LAB checkout only; no original checkout writes or global installation.
- Product `AX4LAB`, command/distribution `ax4lab`, default web port 7861.
- Keep schemas, module/graph IDs, device contracts and historical evidence intact.
- Documentation stays in English/Korean according to the existing page.

## Review focus

- Existing atr launcher survives installation byte-for-byte.
- Custom ports and .env values do not send CLI requests to a different server.
- Renaming does not disconnect modules or invalidate serialized records.
- Docs commands, package metadata, launcher help and UI agree.
- Historical links and immutable evidence retain their meaning.

## Task 1: Launcher isolation

Files: runtime/install shell scripts, runtime/scripts/doctor.py,
runtime/app/serve.py, runtime/configs/system.yaml, .env.example,
runtime/tests/unit/test_portable_bootstrap.py and related diagnostic tests.

- [x] Add behavioral failing tests for coexistence, defaults, custom ports and doctor.
- [x] Implement ax4lab launcher/install/diagnostics with checkout ownership guards.
- [x] Run isolated installer and configuration tests, record command/results.

## Task 2: Active documentation terminology

Files: README.md, docs, active runtime Markdown guides and installer README.

- [x] Inventory old product/command references; exclude serialized/historical IDs.
- [x] Update prose, install/start commands and default web URLs; preserve structure.
- [x] Validate local links and document intentional compatibility exceptions.

## Task 3: Runtime presentation and package metadata

Files: runtime/web/templates, runtime/app/main.py, runtime presentation strings,
runtime/pyproject.toml, runtime/uv.lock and package-related tests.

- [x] Add failing checks at actual rendering/configuration/metadata boundaries.
- [x] Update product strings, API title and distribution metadata without logic changes.
- [x] Run affected Python/Node tests and frozen lock check.

## Task 4: Integration review

- [x] Audit remaining old identifiers and distinguish contracts from branding.
- [x] Run bounded hardware/network-isolated regression checks and docs validation.
- [x] Obtain independent diff review and fix actionable naming/isolation regressions.
- [x] Record outcomes and limitations; publish only upon an explicit follow-up request.

## Verification outcome (2026-10-24)

- Hardware/network-isolated targeted run: **317 passed**, 25 warnings, 28.32 s.
  Coverage includes public CLI installation/ownership, endpoint and backend
  precedence, recovery/audit callers, module and graph contracts, documentation,
  package metadata, positive-selection wheel/sdist builds, and process cleanup.
- Frozen dependency lock check, Bash syntax checks and `git diff --check` passed.
  Full documentation validation passed. Old proof sections remain unchanged;
  the additive `ax4lab_naming` receipt records this change against `35d64d5`.
- Static real-template preview at 1920×1080: Live, Replay and Runtime IDE show
  AX4LAB without clipped branding. JavaScript was disabled, so this proves
  presentation only, not live interactions. Browser plugin was unavailable;
  local Playwright was used without application/device calls.
- Independent review found four endpoint/backend omissions; all were fixed and
  the bounded re-review passed. Regression tests reproduced each issue first.
- A broad-suite attempt reached its 90-second bound without completing; no full
  suite pass is claimed. Warnings in the targeted run include existing Pydantic/
  FastAPI deprecations and repeated recovery-module execution through `runpy`.
- Original repository remains clean at `3136aa3`. The installed `atr` launcher
  was not modified. No global installation, publication, server restart, model
  startup or equipment operation was performed.

Separate CLI/web/graph names are not complete device isolation: optional model
services, configured bridge endpoints and low-level runtime channels can still be
shared. Serialized schemas, graph IDs, Python imports and historical evidence
retain their compatibility identities.

## Authorized follow-up

The user subsequently requested an operator cheat sheet and publication. Add the
cheat sheet to the reader-facing indexes and documentation manifest, then publish
the structured checkout to the requested public `JIN9811/AX4LAB` repository.
Retain the original repository as upstream provenance; do not push changes there.

---
doc_type: evidence
subtype: audit
status: active
authority: descriptive
audience: [developer, maintainer, reviewer]
scope: [source_integration, repository_layout, portability]
summary: Pinned latest-main documentation integration into the structured portable source tree.
evidence_date: 2026-10-23
method: Committed-object delta mapping, three-way text reconciliation, explicit identity overlays, and offline scoped validation.
related_docs:
  - system/maintenance/repository_layout_reference_index.md
  - system/maintenance/portable_installation_evidence.md
supersedes: []
---

# Latest main integration — 2026-10-23

## Pinned scope

Source delta: `ba273ddb0fc2bf8795630d51d93d3932748e0a51` →
`3136aa3c66e10c8151472d955914b5390b17ea3d`.
Destination base: `2f29adf9d95c692a15531833f2352f0e7f40925d` on
`refactor/repository-layout`.

The integration reads source Git objects, not a live source checkout. No device,
server, running process, model, calibration, private state, global launcher,
remote repository, or publication was changed. This report is software-only
evidence; it does not establish experimental or hardware readiness.

## Exact changed-file accounting

All **157** source delta records are accounted for: **118 modifications,
29 deletions, and 10 evidence relocations** (five R100, two R092, two R090,
one R077). The full per-file inventory is
`repository_layout_manifest.json` → `latest_main_integration.records`.
Every record has the original/new source path, previous/current destination,
disposition, previous destination identity and, where retained, current identity.
All pre-existing manifest sections, including `entries`, `historical_documents`
and migration-phase identities, remain unchanged. The new overlay is not a
baseline refresh or a claim that the later bytes equal the earlier proof.

Content was reconciled against mapped base and upstream text. Parsed links and
owned metadata were remapped into `system/`, `docs/`, and `runtime/`. Conflicts
were reviewed by class: upstream navigation supersedes retired paper links;
the English user manual retains the checkout-local launch instructions;
destination-only publication approvals remain, with replaced approval records
preserved separately. Two archived specs needed remaining metadata links to
retired material removed or remapped. Historical code excerpts and experimental
measurements are not rewritten as current operational instructions.

The 23 wiki topics retain their topic identities and upstream review timestamps;
their source digests refer to final mapped source bytes. This content integration
is separate from the earlier reference-only migration provenance. It does not
claim a new scientific review at the old timestamp.

## Portability and module boundaries

The outer-root Linux launch command remains
`bash runtime/install/run_local.sh`; `atr up` is only an optional alias whose
checkout binding must be checked. The first-run tutorials, root navigation,
installer documentation and moved-environment rebuild instructions retain the
portable-install amendments. A newly edited GUI development-server example
explicitly uses `runtime/` with `../.venv/` and isolated data roots.

Module organization is preserved, not flattened: agent owners remain under
`runtime/agents/` (including `core/`), module graphs under
`runtime/graphs/modules/`, agent packages under `runtime/packages/agents/`,
and device owners under `runtime/device_bridges/`. The upstream delta adds no
new unified `modules/<owner>/` organization. No experiment runtime implementation
is changed by this synchronization.

## Manuscript retirement and retained evidence

The source-deleted manuscript chapters, figures, artifact manifest, paper
documentation standard, dedicated checker and dedicated test are retired.
Their old identities remain recoverable in Git and the frozen migration manifest.
Ten evidence files now reside under `system/runtime/evidence/`; measurements,
limitations and historical test outcomes remain evidence, not a new run.
`docs/paper/CITATION.cff` is preserved. The positive source-distribution inventory
and active validation commands no longer invoke the retired checker.

## Validation evidence

On exported tree `37a6ca8551b67a3ec075a3ac17bde564924598e3`:

- Isolated documentation validator: passed.
- Isolated layout/documentation/knowledge-compatibility selection: **85 passed,
  1 skipped, 21 warnings**. The skipped bounded build gate was not requested;
  warnings are existing Pydantic field-shadowing/FastAPI lifecycle deprecations.
- New explicit-supersession tests were written first and observed failing;
  the final local selection passed **12 tests**, with one build test deselected
  and one host pytest warning about the unavailable asyncio config plugin.
- Full mapped-reference audit: **3,023 references**, no missing files, missing
  anchors, escaping references, or metadata errors (230 external URLs counted,
  not network-checked).
- Frozen manifest preservation comparison and `git diff --check`: passed.

The first exported documentation check correctly exposed a second historical
validation entrypoint; the governance validator now checks the explicit new
identity instead of incorrectly comparing superseded bytes to the frozen hash.
Tampering with superseded bytes remains a failure. The report and its inventory
entry were added after the exported-tree run; the controller performs final
committed-tree checks. The documentation validator passed again with the report
and its inventory entry present. The full experiment suite and hardware/server checks were
not run. No full-suite success claim is made.

### Independent committed-tree verification

The controller independently exported commit `d5ec3c7f98022030b33b9daf350039ddddb63ada`
and ran the following bounded selections with isolated PID, network, mount, IPC,
and user namespaces, synthetic devices, a fresh HOME, and read-only validation
dependencies. No original checkout, credentials, host service or physical device
was available to the tests.

| Selection | Result |
| --- | --- |
| Installation profile, bootstrap, doctor, resource defaults | 120 passed |
| Layout manifest, distribution selection, documentation, knowledge relocation, new integration checks | 85 passed, 1 opt-in build skipped |
| Package contracts, module control views, Module Designer API, IDE lifecycle | 82 passed |
| Knowledge publication, runtime Wiki safety, reference roots | 172 passed |
| Documentation governance validator | Passed |
| Mapped reference audit | 3,024 checked; no local file, anchor, containment or metadata errors |

The four pytest selections total **459 passed and 1 skipped**. Their warning
counts were respectively 0, 21, 22, and 5, matching the corresponding baseline
categories. The audit counted 230 external URLs without requesting them.

An independent Git-object comparison verified all 157 source delta records,
their previous and current identities, unchanged pre-existing manifest sections,
and no implementation changes in the protected experiment runtime directories.
All 98 agent files (including 30 core-owner files), 20 graph-module files,
18 package files, 68 bridge files and 133 web files remain under `runtime/`.
The source checkout remained clean at `3136aa3`.

The task-level reviewer approved the integration without actionable findings.
These checks do not replace the existing portability acceptance limitations,
full-suite results, or commissioning on the target PC with actual equipment.

## Integration decisions

- Apply the final upstream net delta rather than replaying its reverted
  documentation redesign. A request for that discarded intermediate design
  would require a separate change.
- Keep the existing isolated AX4LAB clone and its structured layout. No original
  checkout migration or newly unified module hierarchy is implied.
- Retire only the upstream-deleted manuscript files; keep experimental evidence
  and citation metadata. Retired tracked files remain recoverable from Git.
- Keep all work in local commits on `refactor/repository-layout`; no push or new
  public repository was performed. Publication remains a separate action.
- Reuse the preceding local commit's author identity through per-command Git
  options, without changing global or repository Git configuration. Attribution
  can be amended if a different author is intended.

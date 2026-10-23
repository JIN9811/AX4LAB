<!-- atr-doc
doc_type: design
subtype: architecture
status: active
authority: proposal
decision_status: approved
audience: [developer, maintainer, operator]
scope: [installation, path_resolution, environment_validation]
summary: Portable Linux installation and Windows UTM bridge configuration without changing experiment behavior.
related_docs:
  - system/specs/2026-10-01-repository-layout-design.md
  - runtime/install/README.md
supersedes: []
-->

# Portable Installation Design

## Intent and agreed scope

Make AX4LAB installable in a different directory and under a different user
without editing application source. The agreed target is a Linux main PC and a
Windows UTM bridge. Clone, install, configure the local equipment, and launch
should be a documented, repeatable sequence. This is not a claim that a clone
alone contains models, calibration, device drivers, or experiment data.

Work is confined to the AX4LAB clone. Existing running installations and the
separate Rebot deployment/runtime workspaces remain untouched. This document is
approved by the user on 2026-10-23, not an implemented or validated installation.

## Approaches

- **Native execution with explicit installation profiles (recommended):** reuse
  RuntimePaths, bootstrap scripts, doctor, and existing hardware bridges. Keep
  native device access while making dependencies and their versions explicit.
- **Full containerization:** more uniform userspace, but introduces additional
  USB, GPU, desktop-session and camera integration work. Not selected for this
  scope; existing containers may still be used by their existing integrations.
- **Manual path replacement:** small initial effort but does not provide
  reproducible installations or detect accidental use of an old checkout.

The user accepted the proposed native direction and Linux/Windows scope. The
specific mechanisms below are implementation proposals, not prior commitments.

## Invariants

- Preserve module identities, blueprint/package contracts and Runtime IDE routes.
- Do not change experiment ordering, prompts, completion checks, recovery,
  thresholds, timeouts, motion generation or device commands.
- Do not repoint the installed global atr command, restart services, migrate
  private state, change calibration, or operate equipment during this work.
- Do not silently switch to another model, environment, simulator, repository or
  device when a required dependency is absent.
- Setup never launches experiments. Diagnostics are non-actuating; installation
  does not itself authorize service startup or device access.

## Current evidence

RuntimePaths resolves source and default private-store roots inside the clone.
The remaining problems cross boundaries outside that resolver:

- The installed atr launcher binds the original checkout; install_cli.sh can
  overwrite the same global launcher path.
- devices.yaml contains personal UTM, YOLO and RealSense build paths.
- The specimen pose bridge passes a relative ROS setup path to a script running
  in scripts/vision; missing setup files are silently skipped.
- The simulation GUI still supplies an old checkout-specific scene path.
- LeRobot uses external Conda environments, source repositories and caches.
- A fresh clone lacks the virtual environment, private settings and ROS build.
- bootstrap_linux.sh exists, but installs requirements without a frozen
  dependency contract, installs the global launcher by default, and suppresses
  doctor failure with `|| true`.

## Path ownership and resolution

Retain RuntimePaths as the authority for repository, runtime, system and private
store roots. Do not introduce a competing root resolver or relocate existing
stores. Keep ATR_LAYOUT_CONFIG and ATR_PATH_BINDINGS semantics unchanged.

Add one versioned, git-ignored installation profile for external resources.
Ship a sanitized example. Use an explicit profile selector, proposed as
ATR_INSTALL_PROFILE; otherwise use a documented checkout-local profile. Missing
profiles are acceptable for unconfigured GUI use, not for required live paths.

The external profile describes only integration resources: executables,
environments, source checkouts, ROS setup files, models and bridge endpoint
references. It does not override experiment policy or device safety settings.
Credentials remain in the existing secret mechanism; never copy values into
tracked templates, diagnostics or manifests.

Resolution rules:

1. An explicit existing user override wins; report conflicts and provenance.
2. Installation-profile values fill installation-specific resource fields.
3. Built-in portable defaults apply only where their ownership is defined.
4. Discovery suggests candidates during setup. Multiple candidates require a
   selection; live execution does not search other home directories as fallback.

Profile-relative external paths resolve against the profile's directory;
code-owned resources resolve against runtime_root. Existing explicitly
configured legacy paths remain valid during migration, with diagnostics, until
the operator replaces them. Unknown keys and unresolved placeholders are errors.
Resolve once into absolute paths before passing values into subprocesses.

Both application consumers and doctor use the same resolved configuration.
Inspect all loaders and independent workers to avoid a GUI-only override.
Printed provenance includes the selected profile and source checkout but redacts
credentials and sensitive URLs. Stale absolute paths in imported run artifacts
are historical references, not executable installation authority.

## Installation and launch

Extend the existing bootstrap entry points; avoid a second installation system.
Provide an isolated checkout launch path that derives its location at invocation
time and uses that checkout's environment. Installing a global alias is opt-in;
replacing an existing alias requires explicit confirmation. Do not change the
meaning of an existing running installation's commands.

Moving source is supported, but moving an installed virtual environment or ROS
install tree is not assumed safe. Detect their old prefixes and rebuild them at
the new location through an explicit setup operation.

Core setup uses a validated frozen dependency set derived from the existing
package and lock files. Hardware/GPU stacks are optional profiles with separate
compatibility constraints, not a forced single Python environment. Record exact
external source revisions and model identifiers/checksums where available.
Never invent a tested version or fetch a floating branch as a reproducibility
guarantee. Unverified combinations remain explicitly unverified.

Offer dry-run plans and resumable/idempotent setup steps. Network downloads,
system package installation, license/authentication requirements and large model
sizes are disclosed before execution. Existing installations are selectable,
not modified automatically. No credentials or private datasets are published.

Use the existing Windows bridge installers rather than installing the Linux
stack on the UTM PC. Validate host-local paths on the Windows side; a Windows
path is never resolved relative to the Linux checkout. Installation does not
start desktop automation or alter the UTM application.

## Private resources and compatibility

Connection memory, learned policies, calibration and experiment artifacts are
separate from source. Provide an explicit mapping/import procedure, not an
automatic copy from the original PC. Calibration and device identity must be
matched before reuse; a valid path alone is insufficient.

The existing OMX and newly supplied Rebot B601 runtime paths are distinct
integrations. This work does not convert robot profiles or assume their LeRobot
editable sources are interchangeable. Validate whichever integration the
operator selects without changing robot type or behavior.

## Diagnostics and failure behavior

Extend doctor to report core, selected integration and optional-feature results
separately, in human-readable and machine-readable form. Include source roots,
Python/package origin, external paths, dependency versions, missing files, ROS
prefixes, launcher binding and configured service endpoints. Do not print secrets.

Default checks are offline and non-actuating. No device connections, model
startup, environment installation or service restart. Offline diagnostics cannot
certify hardware readiness. An optional later connectivity check needs separate
scope and must not be confused with this verification.

Core install failures produce a failing exit code. Missing required resources
fail an explicitly selected integration check; unused integrations are marked
not configured. A GUI may open without equipment. Do not add new stopping points
inside experiment loops; configuration errors belong at setup or explicit launch
preflight, with actionable messages instead of silent fallback.

## Verification and acceptance

1. Audit runtime, configuration, GUI defaults, scripts, manifests and install
   documentation; classify historical/example paths separately from active ones.
2. Test resolution from unrelated working directories, paths containing spaces,
   changed usernames, missing/ambiguous dependencies and explicit overrides.
3. Run clean-install checks without access to the original repository, home
   caches or editable packages. Verify imported module origins and all writes.
4. Verify bootstrap dry-run, failure propagation and launcher collision handling.
5. Verify ROS setup paths reach the child process as intended, and missing
   required setups are identified without launching cameras.
6. Compare module/package/Runtime IDE contracts and mocked loop event sequences
   with the pre-change clone. Preserve the existing non-actuating behavior.
7. Test Windows path handling and bridge installation in Windows CI or a real
   isolated Windows environment. Linux static checks alone are not acceptance.
8. Record Linux distribution, architecture, Python and GPU compatibility actually
   tested. Do not advertise all Linux PCs as supported from one-host testing.

Acceptance requires an isolated core install and GUI/test-mode startup, correct
resource selection, no original-tree access or writes, and passing relevant
contract regressions. Hardware acceptance is a separate later test authorized
by the operator. If dependencies or a Windows runner are unavailable, report the
remaining acceptance gap rather than marking portability complete.

## Delivery and approval boundaries

Implement in small sections: resolver/profile integration; existing path fixes;
bootstrap/launch/doctor; clean-environment tests; operator documentation. Maintain
the structured branch and leave the original main checkout unchanged.

Reuse docs for operator instructions and system for contracts/design details.
Do not create or publish the AX4LAB GitHub repository as part of this design
step. Review publication contents and request the appropriate release step
separately. No operating-server cutover is implied by passing tests.

Exact helper names, profile schema keys, test fixtures and lock implementation
are left to the implementation plan, provided these ownership and compatibility
rules hold. Design approval is required before implementation.

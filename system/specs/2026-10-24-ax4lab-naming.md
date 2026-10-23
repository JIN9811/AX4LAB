# AX4LAB naming and command isolation

## Intent and approved scope

The user approved separating the new AX4LAB checkout from the existing `atr`
installation and requested consistent terminology and commands throughout it.
Work only in the desktop AX4LAB checkout. Do not modify the original repository,
install a global launcher, start hardware, or restart running services.

## Approach

Use `AX4LAB` for the project and UI, `ax4lab` for its CLI and distribution name.
Rename active operator documentation and examples without changing their structure.
Install only `~/.local/bin/ax4lab`; never overwrite or execute `atr`.
Default the new web server and CLI to port 7861, with coherent configurable host,
port and URL settings. Detect conflicting CLI ownership rather than replacing it.

An alias named `atr` would retain the original collision. A blind repository-wide
replacement would break existing experiment evidence and serialized contracts.
Therefore retain internal schema IDs, graph IDs, import names, device protocols,
and historical source/evidence identities. Document these compatibility exceptions.
New launcher controls use `AX4LAB_*`; retained low-level runtime environment keys
remain explicit compatibility configuration, not new product branding.

## Acceptance

- Installing into a synthetic home containing an old `atr` leaves it unchanged.
- Generated `ax4lab` help, start, status and stop target the selected checkout.
- Server and CLI default to 7861; explicit custom ports remain coherent.
- GUI/API titles and active operator prose refer to AX4LAB.
- Python metadata and frozen lock agree on distribution `ax4lab`.
- No renaming of experiment contracts, no hardware operations, no publication.
- Installer/doctor/port tests, module contracts, documentation links and targeted
  frontend checks pass; unrelated baseline failures are reported, not hidden.

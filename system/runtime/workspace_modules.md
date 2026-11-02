# Workspace modules

Workspace modules are trusted, locally installed interactive capabilities. They
are separate from agent, graph, device-bridge, and package registries. Installing
or removing a module means installing or removing its folder; catalog refresh
only re-reads metadata and never imports or hot-reloads provider code.

## Installed folder contract

Each direct child of a workspace's module root contains:

- `module.yaml`: safely parsed declarative metadata.
- `provider.py`: trusted code, loaded lazily by the owning workspace only when an
  action is requested.
- A local icon, `icon.svg` by default or the relative filename in `icon`.

The descriptor has a schema owned by the workspace and the common `id`,
`version`, and non-empty `label` fields. IDs are lower snake case and versions
are three-part numeric versions. Workspace validators define domain fields such
as `schema`, `actions`, and `output_kinds`; descriptors do not define imports,
Python or JavaScript snippets, shell commands, executable equations, or remote
resource URLs. Descriptor, provider, and icon paths are resolved and must remain
inside the installed module folder, including through symlinks.

`discover_modules(root, validator)` returns `(modules, errors)`. Discovery is
sorted by installed folder and isolates malformed entries. Every duplicate ID is
excluded. An error is `{"module": <folder-or-duplicate-id>, "message": <text>}`.
No provider is imported during discovery.

Each module result has this exact common record shape:

```python
{
    "id": str,                    # identity snapshot, copied from validated metadata
    "version": str,               # identity snapshot, copied from validated metadata
    "root": Path,                 # resolved module folder
    "descriptor_path": Path,      # resolved module.yaml
    "provider_path": Path,        # resolved provider.py
    "icon_path": Path,            # resolved local icon
    "descriptor": dict,           # deep-copied validator result
}
```

Consumers use the top-level `id` and `version` as the discovery-time identity;
they do not recompute identity from a descriptor a caller may later copy or
modify. Persistent jobs must additionally pin their validated configuration and
provider fingerprint. The common catalog does not load providers or promise
Python hot reload.

Serial Communication is the one compatibility adapter for the legacy fixed
filename `protocol.py`. It keeps `ax4lab.serial_device.v1`, `ModuleCatalog`, its
URLs, profiles, validation, protocol factory, and restart-on-code-change check.
New workspaces and nested provider catalogs use `provider.py`.
Design additionally validates nonempty unique `actions` from `preview`/`generate`
and `output_kinds: [stl]`; these are enforced admission/control declarations, not
arbitrary executable actions. Geometry `agent_handoff` is a boolean defaulting
to false; manual support does not automatically enable experiment handoff.

## Declarative fields

`normalize_fields(fields, defaults, values)` validates metadata and returns a
deep-copied defaults mapping overlaid with explicit values. Every field requires
a unique lower-snake-case `key`, a non-empty `label`, a supported `type`, and a
default. Unknown default or value keys are rejected. Hidden fields are still
validated by the server.

Supported field metadata and values are:

- `number`: finite JSON number, not boolean; finite inclusive `min` and `max`,
  with an optional positive finite `step`.
- `integer`: JSON integer, not boolean; integer inclusive `min` and `max`, with
  an optional positive integer `step`.
- `enum`: a non-empty unique list of non-empty string `options`.
- `boolean`: a JSON boolean.
- `text`: a string.
- `vector`: a JSON list with positive integer `length`; every element is a
  finite number inside the shared finite inclusive `min` and `max`.

All types may have string `description` and `unit` metadata. Visibility is data,
not code, and has exactly one of these forms:

```yaml
visible_when: {field: enabled, equals: true}
visible_when: {field: mode, in: [preview, final]}
```

The referenced field must exist and cannot be the field itself. Condition values
must be valid values for the referenced field. No other visibility operators,
expressions, callbacks, or snippets are accepted. API validation is authoritative;
frontends apply the same rules only for immediate feedback.

Catalog refresh discovers additions and removals. Workspace enable/disable state
controls new selections but does not delete profiles, jobs, artifacts, or past
evidence. Saved references to missing modules remain explicit and unavailable;
they are never substituted with another provider.

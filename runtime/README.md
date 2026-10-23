# AX4LAB runtime

This directory contains the `ax4lab` Python build project and
its executable peers. `runtime` is a filesystem container, not a Python import
namespace. Public imports such as `app`, `graphs`, and `utils` are unchanged.

From the outer repository, install with `python -m pip install -e './runtime[dev]'`.
Run source commands from this directory using the outer `.venv` interpreter.
Build distributions here with `python -m build --no-isolation`.

The outer repository owns Git, `.github`, `.env`, `.venv`, `system`, and private
store bindings. `configs/repository_layout.json` names the source roots; explicit
`ATR_LAYOUT_CONFIG` and `ATR_PATH_BINDINGS` bindings support installed use.
Moving sources never activates new private stores.

`distribution-files.json` positively enumerates wheel code/resources and the
broader sdist delivery surface. Wheel resources under
`_autonomous_researcher_resources` can be copied into an explicitly bound runtime
tree. Optional Piper voice assets are source/sdist delivery only, not wheel
contents. The standalone Windows bridge retains its own environment, portable
Python and data-root contracts.

The public launcher is `ax4lab` and the default web port is `7861`, separate
from an existing `atr` installation. Legacy `atr.*` schema IDs, graph IDs,
low-level environment keys and the resource-directory name above remain stable
for compatibility; they are not alternative launch commands.

See [installation](install/README.md), [repository navigation](../README.md),
and [license](LICENSE).

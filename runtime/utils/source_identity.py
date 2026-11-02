"""Attest trusted Python implementation bytes when their module code executes.

This is source provenance, not a sandbox for arbitrary installed Python code.
The hook must run directly in each fingerprinted module's top-level frame.
"""
import hashlib
from pathlib import Path
import sys


_LOADED = {}


def attest_module_source(filename):
    path = Path(filename).resolve()
    source = path.read_bytes()
    executing = sys._getframe(1).f_code
    # A timestamp-valid stale pyc must not attest newer source bytes. Compare the
    # entire executing module (nested function bodies and module constants too).
    current = compile(source, executing.co_filename, "exec", dont_inherit=True, optimize=sys.flags.optimize)
    if executing != current:
        raise ValueError(f"Executing source differs from disk; restart worker: {path.name}")
    digest = hashlib.sha256(source).hexdigest()
    if path in _LOADED and _LOADED[path] != digest:
        raise ValueError(f"Loaded source changed; restart worker: {path.name}")
    _LOADED[path] = digest


def verify_loaded_source(relative_name, expected_digest):
    """Unloaded modules attest on import; loaded modules must match acceptance."""
    name = relative_name.removesuffix(".py").replace("/", ".")
    if name.endswith(".__init__"):
        name = name.removesuffix(".__init__")
    module = sys.modules.get(name)
    if module is None:
        return
    filename = getattr(module, "__file__", None)
    if filename is None or _LOADED.get(Path(filename).resolve()) != expected_digest:
        raise ValueError(f"Loaded numerical source differs from acceptance; restart worker: {name}")


attest_module_source(__file__)

"""Representation-specific public inputs backed by the installed descriptor."""
from copy import deepcopy

from utils.source_identity import attest_module_source
from .catalog import parameter_schema
from .engine import normalize_request

attest_module_source(__file__)


def geometry_input_contract(catalog, record, representation=None):
    descriptor = record["descriptor"]
    mode = descriptor["default_representation"] if representation is None else representation
    if not isinstance(mode, str) or mode not in descriptor["representations"]:
        raise ValueError("Unsupported representation")
    template = normalize_request({"module_id": record["module_id"], "geometry_id": record["id"],
        "provider_version": record["version"], "representation": mode,
        "quality": "final", "resolution": 128}, catalog)
    fields, _ = parameter_schema(descriptor, mode)
    return {
        "schema": "ax4lab.geometry_input_contract.v1",
        "module_id": record["module_id"], "module_version": record["module_version"],
        "geometry_id": record["id"], "provider_version": record["version"],
        "representation": mode, "representations": deepcopy(descriptor["representations"]),
        "parameters": [{**deepcopy(field), "default": deepcopy(template["parameters"][field["key"]]),
                        "role": descriptor.get("parameter_roles", {}).get(field["key"], "design")}
                       for field in fields],
        "request_template": template,
        "design_family": descriptor.get("design_family", ""),
        "design_notes": deepcopy(descriptor.get("design_notes", [])),
        "default_basis": descriptor.get("default_basis", ""),
        "research_sources": deepcopy(descriptor.get("research_sources", [])),
    }

"""Resolve stable connection references without model-specific routing rules."""
from __future__ import annotations

from copy import deepcopy


def endpoint_ref(endpoint_id: str) -> str:
    return f"endpoint:{endpoint_id}"


def resolve_endpoint(backend, reference: str):
    """Legacy concrete pins are accepted only when their endpoint is unique."""
    routes = getattr(backend, '_endpoint_routes', None)
    if routes is None:
        if reference.startswith('endpoint:'):
            raise ValueError('Endpoint registry is not configured.')
        return None  # Compatibility for standalone adapters, not runtime routing.
    if reference.startswith('endpoint:'):
        row = routes.get(reference.removeprefix('endpoint:'))
        if row is None:
            raise ValueError('Endpoint is no longer registered. Select a registered connection.')
        return row
    if reference in routes:
        return routes[reference]
    matches = [row for row in routes.values() if row['model'] == reference]
    if len(matches) != 1:
        raise ValueError('Legacy model reference is missing or ambiguous. Select an endpoint ID.')
    return matches[0]


def endpoint_token(backend, row):
    if row is None:
        return backend._api_key
    if row.get('access_token') is not None:
        return row['access_token']
    if row['base_url'].rstrip('/') == getattr(backend, '_api_key_base_url', backend._base_url).rstrip('/'):
        return backend._api_key
    return ''


def has_endpoint_credentials(backend, references) -> bool:
    """Only credentials assigned to the selected API roles enable that route."""
    for reference in references:
        try:
            row = resolve_endpoint(backend, reference)
        except ValueError:
            continue
        if row is not None and row.get('access_token'):
            return True
    return False


def role_endpoint_references(router):
    """Include fallback-only connections when binding credentials and API usage."""
    return [reference
            for task in ('orchestrator_plan', 'design_reasoning')
            for selection in (router.select(task),)
            for reference in (selection.primary, selection.fallback) if reference]


def selected_uses_global_credential(backend, references, base_url) -> bool:
    """A legacy global key remains usable only at its explicitly bound address."""
    for reference in references:
        try:
            row = resolve_endpoint(backend, reference)
        except ValueError:
            continue
        if row is None:
            if backend._base_url.rstrip('/') == base_url.rstrip('/'):
                return True
        elif row.get('access_token') is None and row['base_url'].rstrip('/') == base_url.rstrip('/'):
            return True
    return False


def normalize_roles(config: dict) -> dict:
    """Read old worker-role keys once; expose only generic role names."""
    cfg = deepcopy(config)
    for models in [cfg.get('models', {}), *cfg.get('backend_models', {}).values(),
                   cfg.get('role_capabilities', {})]:
        if isinstance(models, dict) and 'e4b' in models:
            models.setdefault('worker', models.pop('e4b'))
    cfg['task_routes'] = {task: ('worker' if role == 'e4b' else role)
                          for task, role in cfg.get('task_routes', {}).items()}
    return cfg

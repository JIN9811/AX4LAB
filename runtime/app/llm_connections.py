"""Endpoint registrations and role assignment, independent of model naming."""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager, nullcontext
from copy import copy, deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Literal
from urllib.parse import urlsplit
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from backends.endpoint_routes import endpoint_ref
from backends.llm_lease import RECONCILIATION_PRIORITY
from backends.model_router import ModelRouter


def endpoint_url(value: str) -> str:
    value = str(value).strip().rstrip('/')
    try:
        url = urlsplit(value)
        port = url.port
    except ValueError:
        raise ValueError('Enter a valid HTTP(S) base URL.') from None
    if (url.scheme not in {'http', 'https'} or not url.hostname or url.username is not None
            or url.password is not None or url.query or url.fragment or port == 0
            or any(c.isspace() or ord(c) < 32 for c in value)):
        raise ValueError('Use an HTTP(S) base URL without credentials, query parameters, or fragments.')
    if url.path.endswith(('/chat/completions', '/models', '/responses')):
        raise ValueError('Enter the API base URL, usually ending in /v1.')
    return value


class EndpointCapabilities(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: bool = True
    vision: bool = False


class EndpointRecord(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')
    label: str = Field(default='', max_length=256)
    provider: Literal['openai', 'vllm']
    base_url: str = Field(min_length=1, max_length=2048)
    model: str = Field(min_length=1, max_length=256)
    management_id: str = Field(default='', max_length=256)
    access_token: str | None = Field(default=None, max_length=4096)
    capabilities: EndpointCapabilities = Field(default_factory=EndpointCapabilities)
    _url = field_validator('base_url')(endpoint_url)

    @field_validator('model', 'label', 'management_id')
    @classmethod
    def clean_text(cls, value, info):
        value = value.strip()
        if (info.field_name == 'model' and not value) or any(ord(c) < 32 for c in value):
            raise ValueError('Enter a valid connection value.')
        return value


class ConnectionProfile(BaseModel):
    model_config = ConfigDict(extra='forbid')
    orchestrator_endpoint: str = Field(min_length=1, max_length=64)
    worker_endpoint: str = Field(min_length=1, max_length=64)
    orchestrator_fallback: str = Field(default='', max_length=64)
    worker_fallback: str = Field(default='', max_length=64)


class LLMConnections:
    def __init__(self, context, path: Path, *, busy=lambda: False):
        self.ctx, self.path, self.busy = context, path, busy
        self._defaults = {name: copy(context.primary_backends[name]) for name in ('openai', 'vllm')}
        self._probing = False
        self._managing = False
        self.load_error = ''
        self.migration_notices = []
        self._endpoints = {}
        for client in self._defaults.values():
            self._endpoints.update(deepcopy(getattr(client, '_endpoint_routes', {})))
        self._profiles = self._seed_profiles()
        self._deployment_profiles = deepcopy(self._profiles)
        self._apply_all()

    @property
    def _manager(self):
        return getattr(self._defaults['vllm'], '_nemoclaw_runtime', None)

    def _legacy_endpoint(self, provider, model, url, *, token=None, management_id=''):
        for key, row in self._endpoints.items():
            if row['provider'] == provider and row['model'] == model and row['base_url'] == url:
                if token is not None:
                    self._endpoints[key] = EndpointRecord.model_validate(
                        {**row, 'access_token': token}).model_dump()
                return key
        key = provider + '-' + hashlib.sha256(f'{url}\0{model}'.encode()).hexdigest()[:12]
        self._endpoints[key] = EndpointRecord(id=key, label=model, provider=provider, base_url=url,
            model=model, management_id=management_id, access_token=token).model_dump()
        return key

    def _seed_profiles(self):
        profiles = {}
        for provider, client in self._defaults.items():
            router = self.ctx.model_routers[provider]
            profile = {}
            for role, task in [('orchestrator', 'orchestrator_plan'), ('worker', 'design_reasoning')]:
                selection = router.select(task)
                for field, ref in [(role + '_endpoint', selection.primary), (role + '_fallback', selection.fallback)]:
                    if not ref:
                        profile[field] = ''
                    elif ref.startswith('endpoint:'):
                        profile[field] = ref.removeprefix('endpoint:')
                    else:
                        url = getattr(client, '_model_base_urls', {}).get(ref, client._base_url)
                        managed = ref if provider == 'vllm' and self._manager and ref in self._manager._models else ''
                        profile[field] = self._legacy_endpoint(provider, ref, url, management_id=managed)
            profiles[provider] = profile
        return profiles

    def _ensure_idle(self):
        if self.is_busy():
            raise RuntimeError('Connection changes require an idle runtime and no active LLM request.')

    def is_busy(self):
        return self._probing or self._managing or bool(self.busy())

    @asynccontextmanager
    async def lifecycle(self, operation):
        """Reserve the same inference lease while a server is starting/stopping."""
        self._ensure_idle()
        self._managing = True
        lease = getattr(self.ctx, 'llm_lease', None)
        try:
            async with (lease.acquire(RECONCILIATION_PRIORITY,
                                     f'connection-{operation}', wait=False) if lease else nullcontext()):
                yield
        finally:
            self._managing = False

    def _validate_record(self, key, raw):
        row = EndpointRecord.model_validate({**raw, 'id': key}).model_dump()
        if row['management_id']:
            retained = self._endpoints.get(key, {})
            configured_but_disabled = self._manager is None and retained.get('management_id') == row['management_id']
            if row['provider'] != 'vllm' or (not configured_but_disabled and
                    (self._manager is None or row['management_id'] not in self._manager._models)):
                raise ValueError('Choose an existing local server management target.')
        row['label'] = row['label'] or key
        return row

    def validate(self, provider, raw, *, endpoints=None):
        if provider not in self._defaults:
            raise ValueError('Choose openai or vllm.')
        profile = ConnectionProfile.model_validate(raw).model_dump()
        registry = self._endpoints if endpoints is None else endpoints
        for key in profile.values():
            if key and (key not in registry or registry[key]['provider'] != provider):
                raise ValueError('Select a registered endpoint belonging to this provider.')
        return profile

    def _apply_all(self):
        for provider, profile in self._profiles.items():
            backend = self.ctx.primary_backends[provider]
            backend._endpoint_routes = deepcopy({key: row for key, row in self._endpoints.items() if row['provider'] == provider})
            primary = self._endpoints.get(profile['orchestrator_endpoint'])
            if primary is None:
                continue
            # Keep inherited credentials bound to their original address even
            # when that endpoint moves from orchestrator to worker/fallback.
            if not hasattr(backend, '_api_key_base_url'):
                backend._api_key_base_url = backend._base_url
            backend._base_url = primary['base_url']
            cfg = deepcopy(self.ctx.model_routers[provider]._cfg)
            metadata = deepcopy(self.ctx.runtime_profiles.get(provider, {}))
            for role in ('orchestrator', 'worker'):
                key, fallback = profile[role + '_endpoint'], profile[role + '_fallback']
                cfg.setdefault('models', {})[role] = dict(primary=endpoint_ref(key),
                    fallback=endpoint_ref(fallback) if fallback else None)
                row = self._endpoints.get(key, {})
                metadata.setdefault('models', {})[role] = dict(primary=endpoint_ref(key),
                    fallback=endpoint_ref(fallback) if fallback else None,
                    endpoint_id=key, served_model=row.get('model', ''), capabilities=row.get('capabilities', {}))
            metadata.setdefault('backend', {}).update(proxy_url=primary['base_url'], connection_mode='endpoint')
            metadata['models'].pop('e4b', None)  # Imported metadata only.
            router = ModelRouter(cfg)
            self.ctx.model_routers[provider] = router
            if self.ctx.active_backend == provider:
                self.ctx.model_router = router
            self.ctx.runtime_profiles[provider] = metadata

    def public(self):
        records = []
        for row in self._endpoints.values():
            public = {key: deepcopy(value) for key, value in row.items() if key != 'access_token'}
            public['has_access_token'] = bool(row.get('access_token'))
            records.append(public)
        profiles = deepcopy(self._profiles)
        for profile in profiles.values():
            profile['base_url'] = self._endpoints.get(profile['orchestrator_endpoint'], {}).get('base_url', '')
        targets = [dict(id=key, label=value.deployment) for key, value in getattr(self._manager, '_models', {}).items()]
        return dict(ok=True, profiles=profiles, endpoints=records, management_targets=targets,
            local_models=self._local_rows(), active_backend=self.ctx.active_backend,
            busy=self.is_busy(), load_error=self.load_error, migration_notices=list(self.migration_notices))

    def _local_rows(self):
        return [dict(id=key, model=endpoint_ref(key), served_model=row['model'], label=row['label'],
                     base_url=row['base_url'], managed=bool(row['management_id']))
                for key, row in self._endpoints.items() if row['provider'] == 'vllm']

    async def local_models_public(self):
        rows = self._local_rows()
        backend = self.ctx.primary_backends['vllm']
        for row in rows:
            try:
                row['base_url'] = await backend._base_url_for_model(row['model'])
            except (RuntimeError, OSError, ValueError):
                pass
        return rows

    def save_endpoint(self, key, raw):
        self._ensure_idle()
        row = self._validate_record(key, raw)
        old = self._endpoints.get(key, {})
        if row['access_token'] is None:
            same = (row['provider'], row['base_url'], row['management_id']) == (
                old.get('provider'), old.get('base_url'), old.get('management_id', ''))
            changed_target = old and row['management_id'] != old.get('management_id', '')
            row['access_token'] = old.get('access_token') if same else ('' if changed_target else None)
        endpoints = {**self._endpoints, key: row}
        if len(endpoints) > 128:
            raise ValueError('Register at most 128 endpoints.')
        for provider, profile in self._profiles.items():
            self.validate(provider, profile, endpoints=endpoints)
        self._persist(self._profiles, endpoints)
        self._endpoints = endpoints
        self._apply_all()
        return self.public()

    def remove_endpoint(self, key):
        self._ensure_idle()
        if key not in self._endpoints:
            raise ValueError('Endpoint is not registered.')
        if any(key in profile.values() for profile in self._profiles.values()):
            raise ValueError('This endpoint is assigned to a role. Save a replacement before removing it.')
        endpoints = {k: row for k, row in self._endpoints.items() if k != key}
        self._persist(self._profiles, endpoints)
        self._endpoints = endpoints
        self._apply_all()
        return self.public()

    def save(self, provider, raw):
        self._ensure_idle()
        profile = self.validate(provider, raw)
        profiles = {**self._profiles, provider: profile}
        self._persist(profiles, self._endpoints)
        self._profiles = profiles
        self._apply_all()
        self.load_error = ''
        return self.public()

    def _persist(self, profiles, endpoints):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix='.llm-connections-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(dict(schema='llm_connections.v2', profiles=profiles, endpoints=endpoints), stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def _load_legacy(self, data):
        """Import explicit legacy selections; retired managed targets stay retired."""
        catalog = data.get('local_models', {})
        if not isinstance(catalog, dict):
            raise ValueError('Invalid legacy catalog.')
        for model, item in catalog.items():
            # Keep unused operator registrations too. Retired managed entries
            # are handled below only through the configured management targets.
            if not isinstance(item, dict) or item.get('managed'):
                continue
            try:
                if len(self._endpoints) >= 128:
                    raise ValueError('Endpoint limit reached.')
                self._legacy_endpoint('vllm', str(model), endpoint_url(item['base_url']),
                                      token=item.get('access_token'))
            except (ValueError, KeyError, TypeError):
                self.migration_notices.append('An invalid or excess legacy catalog entry was skipped.')
        for provider, raw in data['profiles'].items():
            if provider not in self._defaults or not isinstance(raw, dict):
                self.migration_notices.append('An invalid legacy provider profile was skipped.')
                continue
            previous = deepcopy(self._endpoints)
            profile = {}
            try:
                url = endpoint_url(raw['base_url'])
                for role in ('orchestrator', 'worker'):
                    for field, old_field in [(role + '_endpoint', role + '_model'), (role + '_fallback', role + '_fallback')]:
                        model = str(raw.get(old_field) or '')
                        if not model:
                            if field.endswith('_endpoint'):
                                raise ValueError('Missing legacy role.')
                            profile[field] = ''
                            continue
                        item = catalog.get(model, {}) if provider == 'vllm' else {}
                        managed = provider == 'vllm' and (item.get('managed') or raw.get('mode') == 'managed')
                        matches = [key for key, row in self._endpoints.items() if row['provider'] == provider and row['model'] == model]
                        if managed and not matches:
                            profile[field] = self._deployment_profiles[provider][field] if field.endswith('_endpoint') else ''
                            self.migration_notices.append('A retired managed connection was replaced by the configured endpoint; retired fallback removed.')
                        elif managed and len(matches) == 1:
                            profile[field] = matches[0]
                        else:
                            profile[field] = self._legacy_endpoint(provider, model,
                                endpoint_url(item.get('base_url') or url),
                                token=item.get('access_token', raw.get('access_token')))
                self._profiles[provider] = self.validate(provider, profile)
            except (ValueError, KeyError, TypeError):
                self._endpoints = previous
                self.migration_notices.append(f'The legacy {provider} profile could not be imported; deployment defaults retained.')

    def load(self):
        if not self.path.exists():
            return
        before = deepcopy((self._endpoints, self._profiles))
        try:
            data = json.loads(self.path.read_text())
            if not isinstance(data, dict) or not isinstance(data.get('profiles'), dict):
                raise ValueError('Invalid connection settings envelope.')
            if data.get('schema') == 'llm_connections.v1':
                self._load_legacy(data)
            elif data.get('schema') == 'llm_connections.v2':
                raw = data.get('endpoints')
                if not isinstance(raw, dict) or len(raw) > 128:
                    raise ValueError('Invalid endpoint registry.')
                endpoints = {key: self._validate_record(key, value) for key, value in raw.items()}
                profiles = {name: self.validate(name, value, endpoints=endpoints) for name, value in data['profiles'].items()}
                if set(profiles) != set(self._defaults):
                    raise ValueError('Missing provider profile.')
                self._endpoints, self._profiles = endpoints, profiles
            else:
                raise ValueError('Unsupported connection schema.')
        except (OSError, ValueError, KeyError, TypeError):
            self._endpoints, self._profiles = before
            self.load_error = 'Saved connections could not be loaded. Deployment defaults remain active.'
            return
        self._apply_all()
        self.load_error = ''

    async def probe(self, provider, raw, role, *, api_key=''):
        self._ensure_idle()
        lease = getattr(self.ctx, 'llm_lease', None)
        self._probing = True
        try:
            async with (lease.acquire(RECONCILIATION_PRIORITY, 'connection-check', wait=False) if lease else nullcontext()):
                return await self._probe(provider, raw, role, api_key=api_key)
        finally:
            self._probing = False

    async def _probe(self, provider, raw, role, *, api_key=''):
        if role not in {'orchestrator', 'worker'}:
            raise ValueError('Choose the orchestrator or worker endpoint.')
        profile = self.validate(provider, raw)
        key = profile[role + '_endpoint']
        client = copy(self.ctx.primary_backends[provider])
        client._endpoint_routes = deepcopy(client._endpoint_routes)
        if provider == 'openai':
            client._api_key = api_key
            client._api_key_base_url = self._endpoints[key]['base_url']
            client._api_routing_enabled = True
        client._timeout_s = 60
        start = time.monotonic()
        try:
            reply = await asyncio.wait_for(client.complete(model=endpoint_ref(key),
                system_prompt='Connection check only. Reply with Connection confirmed.',
                user_prompt='Do not use tools or start an experiment.',
                metadata={'max_tokens': 128, 'task_type': 'connection_check'}), timeout=60)
            text = str(reply.text or '').strip()
            if not text or text == 'None' or reply.raw.get('mock'):
                raise ValueError('No usable reply.')
            for secret in (api_key, client._api_key, self._endpoints[key].get('access_token')):
                if secret:
                    text = text.replace(secret, '[redacted]')
            return dict(ok=True, endpoint_id=key, model=self._endpoints[key]['model'], reply=text[:2000], elapsed_s=round(time.monotonic()-start, 2))
        except httpx.HTTPStatusError as exc:
            message = f'Endpoint returned HTTP {exc.response.status_code}. Check its URL, served model ID and credentials.'
        except (httpx.TimeoutException, TimeoutError):
            message = 'No response within 60 seconds. Check model readiness.'
        except httpx.RequestError:
            message = 'Cannot connect to this endpoint. Check the address and server.'
        except (ValueError, RuntimeError):
            message = 'No usable reply. Check credentials, capabilities and that the model is loaded.'
        return dict(ok=False, endpoint_id=key, model=self._endpoints[key]['model'], message=message, elapsed_s=round(time.monotonic()-start, 2))

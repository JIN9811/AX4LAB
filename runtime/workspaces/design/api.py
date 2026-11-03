"""Loopback/same-origin Design API; host paths are never request inputs."""
import ipaddress
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from .profiles import DesignError

MAX_BODY = 65536


def local_only(request):
    def loopback(host):
        try:
            return ipaddress.ip_address(host).is_loopback
        except (ValueError, TypeError):
            return host == 'localhost'
    if not request.client or not loopback(request.client.host) or not loopback(request.url.hostname):
        raise HTTPException(403, 'Design workspace is available on this PC only')
    origin = request.headers.get('origin')
    if origin:
        try:
            parsed = urlsplit(origin)
        except ValueError as exc:
            raise HTTPException(403, 'Invalid Design origin') from exc
        if (parsed.scheme, parsed.netloc) != (request.url.scheme, request.url.netloc) or parsed.path or parsed.query or parsed.fragment:
            raise HTTPException(403, 'Cross-origin Design access is disabled')
    if request.headers.get('sec-fetch-site') == 'cross-site':
        raise HTTPException(403, 'Cross-site Design access is disabled')


class LocalBoundedRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bounded(request):
            local_only(request)
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_BODY:
                    raise HTTPException(413, 'Design payload exceeds 64 KiB')
                chunks.append(chunk)
            request._body = b''.join(chunks)
            return await handler(request)
        return bounded


class Payload(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Validate(Payload):
    request: dict


class Submit(Validate):
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')


class Profile(Validate):
    name: str = Field(min_length=1, max_length=120)


class UpdateProfile(Profile):
    revision: int = Field(ge=1, strict=True)


class DeleteProfile(Payload):
    revision: int = Field(ge=1, strict=True)
    confirmed: StrictBool


class ModuleState(Payload):
    revision: int = Field(ge=1, strict=True)
    enabled: StrictBool


def create_router(service, templates=None):
    router = APIRouter(route_class=LocalBoundedRoute)

    def call(operation):
        try:
            return operation(service() if callable(service) else service)
        except DesignError as exc:
            status = {'not_found':404, 'module_unavailable':404, 'invalid_request':422,
                'queue_full':429, 'compute_unavailable':503, 'unavailable':503,
                'store_write_failed':503, 'store_invalid':503}.get(exc.code, 409)
            raise HTTPException(status, {'code':exc.code, 'message':str(exc)}) from exc

    @router.get('/design', include_in_schema=False)
    def workspace(request: Request):
        if templates is None:
            raise HTTPException(404)
        return templates.TemplateResponse(request=request, name='design.html', context={})

    @router.get('/api/design/modules')
    def modules():
        return call(lambda s: {'modules':s.modules(), 'errors':s.catalog.errors})

    @router.post('/api/design/modules/refresh')
    def refresh():
        return call(lambda s:s.refresh())

    @router.get('/api/design/modules/{module_id}/icon')
    def icon(module_id: str):
        return call(lambda s:FileResponse(s.icon(module_id), media_type='image/svg+xml', headers={'Content-Security-Policy':"default-src 'none'; sandbox", 'X-Content-Type-Options':'nosniff'}))

    @router.get('/api/design/modules/{module_id}/geometries')
    def geometries(module_id: str):
        return call(lambda s:{'geometries':s.geometries(module_id)})

    @router.get('/api/design/modules/{module_id}/geometries/{geometry_id}/contract')
    def contract(module_id: str, geometry_id: str, representation: str | None = None):
        return call(lambda s:s.contract(module_id, geometry_id, representation))

    @router.get('/api/design/modules/{module_id}/state')
    def state(module_id: str):
        return call(lambda s:s.module_state(module_id))

    @router.put('/api/design/modules/{module_id}/state')
    def set_state(module_id: str, body: ModuleState):
        return call(lambda s:s.module_state(module_id, **body.model_dump()))

    @router.get('/api/design/profiles')
    def profiles():
        return call(lambda s:{'profiles':s.profiles()})

    @router.post('/api/design/profiles', status_code=201)
    def create(body: Profile):
        return call(lambda s:s.create_profile(body.model_dump()))

    @router.get('/api/design/profiles/{profile_id}')
    def profile(profile_id: str):
        return call(lambda s:s.profile(profile_id))

    @router.put('/api/design/profiles/{profile_id}')
    def update(profile_id: str, body: UpdateProfile):
        return call(lambda s:s.update_profile(profile_id, body.model_dump(exclude={'revision'}), body.revision))

    @router.delete('/api/design/profiles/{profile_id}')
    def delete(profile_id: str, body: DeleteProfile):
        call(lambda s:s.delete_profile(profile_id, body.revision, confirmed=body.confirmed))
        return {'deleted':True}

    @router.post('/api/design/validate')
    def validate(body: Validate):
        return call(lambda s:s.validate(body.request))

    @router.get('/api/design/jobs')
    def jobs():
        return call(lambda s:{'jobs':s.jobs()})

    @router.post('/api/design/jobs', status_code=202)
    def submit(body: Submit):
        return call(lambda s:s.submit(body.request, idempotency_key=body.idempotency_key))

    @router.get('/api/design/jobs/{job_id}')
    def job(job_id: str):
        return call(lambda s:s.job(job_id))

    @router.post('/api/design/jobs/{job_id}/cancel')
    def cancel(job_id: str):
        return call(lambda s:s.cancel(job_id))

    @router.get('/api/design/jobs/{job_id}/artifacts/{artifact_id}')
    def artifact(job_id: str, artifact_id: str):
        return call(lambda s:FileResponse(s.artifact(job_id, artifact_id), filename='geometry.stl',
            media_type='model/stl', headers={'X-Content-Type-Options':'nosniff'}))

    return router

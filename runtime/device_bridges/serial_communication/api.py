"""Loopback-only HTTP adapter. The device core has no web dependencies."""
import ipaddress
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from .errors import SerialError


def local_only(request: Request):
    def loopback(host):
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return host == 'localhost'
    if not request.client or not loopback(request.client.host) or not loopback(request.url.hostname):
        raise HTTPException(403, 'Serial workspace is available on this PC only')
    origin = request.headers.get('origin')
    if origin:
        parsed = urlsplit(origin)
        if (parsed.scheme, parsed.netloc) != (request.url.scheme, request.url.netloc):
            raise HTTPException(403, 'Cross-origin serial access is disabled')
    if request.headers.get('sec-fetch-site') == 'cross-site':
        raise HTTPException(403, 'Cross-site serial access is disabled')


class Payload(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class NewProfile(Payload):
    module_id: str
    name: str | None = None
    settings: dict = Field(default_factory=dict)


class UpdateProfile(Payload):
    revision: int = Field(ge=1, strict=True)
    name: str | None = None
    settings: dict = Field(default_factory=dict)


class DeleteProfile(Payload):
    revision: int = Field(ge=1, strict=True)
    confirmed: StrictBool


class ReadRequest(Payload):
    timeout_s: float | None = Field(default=None, ge=.1, le=30)


class PollRequest(Payload):
    enabled: StrictBool
    interval_s: float = Field(default=1, ge=.2, le=3600)


class RecordRequest(Payload):
    enabled: StrictBool


def create_router(service, templates=None):
    router = APIRouter(dependencies=[Depends(local_only)])

    def call(operation):
        try:
            s = service() if callable(service) else service
            return operation(s)
        except SerialError as exc:
            # The HTTP request arrived; the downstream instrument did not reply.
            # 408 makes browsers such as Firefox replay POSTs and send another P.
            status = {'not_found':404, 'module_unavailable':404, 'timeout':504,
                      'invalid_config':422, 'dependency_missing':503,
                      'config_invalid':503, 'config_write_failed':503}.get(exc.code,409)
            raise HTTPException(status, {'code':exc.code, 'message':str(exc)}) from exc

    @router.get('/serial', include_in_schema=False)
    def workspace(request: Request):
        if templates is None:
            raise HTTPException(404)
        return templates.TemplateResponse(request=request, name='serial.html', context={})

    @router.get('/serial/modules/{module_id}/views/{view_id}', include_in_schema=False)
    def module_view(module_id: str, view_id: str, profile_id: str = ''):
        def op(s):
            page = s.catalog.view_file(module_id, view_id)
            if profile_id and s.store.get(profile_id)['module_id'] != module_id:
                raise HTTPException(422, 'Select a profile belonging to this module')
            return FileResponse(page, media_type='text/html')
        return call(op)

    @router.get('/api/serial/modules/{module_id}/views/{view_id}/assets/{asset:path}')
    def module_view_asset(module_id: str, view_id: str, asset: str):
        return call(lambda s: FileResponse(s.catalog.view_file(module_id, view_id, asset)))

    @router.get('/api/serial/modules')
    def modules():
        return call(lambda s: {'modules':s.catalog.list(), 'errors':s.catalog.errors})

    @router.post('/api/serial/modules/refresh')
    def refresh():
        def op(s):
            s.catalog.refresh()
            return {'modules':s.catalog.list(), 'errors':s.catalog.errors}
        return call(op)

    @router.get('/api/serial/modules/{module_id}/icon')
    def icon(module_id: str):
        def op(s):
            p = s.catalog.icon(module_id)
            if p is not None and p.is_file():
                return FileResponse(p)
            return Response('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96"><rect x="12" y="12" width="72" height="72" rx="16" fill="#18445a"/><path d="M28 48h40M48 28v40" stroke="#58daf6" stroke-width="6"/></svg>',media_type='image/svg+xml')
        return call(op)

    @router.get('/api/serial/ports')
    def ports():
        return call(lambda s: {'ports':s.ports()})

    @router.get('/api/serial/profiles')
    def profiles():
        return call(lambda s: {'profiles':s.profiles()})

    @router.post('/api/serial/profiles', status_code=201)
    def create(body: NewProfile):
        return call(lambda s:s.create_profile(body.model_dump(exclude_none=True)))

    @router.get('/api/serial/profiles/{profile_id}')
    def profile(profile_id: str):
        return call(lambda s:s.store.get(profile_id))

    @router.put('/api/serial/profiles/{profile_id}')
    def update(profile_id: str, body: UpdateProfile):
        return call(lambda s:s.update_profile(profile_id,body.model_dump(exclude={'revision'},exclude_none=True),body.revision))

    @router.delete('/api/serial/profiles/{profile_id}')
    def delete(profile_id: str, body: DeleteProfile):
        if not body.confirmed:
            raise HTTPException(422, 'Confirm profile deletion')
        call(lambda s:s.delete_profile(profile_id,body.revision))
        return {'deleted':True}

    @router.post('/api/serial/profiles/{profile_id}/connect')
    def connect(profile_id: str):
        return call(lambda s:s.connect(profile_id))

    @router.post('/api/serial/profiles/{profile_id}/disconnect')
    def disconnect(profile_id: str):
        return call(lambda s:s.disconnect(profile_id))

    @router.get('/api/serial/profiles/{profile_id}/status')
    def status(profile_id: str):
        return call(lambda s:s.status(profile_id))

    @router.get('/api/serial/profiles/{profile_id}/latest')
    def latest(profile_id: str):
        return call(lambda s:s.latest(profile_id))

    @router.get('/api/serial/profiles/{profile_id}/events')
    def events(profile_id: str, after: int = Query(default=0, ge=0)):
        return call(lambda s:s.events(profile_id,after))

    @router.post('/api/serial/profiles/{profile_id}/read')
    def read(profile_id: str, body: ReadRequest = ReadRequest()):
        return call(lambda s:s.read(profile_id,body.timeout_s))

    @router.post('/api/serial/profiles/{profile_id}/polling')
    def polling(profile_id: str, body: PollRequest):
        return call(lambda s:s.polling(profile_id,body.enabled,body.interval_s))

    @router.post('/api/serial/profiles/{profile_id}/recording')
    def recording(profile_id: str, body: RecordRequest):
        return call(lambda s:s.record(profile_id,body.enabled))

    @router.get('/api/serial/recordings')
    def recordings():
        return call(lambda s: {'recordings':s.recordings()})

    @router.get('/api/serial/recordings/{recording_id}/{filename}')
    def download(recording_id: str, filename: str):
        return call(lambda s:FileResponse(s.recording_file(recording_id,filename),filename=filename))

    return router

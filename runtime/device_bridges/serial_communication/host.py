"""Thin AX4LAB binding. Registering routes does not open a port or write config."""
import logging
import re
import threading

from .api import create_router


class SerialTelemetryAccessFilter(logging.Filter):
    """Quiet successful UI reads; retain errors and explicit device actions."""
    route = re.compile(r'/api/serial/profiles(?:/[^/]+/(?:status|latest|events))?')

    def filter(self, record):
        # Uvicorn access records carry client, method, path, version, status.
        # Unknown formats stay visible rather than hiding unrelated diagnostics.
        if not isinstance(record.args, tuple) or len(record.args) != 5:
            return True
        _, method, path, _, status = record.args
        if not isinstance(path, str) or not isinstance(status, int):
            return True
        return not (method == 'GET' and 200 <= status < 400
                    and self.route.fullmatch(path.split('?', 1)[0]))


def install_serial_workspace(app, paths, templates):
    access = logging.getLogger('uvicorn.access')
    if not any(isinstance(f, SerialTelemetryAccessFilter) for f in access.filters):
        access.addFilter(SerialTelemetryAccessFilter())
    lock = threading.Lock()
    instance = None

    def service():
        nonlocal instance
        with lock:
            if instance is None:
                from .service import SerialService
                instance = SerialService(paths.memory_root/'serial_communication/profiles.json',
                                         paths.log_root/'serial_communication')
            return instance

    def shutdown():
        with lock:
            if instance is not None:
                instance.shutdown()

    app.include_router(create_router(service, templates))
    app.router.add_event_handler('shutdown',shutdown)

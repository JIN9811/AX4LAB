"""Thin AX4LAB binding. Registering routes does not open a port or write config."""
import threading

from .api import create_router


def install_serial_workspace(app, paths, templates):
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

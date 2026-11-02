"""Lazy public host binding. Installation neither starts compute nor touches devices."""
import threading

from .api import create_router


def install_design_workspace(app, paths, templates):
    lock = threading.Lock()
    instance = None

    def service():
        nonlocal instance
        with lock:
            if instance is None:
                from .service import DesignService
                instance = DesignService(paths.memory_root, paths.artifact_root)
            return instance

    def shutdown():
        with lock:
            if instance is not None:
                instance.shutdown()

    app.include_router(create_router(service, templates))
    app.router.add_event_handler('shutdown', shutdown)

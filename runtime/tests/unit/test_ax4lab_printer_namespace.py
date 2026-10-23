"""Public artifact URLs belong to this checkout's server, never an old ATR port."""
import pytest


@pytest.mark.parametrize('port', [None, '8877'])
def test_printer_handoff_url_uses_current_ax4lab_server_port(monkeypatch, port):
    from device_bridges.printer_fleet.bridge import PrinterDeviceBridgeManager
    manager = object.__new__(PrinterDeviceBridgeManager)
    monkeypatch.setattr(manager, '_detect_printer_reachable_host', lambda _: '192.0.2.20')
    monkeypatch.delenv('AX4LAB_PORT', raising=False)
    monkeypatch.setenv('ATR_SERVER_PORT', '7860')
    monkeypatch.setenv('PORT', '7860')
    if port:
        monkeypatch.setenv('AX4LAB_PORT', port)
    url = manager._bambu_http_public_base_url({}, printer_host='192.0.2.30')
    assert url == f'http://192.0.2.20:{port or "7861"}'


def test_explicit_printer_handoff_port_remains_authoritative(monkeypatch):
    from device_bridges.printer_fleet.bridge import PrinterDeviceBridgeManager
    manager = object.__new__(PrinterDeviceBridgeManager)
    monkeypatch.setattr(manager, '_detect_printer_reachable_host', lambda _: '192.0.2.20')
    monkeypatch.setenv('AX4LAB_PORT', '8877')
    url = manager._bambu_http_public_base_url({'server_port': 9988}, printer_host='192.0.2.30')
    assert url == 'http://192.0.2.20:9988'

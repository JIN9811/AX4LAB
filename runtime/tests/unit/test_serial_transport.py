from types import SimpleNamespace


def test_usb_serial_identity_survives_socket_change(monkeypatch):
    from serial.tools import list_ports
    from device_bridges.serial_communication.transport import enumerate_ports
    p=SimpleNamespace(device='/dev/fake',vid=1,pid=2,serial_number='stable',location='1-2',interface=None,description='Scale')
    monkeypatch.setattr(list_ports,'comports',lambda:[p])
    identity=enumerate_ports()[0]['device_id']
    p.location='1-5';p.device='/dev/other'
    assert enumerate_ports()[0]['device_id']==identity

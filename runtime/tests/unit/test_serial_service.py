import json
import queue
import threading
import time

import pytest


class FakeTransport:
    def __init__(self, reply=True):
        self.queue = queue.Queue()
        self.sent = []
        self.closed = False
        self.reply = reply
        self.close_count = 0

    @property
    def in_waiting(self):
        return 0

    def read(self, size=4096):
        if self.closed:
            raise OSError('disconnected')
        try:
            return self.queue.get(timeout=.01)
        except queue.Empty:
            return b''

    def write(self, data):
        self.sent.append(data)
        if self.reply:
            self.queue.put(b' 14:55:57 W:    8.56 g  \r\n')
        return len(data)

    def flush(self):
        pass

    def close(self):
        self.close_count += 1
        self.closed = True


@pytest.fixture
def rig(tmp_path):
    from device_bridges.serial_communication.service import SerialService
    transports = []
    ports = [{'port':'/dev/fake1','device_id':'device1','description':'Scale','available':True},
             {'port':'/dev/fake2','device_id':'device2','description':'UTM','available':True}]
    def factory(settings):
        t = FakeTransport()
        transports.append(t)
        return t
    s = SerialService(tmp_path/'config.json', tmp_path/'logs', port_provider=lambda:ports, transport_factory=factory)
    yield s, transports, ports
    s.shutdown()


def profile(s, port='/dev/fake1'):
    return s.create_profile({'name':'Scale','module_id':'cas_mwii_plus','settings':{'port':port}})


def test_set_no_io_connect_snapshot_fresh_read_and_timeout(rig):
    from device_bridges.serial_communication.errors import SerialError
    s, ts, _ = rig
    p = profile(s)
    assert not ts
    s.connect(p['id'])
    assert ts[0].sent == []
    result = s.read(p['id'], .2)
    assert result['values']['weight'] == 8.56
    assert ts[0].sent == [b'P']
    s.update_profile(p['id'], {'name':'Updated','settings':{'port':'/dev/fake2'}}, p['revision'])
    assert s.status(p['id'])['active_settings']['port'] == '/dev/fake1'
    assert s.status(p['id'])['needs_reconnect']
    ts[0].reply = False
    with pytest.raises(SerialError, match='timed out'):
        s.read(p['id'], .1)
    assert s.status(p['id'])['state'] == 'connected'
    s.disconnect(p['id'])
    assert ts[0].closed
    s.connect(p['id'])
    assert s.status(p['id'])['active_settings']['port'] == '/dev/fake2'


def test_alias_ownership_unplug_and_identity_mismatch(rig):
    from device_bridges.serial_communication.errors import SerialError
    s, ts, ports = rig
    p, other = profile(s), profile(s)
    s.connect(p['id'])
    with pytest.raises(SerialError):
        s.connect(other['id'])
    ts[0].closed = True
    end = time.monotonic()+1
    while s.status(p['id'])['state'] != 'error' and time.monotonic() < end:
        time.sleep(.01)
    assert s.status(p['id'])['state'] == 'error'
    s.disconnect(p['id'])
    ports[0]['device_id'] = 'different-device'
    with pytest.raises(SerialError):
        s.connect(p['id'])


def test_polling_recording_download_and_delete(rig):
    s, ts, _ = rig
    p = profile(s)
    s.connect(p['id'])
    rec = s.record(p['id'], True)
    s.read(p['id'], .2)
    s.polling(p['id'], True, .2)
    time.sleep(.3)
    s.polling(p['id'], False, .2)
    stopped = s.record(p['id'], False)
    assert stopped['complete'] is True
    manifest = json.loads(s.recording_file(rec['id'], 'manifest.json').read_text())
    assert manifest['complete'] is True
    assert s.recording_file(rec['id'], 'raw.bin').read_bytes()
    assert '8.56' in s.recording_file(rec['id'], 'measurements.csv').read_text()
    assert s.events(p['id'],0)['events']
    s.disconnect(p['id'])
    s.delete_profile(p['id'],p['revision'])
    assert s.profiles() == [] and len(s.recordings()) == 1


def test_stale_and_missing_module_profile_survive(rig):
    s, ts, _ = rig
    p = profile(s)
    s.connect(p['id'])
    assert s.latest(p['id'])['measurement'] is None
    assert s.status(p['id'])['receive_state'] == 'no_data'
    assert s.connect(p['id'])['state'] == 'connected'
    assert len(ts) == 1


def test_invalid_settings_and_paths_are_rejected(rig):
    from device_bridges.serial_communication.errors import SerialError
    s, _, _ = rig
    p = profile(s)
    for patch in [{'baudrate':-1},{'timeout_s':float('nan')},{'unexpected':True}]:
        with pytest.raises(SerialError):
            s.update_profile(p['id'], {'settings':patch}, p['revision'])
    with pytest.raises(SerialError):
        s.recording_file('../config.json','manifest.json')


def test_concurrent_read_does_not_duplicate_command(rig):
    from device_bridges.serial_communication.errors import SerialError
    s, ts, _ = rig
    p = profile(s)
    s.connect(p['id'])
    ts[0].reply = False
    results = []
    def read():
        try:
            s.read(p['id'], .2)
        except SerialError as e:
            results.append(e.code)
    a = threading.Thread(target=read)
    a.start()
    while not ts[0].sent:
        time.sleep(.001)
    read()
    a.join()
    assert sorted(results) == ['busy','timeout']
    assert ts[0].sent == [b'P']


def test_disconnect_closes_transport_exactly_once(rig):
    s, ts, _ = rig
    p = profile(s)
    s.connect(p['id'])
    s.disconnect(p['id'])
    s.disconnect(p['id'])
    assert ts[0].close_count == 1


def test_set_cannot_silently_rebind_reused_port(rig):
    from device_bridges.serial_communication.errors import SerialError
    s,ts,ports=rig
    p=profile(s)
    ports[0]['device_id']='replacement'
    with pytest.raises(SerialError):
        s.update_profile(p['id'],{'name':'Renamed','settings':{'port':'/dev/fake1'}},1)
    assert s.store.get(p['id'])['settings']['device_id']=='device1'
    with pytest.raises(SerialError):
        s.connect(p['id'])
    assert not ts


def test_request_never_uses_unbounded_output_drain(rig):
    s,ts,_=rig
    p=profile(s);s.connect(p['id'])
    def forbidden():
        raise AssertionError('flush/tcdrain is not bounded by write_timeout')
    ts[0].flush=forbidden
    assert s.read(p['id'],.2)['values']['weight']==8.56
    s.disconnect(p['id'])
    assert ts[0].closed


def test_independent_devices_bounded_history_and_staleness(rig):
    s,ts,_=rig
    a,b=profile(s),profile(s,'/dev/fake2')
    s.connect(a['id']);s.connect(b['id'])
    s.read(a['id'],.2);s.read(b['id'],.2)
    assert len(ts)==2 and all(t.sent==[b'P'] for t in ts)
    session=s._session(a['id'])
    with session.cv:
        for i in range(1100):
            session._event('request_error',{'message':str(i)})
        session.measurement['received_at']-=100
    events=s.events(a['id'],0)
    assert events['gap'] and len(events['events'])==1000
    assert s.latest(a['id'])['stale']
    s.disconnect(a['id'])
    assert s.status(b['id'])['state']=='connected'

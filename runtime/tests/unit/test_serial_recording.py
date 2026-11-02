import json
import queue


def test_queue_overflow_marks_recording_incomplete(tmp_path):
    from device_bridges.serial_communication.recording import Recording
    r=Recording(tmp_path,{})
    def full(*args):
        raise queue.Full
    r.q.put_nowait=full
    r.enqueue('rx',{'hex':'00','received_at':0})
    assert r.close()['complete'] is False
    saved=json.loads((r.path/'manifest.json').read_text())
    assert saved['dropped']==1 and 'overflow' in saved['error']


def test_disk_failure_marks_incomplete(tmp_path,monkeypatch):
    from device_bridges.serial_communication import recording
    def fail(*args,**kwargs):
        raise OSError('disk full')
    monkeypatch.setattr(recording,'open',fail,raising=False)
    r=recording.Recording(tmp_path,{})
    result=r.close()
    assert not result['complete'] and 'disk full' in result['error']

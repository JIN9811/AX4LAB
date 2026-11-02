"""One device reader; tabs observe it instead of opening their own connections."""
from collections import deque
from copy import deepcopy
import threading
import time
from uuid import uuid4

from .errors import SerialError
from .recording import Recording


class Session:
    def __init__(self, profile, descriptor, transport, parser, log_root):
        self.profile = deepcopy(profile)
        self.descriptor = deepcopy(descriptor)
        self.transport, self.parser, self.log_root = transport, parser, log_root
        self.id = uuid4().hex
        self.state, self.error = 'connected', None
        self.cv = threading.Condition(threading.RLock())
        self.io = threading.Lock()
        self.transport_closed = False
        self.request_gate = threading.Lock()
        self.stop = threading.Event()
        self.poll_stop = threading.Event()
        self.poll_thread = None
        self.poll_interval = 1.
        self.sequence, self.rx_bytes, self.tx_bytes = 0, 0, 0
        self.history = deque(maxlen=1000)
        self.measurement = None
        self.last_rx = None
        self.recording = None
        self.last_recording = None
        self.thread = threading.Thread(target=self._reader, name=f'serial-{self.id[:6]}', daemon=True)
        self.thread.start()

    def _event(self, kind, payload):
        self.sequence += 1
        event = {'sequence':self.sequence,'kind':kind,'received_at':time.time(),**payload}
        self.history.append(event)
        if self.recording and kind in {'rx','tx','measurement'}:
            self.recording.enqueue(kind,event)
        return event

    def _consume(self, data):
        with self.cv:
            self.rx_bytes += len(data)
            self.last_rx = time.time()
            self._event('rx', {'hex':data.hex()})
            for row in self.parser.feed(data):
                self.measurement = self._event('measurement', row)
            self.cv.notify_all()

    def _reader(self):
        try:
            while not self.stop.is_set():
                with self.io:
                    data = self.transport.read(4096)
                    if data:
                        self._consume(data)
                self.stop.wait(.001)
        except Exception as exc:
            with self.cv:
                if not self.stop.is_set():
                    self.state, self.error = 'error', str(exc)
                    self._event('error', {'message':str(exc)})
                self.cv.notify_all()
        finally:
            self._close_transport()
            self.poll_stop.set()
            with self.cv:
                if self.recording:
                    if self.state == 'error':
                        self.recording.meta['error'] = self.error
                    self.last_recording = self.recording.close()
                    self.recording = None

    def _close_transport(self):
        with self.io:
            if not self.transport_closed:
                self.transport_closed = True
                self.transport.close()

    def snapshot(self):
        with self.cv:
            age = None if self.measurement is None else max(0,time.time()-self.measurement['received_at'])
            stale = age is not None and (age>self.profile['settings']['stale_after_s'] or self.state!='connected')
            return {'session_id':self.id,'state':self.state,'error':self.error,
                    'active_revision':self.profile['revision'],'active_settings':deepcopy(self.profile['settings']),
                    'receive_state':'no_data' if age is None else ('stale' if stale else 'receiving'),
                    'age_s':age,'rx_bytes':self.rx_bytes,'tx_bytes':self.tx_bytes,
                    'parse_errors':self.parser.errors,'last_rx_at':self.last_rx,
                    'polling':bool(self.poll_thread and self.poll_thread.is_alive() and not self.poll_stop.is_set()),
                    'recording':dict(self.recording.meta) if self.recording else None,
                    'last_recording':deepcopy(self.last_recording)}

    def events(self, after):
        with self.cv:
            oldest = self.history[0]['sequence'] if self.history else self.sequence+1
            return {'session_id':self.id,'cursor':self.sequence,'gap':after<oldest-1,
                    'events':deepcopy([e for e in self.history if e['sequence']>after])}

    def read(self, timeout_s):
        if not self.request_gate.acquire(blocking=False):
            raise SerialError('busy','A measurement request is already pending')
        try:
            command = self.parser.request()
            with self.io:
                with self.cv:
                    if self.state != 'connected':
                        raise SerialError('disconnected','Device is disconnected')
                # Preserve already-buffered RX as pre-request evidence, not a new reply.
                waiting = min(int(getattr(self.transport,'in_waiting',0)),65536)
                if waiting:
                    old = self.transport.read(waiting)
                    if old:
                        self._consume(old)
                with self.cv:
                    before = self.sequence
                    if command:
                        self.parser.reset()
                        count = self.transport.write(command)
                        # write_timeout bounds write; POSIX flush/tcdrain can hang
                        # indefinitely under flow control and must not hold locks.
                        if count != len(command):
                            raise SerialError('write_failed','Incomplete request write')
                        self.tx_bytes += count
                        self._event('tx',{'hex':command.hex()})
            deadline = time.monotonic()+timeout_s
            with self.cv:
                while True:
                    if self.state != 'connected' or self.stop.is_set() or (threading.current_thread() is self.poll_thread and self.poll_stop.is_set()):
                        raise SerialError('disconnected','Device request cancelled')
                    if self.measurement and self.measurement['sequence']>before:
                        return deepcopy(self.measurement)
                    remaining = deadline-time.monotonic()
                    if remaining<=0:
                        raise SerialError('timeout','Measurement request timed out')
                    self.cv.wait(min(remaining,.1))
        except OSError as exc:
            raise SerialError('write_failed',str(exc)) from exc
        finally:
            self.request_gate.release()

    def polling(self, enabled, interval_s):
        if enabled:
            if 'polling' not in self.descriptor.get('capabilities',[]):
                raise SerialError('unsupported','This module receives without polling')
            if self.state != 'connected':
                raise SerialError('disconnected','Connect first')
            self.poll_interval = interval_s
            if self.poll_thread and self.poll_thread.is_alive():
                return
            self.poll_stop.clear()
            self.poll_thread = threading.Thread(target=self._poll, name=f'serial-poll-{self.id[:6]}',daemon=True)
            self.poll_thread.start()
        else:
            self.poll_stop.set()
            with self.cv:
                self.cv.notify_all()
            if self.poll_thread:
                self.poll_thread.join(timeout=2)

    def _poll(self):
        while not self.poll_stop.is_set() and not self.stop.is_set():
            try:
                self.read(self.profile['settings']['timeout_s'])
            except SerialError as exc:
                with self.cv:
                    self._event('request_error',{'code':exc.code,'message':str(exc)})
            self.poll_stop.wait(self.poll_interval)

    def record(self, enabled):
        with self.cv:
            if enabled:
                if self.state != 'connected':
                    raise SerialError('disconnected','Connect first')
                if self.recording is None:
                    self.recording = Recording(self.log_root, {'profile':self.profile,'module':self.descriptor,
                                                               'session_id':self.id,'origin':'manual_workspace'})
                return dict(self.recording.meta)
            if self.recording:
                self.last_recording = self.recording.close()
                self.recording = None
            return deepcopy(self.last_recording)

    def close(self):
        self.stop.set()
        with self.cv:
            self.state = 'disconnected'
            self.cv.notify_all()
        self.polling(False, self.poll_interval)
        self._close_transport()
        self.thread.join(timeout=2)
        self.record(False)

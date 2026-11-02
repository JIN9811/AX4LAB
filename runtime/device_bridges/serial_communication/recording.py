"""Bounded asynchronous raw and decoded recording, with explicit completeness."""
import csv
import json
from pathlib import Path
import queue
import threading
import time
from uuid import uuid4

from .profiles import atomic_json


class Recording:
    FILES = {'manifest.json', 'raw.bin', 'chunks.jsonl', 'tx.jsonl', 'measurements.jsonl', 'measurements.csv'}

    def __init__(self, root, metadata):
        self.id = uuid4().hex
        self.path = Path(root) / self.id
        self.path.mkdir(parents=True)
        self.meta = {'schema':'ax4lab.serial_recording.v1','id':self.id, **metadata,
                     'started_at':time.time(),'complete':False,'error':None,'dropped':0}
        self.q = queue.Queue(maxsize=2048)
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, name=f'serial-log-{self.id[:6]}', daemon=True)
        atomic_json(self.path/'manifest.json', self.meta)
        self.thread.start()
        self.ready.wait(2)
        if not self.ready.is_set():
            self.meta['error'] = 'Writer startup timed out'
            self.stop.set()

    def enqueue(self, kind, payload):
        if self.meta['error'] or self.stop.is_set():
            self.meta['dropped'] += 1
            return
        try:
            self.q.put_nowait((kind,payload))
        except queue.Full:
            self.meta['error'] = 'Recording queue overflow'
            self.meta['dropped'] += 1

    def _run(self):
        try:
            with (open(self.path/'raw.bin','wb') as raw,
                  open(self.path/'chunks.jsonl','w') as chunks,
                  open(self.path/'tx.jsonl','w') as tx,
                  open(self.path/'measurements.jsonl','w') as rows,
                  open(self.path/'measurements.csv','w',newline='') as flat):
                csvout = csv.writer(flat)
                csvout.writerow(['sequence','received_at','channel','value','unit','quality'])
                self.ready.set()
                offset = 0
                while not self.stop.is_set() or not self.q.empty():
                    try:
                        kind, p = self.q.get(timeout=.1)
                    except queue.Empty:
                        continue
                    if kind == 'rx':
                        data = bytes.fromhex(p['hex'])
                        raw.write(data)
                        chunks.write(json.dumps({'offset':offset,'bytes':len(data),'received_at':p['received_at']})+'\n')
                        offset += len(data)
                    elif kind == 'tx':
                        tx.write(json.dumps(p)+'\n')
                    else:
                        rows.write(json.dumps(p,allow_nan=False)+'\n')
                        for k,v in p['values'].items():
                            csvout.writerow([p['sequence'],p['received_at'],k,v,p['units'].get(k),p.get('quality')])
                self.meta['bytes'] = offset
        except Exception as exc:
            self.meta['error'] = str(exc)
        finally:
            self.ready.set()
            self.meta['ended_at'] = time.time()
            self.meta['complete'] = self.stop.is_set() and not self.meta['error']
            try:
                atomic_json(self.path/'manifest.json', self.meta)
            except OSError as exc:
                self.meta['complete'] = False
                self.meta['error'] = f'Manifest write failed: {exc}'

    def close(self):
        self.stop.set()
        self.thread.join(timeout=3)
        if self.thread.is_alive():
            self.meta['error'] = 'Writer shutdown timed out'
            self.meta['complete'] = False
        return dict(self.meta)

import os
import select
import threading

import pytest


@pytest.mark.skipif(os.name!='posix',reason='POSIX pseudo-terminal test')
def test_actual_pyserial_transport_request_and_receive_without_hardware(tmp_path):
    import pty
    from device_bridges.serial_communication.service import SerialService
    master,slave = pty.openpty()
    name = os.ttyname(slave)
    os.close(slave)
    s=SerialService(tmp_path/'config.json',tmp_path/'logs',port_provider=lambda:[{
        'port':name,'device_id':'test-pty','available':True,'description':'Virtual scale'}])
    sent=[]
    try:
        p=s.create_profile({'module_id':'cas_mwii_plus','settings':{'port':name}})
        s.connect(p['id'])
        def answer():
            readable,_,_=select.select([master],[],[],2)
            if readable:
                sent.append(os.read(master,128))
                os.write(master,b' 14:55:57 W:    8.56 g  \r\n')
        worker=threading.Thread(target=answer)
        worker.start()
        assert s.read(p['id'],2)['values']['weight']==8.56
        worker.join()
        assert sent==[b'P']
    finally:
        s.shutdown()
        os.close(master)

"""Physical transport adapter. Enumeration is passive; opening is explicit."""
import os
from pathlib import Path
import subprocess
import sys

from .errors import SerialError


def enumerate_ports():
    try:
        from serial.tools import list_ports
    except ImportError:
        raise SerialError('dependency_missing', 'Install AX4LAB serial dependencies') from None
    result = []
    for p in list_ports.comports():
        stable = next((str(x) for x in Path('/dev/serial/by-id').glob('*')
                       if x.resolve() == Path(p.device).resolve()), p.device)
        identity = (f'usb:{p.vid}:{p.pid}:{p.serial_number}:{p.interface}'
                    if p.serial_number else f'path:{os.path.realpath(p.device)}')
        # Enumeration cannot certify absence of external readers without opening.
        permitted = os.name == 'nt' or os.access(p.device, os.R_OK | os.W_OK)
        result.append({'port': p.device, 'stable_path': stable, 'device_id': identity,
                       'description': p.description, 'available': permitted,
                       'availability': 'unknown' if permitted else 'permission_denied'})
    return sorted(result, key=lambda x: x['port'])


def open_transport(settings):
    try:
        import serial
    except ImportError:
        raise SerialError('dependency_missing', 'Install AX4LAB serial dependencies') from None
    port = settings['port']
    if sys.platform.startswith('linux'):
        try:
            checked = subprocess.run(['fuser', port], capture_output=True, timeout=2)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SerialError('ownership_unknown', 'Cannot verify port ownership') from exc
        if checked.returncode == 0:
            raise SerialError('port_busy', 'Port is already used by another process')
        if checked.returncode != 1 or checked.stderr.strip():
            raise SerialError('ownership_unknown', 'Cannot verify port ownership')
    conn = None
    try:
        conn = serial.Serial(port=port, baudrate=int(settings['baudrate']),
                             bytesize=int(settings['bytesize']), parity=settings['parity'],
                             stopbits=settings['stopbits'], timeout=.05, write_timeout=1,
                             rtscts=settings['flow_control']=='rtscts',
                             xonxoff=settings['flow_control']=='xonxoff', dsrdtr=False,
                             exclusive=True if os.name == 'posix' else None)
        if os.name == 'posix':
            import fcntl
            import termios
            fcntl.ioctl(conn.fileno(), termios.TIOCEXCL)
        return conn
    except Exception as exc:
        if conn is not None:
            conn.close()
        raise SerialError('connect_failed', f'Cannot open selected port: {exc}') from exc

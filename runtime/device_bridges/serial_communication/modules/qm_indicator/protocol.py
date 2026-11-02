"""Explicit Qm variants. No control commands or inferred absolute position."""
import re


# Installed QM100T range table approved by the operator on 2026-11-02.
# Codes 0..3 were observed at byte 48; code 1 matched the 2000 kgf selection.
# This is not a universal capacity table for other Qmesys configurations.
OBSERVED60_LOAD_RANGES_KGF = {0: 1000, 1: 2000, 2: 5000, 3: 10000}


class Protocol:
    def __init__(self, variant):
        self.variant = variant
        self.length, self.offsets = {
            'encoder42': (42, (8,18,28)),
            'encoder_pot52': (52, (8,18,28,38)),
            'observed60': (60, (4,14,24,34)),
        }[variant]
        self.buffer = b''
        self.errors = 0

    def request(self):
        return None

    def reset(self):
        self.buffer = b''

    def feed(self, data):
        self.buffer += data
        rows = []
        while b'\x02' in self.buffer:
            self.buffer = self.buffer[self.buffer.index(b'\x02'):]
            end = self.buffer.find(b'\x03')
            newer = self.buffer.find(b'\x02', 1)
            if newer >= 0 and (end < 0 or newer < end):
                self.errors += 1
                self.buffer = self.buffer[newer:]
                continue
            if end < 0:
                break
            frame, self.buffer = self.buffer[:end+1], self.buffer[end+1:]
            try:
                if len(frame) != self.length or not frame[-4:-1].isdigit() or sum(frame[1:-4]) % 256 != int(frame[-4:-1]):
                    raise ValueError('Invalid frame/checksum')
                if self.variant != 'observed60' and frame[1:3] != b'LD':
                    raise ValueError('Invalid header')
                values, units, codes = {}, {}, {}
                for key, offset in zip(('load','disp1','disp2','pot'), self.offsets):
                    field = frame[offset:offset+10]
                    if not re.fullmatch(rb'[+-][0-9]{9}', field) or int(chr(field[8])) > 7:
                        raise ValueError('Invalid numeric field')
                    values[key] = int(field[:8]) / 10**int(chr(field[8]))
                    code = chr(field[9])
                    codes[key] = code
                    units[key] = {'0':'kgf','1':'N','2':'kN'}.get(code) if key == 'load' else ('mm' if code == '0' else None)
                range_byte = frame[47:48] if self.variant == 'observed60' else frame[7:8]
                range_code = int(range_byte) if range_byte.isdigit() else None
                values['load_range'] = (OBSERVED60_LOAD_RANGES_KGF.get(range_code)
                                        if self.variant == 'observed60' else None)
                units['load_range'] = 'kgf'
                rows.append({'values': values, 'units': units, 'unit_codes': codes,
                             'load_range_code': range_code,
                             'valid': True, 'checksum_valid': True, 'quality': 'provisional',
                             'variant': self.variant, 'raw_hex': frame.hex(),
                             'uninterpreted_hex': frame[44:-4].hex() if self.variant == 'observed60' else frame[3:8].hex()})
            except (ValueError, IndexError):
                self.errors += 1
        if len(self.buffer) > 4096:
            self.buffer = b''
            self.errors += 1
        return rows


def create_protocol(variant):
    return Protocol(variant)

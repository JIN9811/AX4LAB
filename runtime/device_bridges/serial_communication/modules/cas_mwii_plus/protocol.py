"""CAS print-key response, not an undocumented binary scale protocol."""
import re
import math


class Protocol:
    def __init__(self):
        self.buffer = b''
        self.date = None
        self.errors = 0

    def request(self):
        return b'P'

    def reset(self):
        self.buffer = b''

    def feed(self, data):
        self.buffer += data
        if len(self.buffer) > 8192:
            self.buffer = b''
            self.errors += 1
        result = []
        while b'\n' in self.buffer:
            raw, self.buffer = self.buffer.split(b'\n', 1)
            line = raw.decode('ascii', errors='replace').strip()
            if re.fullmatch(r'\d{2,4}[/.-]\d{1,2}[/.-]\d{1,4}', line):
                self.date = line
                continue
            match = re.search(r'(\d{2}:\d{2}:\d{2})\s+W:\s*([+-]?)\s*(\d+(?:\.\d+)?)\s+(g|kg|mg|ct|PCS|%)\s*$', line)
            if not match:
                if line:
                    self.errors += 1
                continue
            stamp, sign, number, unit = match.groups()
            value = float(sign+number)
            if not math.isfinite(value):
                self.errors += 1
                continue
            result.append({'values': {'weight': value}, 'units': {'weight': unit},
                           'device_time': stamp, 'device_date': self.date, 'stable': None,
                           'raw_text': line, 'quality': 'decoded', 'valid': True})
        return result


def create_protocol(variant):
    if variant != 'print_text':
        raise ValueError('Unsupported CAS format')
    return Protocol()

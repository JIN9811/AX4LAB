"""Test-only native desktop boundary. Never imports input/device libraries."""
import base64
from datetime import datetime, timezone
import hashlib
import io
import json

from PIL import Image


class SyntheticDesktop:
    def __init__(self, fixtures, result_path):
        self.fixtures = fixtures
        self.result_path = result_path
        self.effects = 0
        self.interrupt_after_effect = False
        self.form_open = False
        self.field_value = None
        self.submitted = False

    def image(self):
        with Image.open(self.fixtures / ('after.ppm' if self.submitted else 'before.ppm')) as image:
            return image.convert('RGB')

    @staticmethod
    def region_hash(image, region):
        x, y, w, h = region
        return hashlib.sha256(image.crop((x, y, x + w, y + h)).tobytes()).hexdigest()

    def capture(self, policy):
        image = self.image()
        stream = io.BytesIO()
        image.save(stream, format='PNG')
        png = stream.getvalue()
        return {'captured_at': datetime.now(timezone.utc).isoformat(), 'image_width': 4, 'image_height': 4,
                'desktop_rect': [0, 0, 4, 4], 'window_rect': [0, 0, 4, 4], 'window_title': 'Synthetic demo',
                'window_id': 'synthetic-window-1', 'dpi': 96, 'image_base64': base64.b64encode(png).decode(),
                'image_sha256': hashlib.sha256(png).hexdigest(),
                'anchor_hashes': {key: self.region_hash(image, target['anchor']['region']) for key, target in policy['targets'].items()}}

    def execute(self, action, context):
        target = action['target_id']
        if target == 'button':
            assert action['type'] == 'click' and not self.form_open
            self.form_open = True
        elif target == 'field':
            assert action['type'] == 'write' and self.form_open and not self.submitted
            self.field_value = action['text']
        else:
            assert target == 'submit' and action['type'] == 'click'
            assert self.form_open and self.field_value is not None and not self.submitted
            self.submitted = True
            self.result_path.write_text(json.dumps({'status': 'complete', 'source': 'synthetic', 'specimen': self.field_value}))
        self.effects += 1
        if self.interrupt_after_effect:
            raise RuntimeError('Synthetic interruption after durable effect')
        return {'ok': True, 'result_file': str(self.result_path)}

    def verify(self, policy, context):
        image = self.image()
        checks = [{'type': 'image', 'ok': self.region_hash(image, check['region']) == check['sha256']}
                  for check in policy['postconditions']]
        checks.append({'type': 'synthetic_file', 'ok': self.result_path.exists() and
                       json.loads(self.result_path.read_text()) == {'status': 'complete', 'source': 'synthetic', 'specimen': 'DEMO-001'}})
        return {'ok': all(check['ok'] for check in checks), 'checks': checks}

"""Shared tiny protocol for controller-triggered voice capture (Python only)."""
import os
import re
import json
import tempfile

ROOT = os.path.expanduser('~/Documents/RhinoGamepad')
CONNECTION = os.path.expanduser('~/Library/Application Support/RhinoGamepad/agent-link.json')
_ID = re.compile(r'^[a-f0-9]{32}$')


def valid_id(value):
    return isinstance(value, str) and bool(_ID.fullmatch(value))


def snapshot_path(request_id, base=None):
    if not valid_id(request_id):
        raise ValueError('Invalid voice request ID')
    return os.path.join(base or ROOT, 'voice_ready_{}.json'.format(request_id))


def status_path(request_id, base=None):
    if not valid_id(request_id):
        raise ValueError('Invalid voice request ID')
    return os.path.join(base or ROOT, 'voice_status_{}.json'.format(request_id))


def atomic_json(path, data):
    folder = os.path.dirname(path)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    handle, temp = tempfile.mkstemp(prefix='.voice_', suffix='.tmp', dir=folder)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as out:
            json.dump(data, out, ensure_ascii=False, indent=2)
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


class YHold:
    """Tap on release; hold starts voice exactly once. Unit-testable."""
    def __init__(self, threshold=0.65):
        self.threshold = threshold
        self.started = None
        self.fired = False

    def update(self, now, down, eligible):
        if not eligible:
            self.started, self.fired = None, False
            return None
        if down:
            if self.started is None:
                self.started = now
            elif not self.fired and now - self.started >= self.threshold:
                self.fired = True
                return 'voice'
        else:
            if self.started is not None:
                action = None if self.fired else 'tap'
                self.started, self.fired = None, False
                return action
        return None

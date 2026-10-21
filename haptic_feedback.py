"""Nonblocking event-to-rumble scheduler for the SDL bridge.

Every committed focus switch produces ONE small tick event. Ticks are *queued*,
not thrown away by a cooldown; the focus gate limits unwanted switches.
At extreme event rates hardware pulses can merge. This is a physical SDL/rumble
limitation, not an intentional loss of focus-change events.
"""
import math

# User-tested 8BitDo: previous tick (67-69% * 1.25) felt too forceful.
# Gentle tick ~52-55% effective drive, stronger positive selection feedback.
PROFILES = {
    'tick': ((0.42, 0.44, 48, 0.0),),
    'lock': ((0.66, 0.67, 155, 0.0),),
    'confirm': ((0.72, 0.74, 85, 0.0), (0.72, 0.74, 85, 0.215)),
}
MAX_POWER = 0.95
MIN_SEPARATION_SECONDS = 0.014


def motors(lo, hi, scale=1.0):
    if not all(math.isfinite(float(x)) for x in (lo, hi, scale)):
        return (0, 0)
    return (int(65535 * min(MAX_POWER, max(0.0, lo * scale))),
            int(65535 * min(MAX_POWER, max(0.0, hi * scale))))


class HapticScheduler:
    def __init__(self, strength=1.0, enabled=True):
        self.strength = strength
        self.enabled = enabled
        self.pending = []
        self.available_at = -999.0
        self.last_sent_at = -999.0

    def submit(self, kind, now):
        if not self.enabled or kind not in PROFILES:
            return False
        start = max(now, self.available_at)
        last_end = start
        for low, high, duration, offset in PROFILES[kind]:
            due = start + offset
            self.pending.append((due, low, high, duration))
            last_end = max(last_end, due + duration / 1000.0)
        self.available_at = last_end + MIN_SEPARATION_SECONDS
        return True

    def pump(self, now, send):
        if not self.pending or not self.enabled:
            return False
        # Deliver at most one scheduled pulse per SDL frame; do not send
        # overlapping commands that would truncate each other's vibration.
        if self.pending[0][0] > now:
            return False
        due, lo, hi, duration = self.pending.pop(0)
        self.last_sent_at = now
        low, high = motors(lo, hi, self.strength)
        send(low, high, duration)
        if now > due + .020:
            # A delayed bridge frame must shift subsequent events, not fire all
            # expired pulses immediately on top of each other.
            shift = now - due
            self.pending = [(when + shift, a, b, ms) for when, a, b, ms in self.pending]
            self.available_at += shift
        return True

    def clear(self):
        self.pending.clear()
        self.available_at = -999.0

"""Pure pointer motion for the Rhino gamepad picker (no Rhino dependencies).

Movement is in viewport-local pixels; never alters the OS mouse cursor.
"""
import math

CURSOR_PIXELS_PER_SECOND = 700.0
CURSOR_PRECISION_FACTOR = 0.22
PICK_UPDATE_SECONDS = 0.15


def clamp(value, low, high):
    return max(low, min(high, value))


def advance(x, y, dx, dy, dt, width, height, precision=False):
    """Apply shaped sticks in top-left-origin viewport pixel coordinates."""
    if width <= 1 or height <= 1:
        return (x, y, False)
    dx, dy = float(dx), float(dy)
    if not all(math.isfinite(v) for v in (dx, dy, dt)):
        return (x, y, False)
    dt = clamp(dt, 0.0, 0.05)
    factor = CURSOR_PRECISION_FACTOR if precision else 1.0
    newx = clamp(float(x) + dx * CURSOR_PIXELS_PER_SECOND * factor * dt, 4.0, width - 5.0)
    newy = clamp(float(y) + dy * CURSOR_PIXELS_PER_SECOND * factor * dt, 4.0, height - 5.0)
    return newx, newy, (abs(newx - x) + abs(newy - y) > 0.005)


def normalized_position(x, y, width, height):
    if width <= 0 or height <= 0:
        return (0.5, 0.5)
    return clamp(x / width, 0., 1.), clamp(y / height, 0., 1.)

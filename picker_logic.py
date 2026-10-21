"""Portable math and protocol helpers for the Rhino gamepad Look & Select mode.

This module has no Rhino imports. Unit tests run in regular Python.
"""

import math

PICK_MODES = ("all", "faces", "curves")


def limit(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def next_mode(current):
    return PICK_MODES[(PICK_MODES.index(current) + 1) % len(PICK_MODES)]


def next_index(current, count, direction):
    if count <= 0:
        return 0
    return (current + direction) % count


def segment_distance(px, py, ax, ay, bx, by):
    """Pixel distance and parameter along a projected segment."""
    vx, vy = bx - ax, by - ay
    denom = vx * vx + vy * vy
    t = 0.0 if denom < 1e-12 else limit(((px - ax) * vx + (py - ay) * vy) / denom, 0.0, 1.0)
    return math.hypot(px - (ax + t * vx), py - (ay + t * vy)), t


def is_action(old, new, key):
    """Monotonic press counters: no repeats for a held button."""
    return old is not None and int(new.get(key, 0)) > int(old.get(key, 0))


def selection_label(candidate):
    name = candidate.get("name") or "unnamed"
    kind = candidate.get("kind") or "object"
    index = candidate.get("component_index")
    if index is not None:
        kind = "{} {}".format(kind, index + 1)
    return "{}: {}".format(kind, name)


def candidate_sort_key(candidate):
    # Direct face/mesh hits at cursor first, then near-screen curves; front to back.
    return (round(float(candidate["pixel_distance"]), 2), float(candidate["depth"]),
            str(candidate["object_id"]), int(candidate.get("component_index") or 0))

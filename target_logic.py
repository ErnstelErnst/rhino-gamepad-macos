"""Pure helpers for conservative soft targeting (no Rhino dependencies).

Only keep a prior hover when it is STILL present in a new authoritative
pick result. Never silently retain an off-cursor hit as an actionable hover.
An explicit lock, tracked by NativePicker, is the only persistent target.
"""


def target_key(entry):
    if not isinstance(entry, dict):
        return None
    return (str(entry.get('id')), str(entry.get('kind')), int(entry.get('index', -1)))


def preferred_index(entries, previous):
    key = target_key(previous)
    if key is not None:
        for index, entry in enumerate(entries):
            if target_key(entry) == key:
                return index
    return 0


def can_refresh(now, last_pick, last_camera_motion, interval=0.15, settle=0.18):
    """Avoid synchronous picking while camera motion is ongoing.

    Explicit button actions may override this gate to get a fresh exact hit.
    """
    return now - last_pick >= interval and now - last_camera_motion >= settle

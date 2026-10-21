"""Pure helpers for experimental screen-space magnetic selection (no Rhino APIs).

Screen direction is relative to the *view*, not model coordinates. Every pick
is still authoritative native Rhino picking; no synthetic geometry is created.
"""
import math

GLIDE_PX_PER_SECOND = 2400.0
PRECISION_SCALE = 0.25
SCAN_INTERVAL = 0.033     # Target cadence; expensive native picking may run slower
MAGNETIC_PICK_HALF_PX = 64  # larger than the manual cursor's 16 px
HYSTERESIS_PX = 18.0
DEPTH_GAP_FRACTION = 0.55
# Adaptive path sampling reduces missed thin parts at fast stick speed.
# Bounded at two native pick positions per scan to limit UI work.
SWEEP_SPACING_PX = 48.0
SWEEP_MAX_SAMPLES = 2
SLOW_PICK_SECONDS = 0.045  # degrade to one probe if native picking is expensive


def key(entry):
    if not isinstance(entry, dict):
        return None
    return (str(entry.get('id')), str(entry.get('kind')), int(entry.get('index', -1)))


def advance(x, y, dx, dy, dt, width, height, precision=False):
    """Integrate screen-space velocity; do not create a visible OS cursor."""
    if width < 10 or height < 10:
        return x, y, False
    try:
        dx, dy, dt = float(dx), float(dy), float(dt)
        if not all(math.isfinite(v) for v in (dx, dy, dt)):
            return x, y, False
        dt = min(0.05, max(0.0, dt))
        scale = PRECISION_SCALE if precision else 1.0
        xx = min(width - 5., max(4., x + dx * dt * GLIDE_PX_PER_SECOND * scale))
        yy = min(height - 5., max(4., y + dy * dt * GLIDE_PX_PER_SECOND * scale))
        return xx, yy, abs(xx-x) + abs(yy-y) >= 0.05
    except (TypeError, ValueError, OverflowError):
        return x, y, False


def choose(hits, previous, anchor, probe, direction, camera_radius, force=False):
    """Choose a visible native hit by screen direction, proximity and depth.

    Geometry screen extents and depth are approximate; the probe is exact
    screen space. Native PickObjects still decides the actual hit set. A
    shallow crossing box is used to bias nearby elements over distant ones.
    """
    if not hits:
        return None
    old_key = key(previous)
    traveled_x, traveled_y = probe[0] - anchor[0], probe[1] - anchor[1]
    moved = math.hypot(traveled_x, traveled_y)
    if not force and moved < HYSTERESIS_PX:
        for hit in hits:
            if key(hit) == old_key:
                return hit
    # Depth is a tie breaker, NOT a hard occlusion test (Ghosted exposes deeper faces).
    filtered = list(hits)
    if not filtered:
        return None
    if moved < HYSTERESIS_PX * 1.6:
        for hit in filtered:
            if key(hit) == old_key:
                return hit

    dx, dy = direction
    directional = math.hypot(dx, dy)
    if directional > 0.05:
        ux, uy = dx/directional, dy/directional
    elif moved >= 0.5:
        ux, uy = traveled_x / moved, traveled_y / moved
    else:
        ux, uy = 0., 0.
    ranked = []
    for hit in filtered:
        sx, sy = hit.get('screen_x', probe[0]), hit.get('screen_y', probe[1])
        vx, vy = sx - anchor[0], sy - anchor[1]
        dist = math.hypot(vx, vy)
        forward = vx * ux + vy * uy
        sideways = abs(vx * uy - vy * ux)
        if not force and directional > 0.05 and forward < -8.0:
            continue
        # Prefer close screen-space candidates in the requested direction;
        # use depth only as a gate and tie-breaker. No model-unit favoritism.
        # Soft depth preference: do not reject deeper objects (Ghosted often
        # shows them), but avoid favoring a very distant hit over an almost
        # equally close foreground candidate.
        prior_depth = previous.get('depth') if previous else None
        hit_depth = hit.get('depth')
        depth_penalty = 0.0
        if prior_depth is not None and hit_depth is not None:
            depth_penalty = min(18.0, max(0.0, float(hit_depth) - float(prior_depth)) /
                                max(1.0, camera_radius) * 4.0)
        score = (max(0.0, forward) + 1.35 * sideways +
                 0.5 * max(0.0, -forward) + depth_penalty,
                 1 if hit.get('approx') else 0,
                 float(hit.get('depth')) if hit.get('depth') is not None else float('inf'),
                 str(key(hit)))
        ranked.append((score, hit))
    return min(ranked, key=lambda item: item[0])[1] if ranked else None


def should_tick(old_entry, new_entry):
    return new_entry is not None and key(old_entry) != key(new_entry)


def sweep_positions(start, end, spacing=SWEEP_SPACING_PX, max_samples=SWEEP_MAX_SAMPLES):
    """Viewport-local picks, ordered in direction of travel; always include end.

    Sampling two places per scan cannot guarantee that every tiny/occluded
    object is discovered, but reduces tunneling without model-wide scanning.
    """
    x0, y0 = map(float, start)
    x1, y1 = map(float, end)
    length = math.hypot(x1-x0, y1-y0)
    count = min(max(1, int(max_samples)), max(1, int(math.ceil(length / max(1., float(spacing))))))
    return [(x0 + (x1-x0)*i/count, y0+(y1-y0)*i/count)
            for i in range(1, count+1)]


def choose_swept(banks, previous, anchor, direction, camera_radius, force=False):
    """Find first NEW hit along travel, not the last hit that happened to be sampled.

    Each bank is (sample_position, native_candidates) in travel order.
    The previous hit is still available as the fallback when no new visible
    candidate can be found. Does not fabricate new geometry targets.
    """
    prev_key = key(previous)
    retained = None
    if previous is not None and not force and banks:
        # Tiny stick noise cannot switch away from a still-detected target.
        d = math.hypot(banks[-1][0][0] - anchor[0],
                       banks[-1][0][1] - anchor[1])
        if d < HYSTERESIS_PX:
            for _, hits in banks:
                for hit in hits:
                    if key(hit) == prev_key:
                        return hit, banks[-1][0]
    for position, hits in banks:
        if prev_key is not None:
            retained = next((h for h in hits if key(h) == prev_key), retained)
        other_hits = [h for h in hits if key(h) != prev_key]
        if other_hits:
            selected = choose(other_hits, previous, anchor, position,
                              direction, camera_radius, force)
            if selected is not None:
                return selected, position
    if retained is not None:
        return retained, banks[-1][0]
    return None, banks[-1][0] if banks else anchor


def scan_sample_budget(last_cost_seconds):
    """Keep a slow Rhino viewport responsive over maximal sweep coverage."""
    return 1 if last_cost_seconds > SLOW_PICK_SECONDS else SWEEP_MAX_SAMPLES


# Candidate focus changes are deliberately slower than cursor movement. This
# rejects alternating hit results from an inflated crossing pick area while
# preserving fast, continuous traversal through genuine nearby elements.
FOCUS_MIN_DWELL_SECONDS = 0.075
FOCUS_MIN_FORWARD_PX = 9.0
FOCUS_IMMEDIATE_PROGRESS_PX = 85.0
FOCUS_MAX_SIDEWAYS_PX = 50.0


class FocusGate:
    """Stateful, screen-direction-consistent focus transition gate.

    Hits are only *proposals*. A new target is committed when it is clearly in
    the current stick direction, a brief pause between commits has passed,
    and either it was independently observed twice or is far enough ahead to
    justify immediate traversal. No haptics are generated for rejected hits.
    """
    def __init__(self):
        self.last_change_at = -999.0
        self.pending_key = None
        self.pending_count = 0

    def reset(self):
        self.last_change_at = -999.0
        self.pending_key = None
        self.pending_count = 0

    def forget_candidate(self):
        self.pending_key = None
        self.pending_count = 0

    def accept(self, previous, proposed, anchor, direction, now, force=False):
        if proposed is None:
            self.forget_candidate()
            return False
        old_key = key(previous)
        new_key = key(proposed)
        if old_key == new_key:
            self.forget_candidate()
            return True
        if previous is None or force:
            self.last_change_at = now
            self.forget_candidate()
            return True
        if now - self.last_change_at < FOCUS_MIN_DWELL_SECONDS:
            return False
        try:
            dx, dy = map(float, direction)
            mag = math.hypot(dx, dy)
            if mag > 0.10:
                dx, dy = dx / mag, dy / mag
                vx = float(proposed.get('screen_x', anchor[0])) - anchor[0]
                vy = float(proposed.get('screen_y', anchor[1])) - anchor[1]
                forward = vx * dx + vy * dy
                sideways = abs(vx * dy - vy * dx)
                if forward < FOCUS_MIN_FORWARD_PX:
                    self.forget_candidate()
                    return False
                if sideways > max(FOCUS_MAX_SIDEWAYS_PX, forward * 1.35):
                    self.forget_candidate()
                    return False
            else:
                # Stick neutral: do not silently traverse focus (unless forced).
                self.forget_candidate()
                return False
        except (TypeError, ValueError, OverflowError):
            self.forget_candidate()
            return False
        if new_key == self.pending_key:
            self.pending_count += 1
        else:
            self.pending_key, self.pending_count = new_key, 1
        if self.pending_count < 2 and forward < FOCUS_IMMEDIATE_PROGRESS_PX:
            return False
        self.last_change_at = now
        self.forget_candidate()
        return True

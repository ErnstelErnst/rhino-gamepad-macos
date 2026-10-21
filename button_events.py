"""Controller button event reconciliation without Rhino / SDL dependencies.

The bridge's cumulative `presses` is the primary source: a fast tap may occur
entirely between Rhino Idle callbacks. The `buttons` level adds a *rising-edge*
fallback when no increment is observed. A held level is NEVER an action every
idle frame; a late counter increment for the same hold is suppressed.
"""


class ButtonEvents:
    def __init__(self):
        self.reset()

    def reset(self):
        self.previous_counts = None
        self.previous_levels = None
        self.raw_fallback_pending = set()

    def consume(self, counts, levels, eligible=True):
        """Return unique newly-pressed buttons; always update baselines.

        eligible=False discards actions for invalid contexts (e.g. Rhino running
        commands) rather than replaying them after the context changes.
        """
        if not isinstance(counts, dict) or not isinstance(levels, dict):
            self.reset()
            return set()
        try:
            current_counts = {str(k): int(v) for k, v in counts.items()}
        except (ValueError, TypeError):
            self.reset()
            return set()
        current_levels = {str(k): bool(v) for k, v in levels.items()}
        if self.previous_counts is None or self.previous_levels is None:
            self.previous_counts = current_counts
            self.previous_levels = current_levels
            return set()

        events = set()
        keys = set(current_counts) | set(self.previous_counts) | set(current_levels) | set(self.previous_levels)
        for key in keys:
            was_down = self.previous_levels.get(key, False)
            down = current_levels.get(key, False)
            before = self.previous_counts.get(key, 0)
            after = current_counts.get(key, 0)
            delta = after - before
            rising = down and not was_down

            if delta > 0:
                # A counter that catches up to an already-observed rising edge
                # is not an additional physical press.
                if key in self.raw_fallback_pending:
                    self.raw_fallback_pending.discard(key)
                else:
                    events.add(key)
            elif rising:
                events.add(key)
                self.raw_fallback_pending.add(key)

            if not down:
                self.raw_fallback_pending.discard(key)

        self.previous_counts = current_counts
        self.previous_levels = current_levels
        return events if eligible else set()

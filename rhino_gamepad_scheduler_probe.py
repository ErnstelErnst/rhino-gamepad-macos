"""Rhino Gamepad NAVIGATION PROFILER (non-invasive, v0.5.4).

Run as a Python 3 script in Rhino 8 ScriptEditor AFTER enabling the existing
Rhino Gamepad listener. Does not touch bridge configuration or model geometry.
Wraps 3 instance methods for 12 seconds and restores them afterwards.
Run again before timeout to stop early and generate the report.

Caveat: measures camera update/Redraw request timing, NOT GPU-present FPS.
"""
import os
import statistics
import time

LISTENER_KEY = "cad_gamepad_mac_rhino_v01"
PROBE_KEY = "rhino_gamepad_navigation_probe_v01"
SECONDS = 12.0
MAX_SAMPLES = 10000


def rate_from_timestamps(values):
    if len(values) < 2:
        return 0.0
    span = values[-1] - values[0]
    return (len(values) - 1) / span if span > 0 else 0.0


def intervals_ms(values):
    return [1000.0 * (b - a) for a, b in zip(values, values[1:])]


def percentile(values, pct):
    if not values:
        return 0.0
    ordered = sorted(values)
    at = (len(ordered) - 1) * (pct / 100.0)
    low = int(at)
    high = min(low + 1, len(ordered) - 1)
    blend = at - low
    return ordered[low] * (1 - blend) + ordered[high] * blend


def timing_summary(name, timestamps):
    values = intervals_ms(timestamps)
    if not values:
        return '{}: insufficient samples'.format(name)
    return ('{}: {:.1f} Hz, intervals median {:.1f} ms, p95 {:.1f} ms, '
            'max {:.1f} ms; >33ms: {} of {}').format(
        name, rate_from_timestamps(timestamps), percentile(values, 50),
        percentile(values, 95), max(values), sum(v > 33.0 for v in values), len(values))


class NavigationProbe(object):
    def __init__(self, controller, output_dir, seconds=SECONDS, clock=None):
        self.controller = controller
        self.output_dir = output_dir
        self.seconds = seconds
        self.clock = clock or time.perf_counter
        self.start_at = None
        self.deadline = None
        self.is_running = False
        self.idle_times = []
        self.processed_times = []
        self.packet_times = []
        self.changed_times = []
        self.move_times_ms = []
        self.update_times_ms = []
        self.sequences_skipped = 0
        self.seq_deltas = []
        self.last_seq = None
        self.last_session = None
        self.camera_calls = 0
        self.camera_changed = 0
        self.originals = {}
        self.wrappers = {}
        self.latest_report = ""

    def _record(self, collection, value):
        if len(collection) < MAX_SAMPLES:
            collection.append(value)

    def start(self):
        if self.is_running:
            raise RuntimeError('Profiler already active.')
        c = self.controller
        for method in ('read_latest', 'move_camera', 'update'):
            fn = getattr(c, method, None)
            if not callable(fn):
                raise RuntimeError('Controller lacks {} method; unsupported version.'.format(method))
            self.originals[method] = fn
        self.start_at = self.clock()
        self.deadline = self.start_at + self.seconds

        def read_latest_wrapper(*args, **kwargs):
            packet = self.originals['read_latest'](*args, **kwargs)
            if isinstance(packet, dict):
                t = self.clock()
                self._record(self.packet_times, t)
                session = packet.get('session')
                seq = packet.get('seq')
                if session != self.last_session:
                    self.last_session = session
                    self.last_seq = None
                if isinstance(seq, int):
                    if self.last_seq is not None and seq > self.last_seq:
                        delta = seq - self.last_seq
                        self._record(self.seq_deltas, delta)
                        self.sequences_skipped += max(0, delta - 1)
                    self.last_seq = seq
            return packet

        def move_camera_wrapper(*args, **kwargs):
            before = self.clock()
            try:
                changed = self.originals['move_camera'](*args, **kwargs)
                return changed
            finally:
                after = self.clock()
                self.camera_calls += 1
                self._record(self.move_times_ms, 1000.0 * (after - before))
                # The real function returns 'changed'; no need to touch the view.
                if 'changed' in locals() and changed:
                    self.camera_changed += 1
                    self._record(self.changed_times, after)

        def update_wrapper(*args, **kwargs):
            before = self.clock()
            self._record(self.idle_times, before)
            tick_before = getattr(self.controller, 'last_tick', None)
            try:
                return self.originals['update'](*args, **kwargs)
            finally:
                after = self.clock()
                self._record(self.update_times_ms, 1000.0 * (after - before))
                if getattr(self.controller, 'last_tick', None) != tick_before:
                    self._record(self.processed_times, after)
                if after >= self.deadline:
                    self.stop()

        self.wrappers = {'read_latest': read_latest_wrapper, 'move_camera': move_camera_wrapper,
                         'update': update_wrapper}
        try:
            for name, wrapper in self.wrappers.items():
                setattr(c, name, wrapper)
            self.is_running = True
        except Exception:
            self._restore()
            raise

    def _restore(self):
        # Restore ONLY wrappers belonging to this profiler instance. If the
        # listener was upgraded while testing, do not touch the new listener.
        for name, old in self.originals.items():
            try:
                if getattr(self.controller, name, None) is self.wrappers.get(name):
                    setattr(self.controller, name, old)
            except Exception:
                pass

    def stop(self):
        if not self.is_running:
            return self.latest_report
        self.is_running = False
        self._restore()
        self.latest_report = self.report()
        try:
            import Rhino
            for line in self.latest_report.splitlines():
                Rhino.RhinoApp.WriteLine(line)
        except Exception:
            print(self.latest_report)
        try:
            os.makedirs(self.output_dir, exist_ok=True)
            filename = 'rhino_gamepad_nav_perf_{}.txt'.format(time.strftime('%Y%m%d_%H%M%S'))
            path = os.path.join(self.output_dir, filename)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self.latest_report + '\n')
            try:
                import Rhino
                Rhino.RhinoApp.WriteLine('Profiler saved report: ' + path)
            except Exception:
                print('Profiler saved report: ' + path)
        except OSError as e:
            try:
                import Rhino
                Rhino.RhinoApp.WriteLine('Unable to save report: ' + str(e))
            except Exception:
                pass
        return self.latest_report

    def report(self):
        run_seconds = (self.clock() - self.start_at) if self.start_at is not None else 0
        lines = ['=== Rhino Gamepad navigation timing report ===',
                 'Duration: {:.1f} s; selection should be OFF; hold right stick throughout.'.format(run_seconds),
                 'WARNING: Rates below are Python camera update/Redraw request rates, NOT measured render FPS.',
                 timing_summary('Scheduler callbacks', self.idle_times),
                 timing_summary('Processed updates (10ms throttle)', self.processed_times),
                 timing_summary('Latest UDP packets accepted', self.packet_times),
                 'Observed UDP seq gaps/coalesced packets: {}; mean seq step: {:.1f}'.format(
                     self.sequences_skipped, statistics.mean(self.seq_deltas) if self.seq_deltas else 0.0),
                 'Camera calls: {}; camera changed: {}'.format(self.camera_calls, self.camera_changed),
                 timing_summary('Camera changed + redraw requested', self.changed_times)]
        if self.move_times_ms:
            lines.append('Camera method (includes Redraw call, not GPU present): median {:.2f} ms, p95 {:.2f} ms, max {:.2f} ms'.format(
                percentile(self.move_times_ms, 50), percentile(self.move_times_ms, 95), max(self.move_times_ms)))
        if self.update_times_ms:
            lines.append('Complete update() overhead: median {:.2f} ms, p95 {:.2f} ms'.format(
                percentile(self.update_times_ms, 50), percentile(self.update_times_ms, 95)))
        lines.extend([
            'Interpretation:',
            '* With Eto selected, ~50-60 Hz camera updates suggests timer improved the tested bottleneck.',
            '* ~60 Hz changed-camera requests but still jerky => viewport rendering/present pacing needs separate measurement.',
            '* Lots of UDP seq gaps with low scheduler frequency => packets are being coalesced while Rhino is busy.',
            '* Camera method p95 >16 ms => synchronous camera work/Redraw may be contributing.',
            '* If no camera changes recorded, ensure Rhino Perspective is frontmost and right stick is held.'
        ])
        return '\n'.join(lines)


def main():
    import Rhino
    import scriptcontext as sc
    prior = sc.sticky.get(PROBE_KEY)
    if prior is not None and getattr(prior, 'is_running', False):
        prior.stop()
        sc.sticky.pop(PROBE_KEY, None)
        Rhino.RhinoApp.WriteLine('Navigation profiler stopped early.')
        return
    controller = sc.sticky.get(LISTENER_KEY)
    if controller is None or not getattr(controller, 'running', False):
        Rhino.RhinoApp.WriteLine('No running gamepad listener. Start v0.5.4 Rhino listener first.')
        return
    output_dir = os.path.expanduser('~/Documents/RhinoGamepad')
    probe = NavigationProbe(controller, output_dir)
    probe.start()
    sc.sticky[PROBE_KEY] = probe
    Rhino.RhinoApp.WriteLine('Navigation profiler running for 12s. Click Perspective viewport, keep RB selection OFF, hold right stick steadily. Results print automatically.')


if __name__ == '__main__':
    main()

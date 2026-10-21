#!/usr/bin/env python3
"""Read SDL2 controller inputs on macOS for Rhino v0.5.3 + voice agent handoff.

This process runs OUTSIDE Rhino.  No keyboard/mouse injection is used.
Only one controller index is selected, but other applications may still receive
raw HID input; SDL does not provide exclusive ownership of a controller.
"""

import argparse
import ctypes
import ctypes.util
import fcntl
import collections
import json
import os
import signal
import socket
import subprocess
import sys
import time
import uuid
import bridge_protocol
import haptic_feedback
import voice_protocol

HOST = "127.0.0.1"
PORT = 47881
HAPTIC_PORT = 47882
BRIDGE_TAG = bridge_protocol.BRIDGE_TAG  # ignore orphaned older bridges
SDL_INIT_GAMECONTROLLER = 0x2000
AXES = {"lx": 0, "ly": 1, "rx": 2, "ry": 3, "lt": 4, "rt": 5}
BUTTONS = {
    "a": 0, "b": 1, "x": 2, "y": 3, "back": 4, "start": 6,
    "l3": 7, "r3": 8,  # SDL2 left/right stick CLICK, not a directional axis
    "lb": 9, "rb": 10, "dup": 11, "ddown": 12,
    "dleft": 13, "dright": 14,
    "paddle1": 16, "paddle2": 17,  # optional SDL2 mappings; may be unavailable
}
DIRECTIONS = {"dup": "north", "ddown": "south", "dleft": "west", "dright": "east"}


def get_sdl2():
    paths = [
        os.getenv("SDL2_LIBRARY", ""),
        ctypes.util.find_library("SDL2"),
        "/opt/homebrew/lib/libSDL2-2.0.0.dylib",
        "/opt/homebrew/lib/libSDL2.dylib",
        "/usr/local/lib/libSDL2-2.0.0.dylib",
        "/usr/local/lib/libSDL2.dylib",
    ]
    for path in paths:
        if path:
            try:
                return ctypes.CDLL(path)
            except OSError:
                pass
    raise RuntimeError("SDL2 shared library not found; install with: brew install sdl2")


def bind_api(sdl):
    api = {
        "SDL_InitSubSystem": (ctypes.c_int, [ctypes.c_uint32]),
        "SDL_QuitSubSystem": (None, [ctypes.c_uint32]),
        "SDL_NumJoysticks": (ctypes.c_int, []),
        "SDL_PumpEvents": (None, []),
        "SDL_IsGameController": (ctypes.c_int, [ctypes.c_int]),
        "SDL_GameControllerOpen": (ctypes.c_void_p, [ctypes.c_int]),
        "SDL_GameControllerClose": (None, [ctypes.c_void_p]),
        "SDL_GameControllerGetAttached": (ctypes.c_int, [ctypes.c_void_p]),
        "SDL_GameControllerUpdate": (None, []),
        "SDL_GameControllerGetAxis": (ctypes.c_int16, [ctypes.c_void_p, ctypes.c_int]),
        "SDL_GameControllerGetButton": (ctypes.c_uint8, [ctypes.c_void_p, ctypes.c_int]),
        "SDL_GameControllerName": (ctypes.c_char_p, [ctypes.c_void_p]),
        "SDL_GameControllerNameForIndex": (ctypes.c_char_p, [ctypes.c_int]),
        "SDL_JoystickNameForIndex": (ctypes.c_char_p, [ctypes.c_int]),
        "SDL_GetError": (ctypes.c_char_p, []),
    }
    for name, (restype, argtypes) in api.items():
        fn = getattr(sdl, name)
        fn.restype, fn.argtypes = restype, argtypes
    # Optional SDL2 >= 2.0.9 rumble; navigation works without it.
    fn = getattr(sdl, 'SDL_GameControllerRumble', None)
    if fn is not None:
        fn.restype = ctypes.c_int
        fn.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_uint16, ctypes.c_uint32]


def list_devices(sdl):
    sdl.SDL_PumpEvents()
    sdl.SDL_GameControllerUpdate()
    devices = []
    for i in range(max(0, sdl.SDL_NumJoysticks())):
        if sdl.SDL_IsGameController(i):
            raw = sdl.SDL_GameControllerNameForIndex(i)
            devices.append((i, raw.decode(errors="replace") if raw else "Unnamed gamepad"))
    return devices


def list_all_devices(sdl):
    """Includes raw joysticks not yet mapped as SDL GameControllers."""
    sdl.SDL_PumpEvents()
    entries = []
    for i in range(max(0, sdl.SDL_NumJoysticks())):
        raw = sdl.SDL_JoystickNameForIndex(i)
        name = raw.decode(errors='replace') if raw else 'Unnamed device'
        entries.append((i, name, bool(sdl.SDL_IsGameController(i))))
    return entries


def open_controller(sdl, preferred=-1):
    available = list_devices(sdl)
    for idx, name in available:
        if preferred >= 0 and idx != preferred:
            continue
        handle = sdl.SDL_GameControllerOpen(idx)
        if handle:
            print("Using gamepad SDL index {}: {}".format(idx, name), flush=True)
            return handle
    return None


def snapshot(sdl, device):
    sdl.SDL_PumpEvents()
    sdl.SDL_GameControllerUpdate()
    if not device:
        return ({key: 0.0 for key in AXES}, {key: False for key in BUTTONS})
    values = {}
    for key, idx in AXES.items():
        raw = int(sdl.SDL_GameControllerGetAxis(device, idx))
        values[key] = max(0.0, min(1.0, raw / 32767.0)) if key in ("lt", "rt") else max(-1.0, min(1.0, raw / 32767.0))
    buttons = {key: bool(sdl.SDL_GameControllerGetButton(device, idx)) for key, idx in BUTTONS.items()}
    return values, buttons


def is_rhino(name):
    lower = name.lower()
    return lower.startswith("rhino") or "rhinoceros" in lower


def choose_mode(connected, buttons, foreground):
    """Physical View/Select button has priority over Rhino camera movement."""
    if not connected:
        return "inactive"
    if buttons.get("back"):
        return "desktop"
    if is_rhino(foreground):
        return "rhino"
    return "inactive"


class ForegroundDetector:
    """Use AppKit when available; otherwise use a throttled AppleScript lookup.

    If either lookup fails or returns an empty name, fail closed: NEVER assume
    Rhino is active.  Queries are cached to avoid launching osascript at 60 Hz.
    The cache means background transitions can take up to one check interval
    to take effect; that limitation is documented, not a security guarantee.
    """

    SCRIPT = ('tell application "System Events" to return name of first '
              'application process whose frontmost is true')

    def __init__(self, interval_seconds=0.25, run_command=None, workspace=None, autoload=True):
        self.run_command = run_command or subprocess.run
        self.workspace = workspace
        if workspace is None and autoload:
            try:
                from AppKit import NSWorkspace
                self.workspace = NSWorkspace.sharedWorkspace()
            except Exception:
                self.workspace = None
        self.provider = "PyObjC" if self.workspace is not None else "osascript"
        self.interval = interval_seconds
        self.next_check = -1.0
        self.cached_name = ""
        self.last_error = ""

    def lookup(self):
        if self.workspace is not None:
            try:
                app = self.workspace.frontmostApplication()
                name = str(app.localizedName()) if app else ""
                return name.strip(), ""
            except Exception as exc:
                # Fail closed.  The next check will retry AppKit.
                return "", "AppKit: " + str(exc)
        try:
            proc = self.run_command(
                ["osascript", "-e", self.SCRIPT],
                capture_output=True, text=True, timeout=0.8, check=False)
            if proc.returncode == 0:
                return (proc.stdout or "").strip(), ""
            return "", "osascript: " + (proc.stderr or "error").strip()[:160]
        except (OSError, subprocess.TimeoutExpired) as exc:
            return "", "osascript: " + str(exc)

    def current(self, now):
        if now >= self.next_check:
            # When PyObjC works, check more frequently without shelling out.
            cadence = min(self.interval, 0.10) if self.workspace is not None else self.interval
            self.cached_name, self.last_error = self.lookup()
            # A slow AppleScript invocation must not cause back-to-back retries.
            self.next_check = max(now, time.monotonic()) + cadence
        return self.cached_name


CAMERA_NEUTRAL_THRESHOLD = 0.18
TRIGGER_NEUTRAL_THRESHOLD = 0.14


def controls_neutral(axes, buttons):
    """Return true only after release of controls relevant to camera movement.

    Requiring all buttons to be up prevents an action pressed during a desktop
    context from accidentally firing in Rhino on re-entry.
    """
    try:
        return (all(abs(float(axes.get(k, 0.0))) < CAMERA_NEUTRAL_THRESHOLD
                    for k in ("lx", "ly", "rx", "ry"))
                and all(float(axes.get(k, 0.0)) < TRIGGER_NEUTRAL_THRESHOLD
                        for k in ("lt", "rt"))
                and not any(buttons.values()))
    except (TypeError, ValueError, AttributeError):
        return False


class CameraArmingGate:
    """Re-arm camera only after neutral controls on initial focus/re-entry.

    The neutral frame is deliberately suppressed. This avoids immediate
    movement from sticks still held while switching out of desktop mode.
    """
    def __init__(self):
        self.armed = False

    def allow(self, requested_mode, axes, buttons):
        if requested_mode != "rhino":
            self.armed = False
            return False
        if not self.armed:
            if controls_neutral(axes, buttons):
                self.armed = True
            return False
        return True


def run_yabai(direction, action):
    command = ["yabai", "-m", "window", "--focus" if action == "focus" else "--swap", direction]
    try:
        proc = subprocess.run(command, capture_output=True, timeout=1.5, check=False)
        if proc.returncode:
            print("yabai failed:", proc.stderr.decode(errors="replace").strip(), flush=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print("yabai unavailable:", exc, flush=True)


def diag_loop(sdl, device_index):
    print("SDL-mapped gamepads:", list_devices(sdl), flush=True)
    handle = open_controller(sdl, device_index)
    if not handle:
        print("No mapped gamepad at requested index; check macOS Game Controllers and SDL mappings.")
        return 2
    try:
        print("Move sticks, press triggers and buttons. Ctrl+C stops.\n")
        while sdl.SDL_GameControllerGetAttached(handle):
            axes, buttons = snapshot(sdl, handle)
            pressed = [name for name, down in buttons.items() if down]
            print("AXES {}  BUTTONS {}".format(
                " ".join("{}:{:+.2f}".format(k, v) for k, v in axes.items()),
                ",".join(pressed) or "-"), flush=True)
            time.sleep(0.25)
        print("Controller disconnected.")
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        sdl.SDL_GameControllerClose(handle)


class BridgeSingleInstance:
    """Advisory lock shared by v0.4+ bridges only; no PID-based killing.

    Earlier v0.2-v0.3.2 scripts never acquired this lock. Stop those manually.
    """
    def __init__(self, path=None):
        self.path = path or os.path.join(os.path.expanduser('~'), 'Library', 'Caches',
                                        'RhinoGamepad', 'bridge_47881.lock')
        self.handle = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.handle = open(self.path, 'a+')
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError):
            self.handle.close()
            self.handle = None
            raise RuntimeError('Another v0.4+ bridge already owns the lock: {}'.format(self.path))
        self.handle.seek(0)
        self.handle.truncate()
        self.handle.write(str(os.getpid()) + '\n')
        self.handle.flush()
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.handle is not None:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()
            self.handle = None


def rate_diagnostic(sdl, device_index, seconds):
    """Measure HOST-side SDL reads and axis variability, not RF polling rate."""
    device = open_controller(sdl, device_index)
    if not device:
        print('No SDL-mapped controller found. Check --diagnose and dongle mode.')
        return 2
    print('Capture: {:.1f}s, requested 250 host reads/sec. Move the stick steadily.'.format(seconds), flush=True)
    samples = 0
    differences = 0
    axis_unique = set()
    previous = None
    started = time.monotonic()
    next_read = started
    try:
        while time.monotonic() - started < seconds:
            axes, _ = snapshot(sdl, device)
            lx = axes['lx']
            axis_unique.add(round(lx, 5))
            if previous is not None and abs(lx - previous) >= .00001:
                differences += 1
            previous = lx
            samples += 1
            next_read += .004
            pause = next_read - time.monotonic()
            if pause > 0:
                time.sleep(pause)
            else:
                next_read = time.monotonic()
        duration = time.monotonic() - started
        print('Host capture rate: {:.1f} reads/s; left-stick x values: {} unique / {} changes'.format(
            samples / duration, len(axis_unique), differences), flush=True)
        print('This does NOT measure RF polling rate or prove 2.4 GHz vs Bluetooth. '
              'Compare the same movement in both modes; use --device-index if duplicated.', flush=True)
        return 0
    finally:
        sdl.SDL_GameControllerClose(device)


def run(args, sdl):
    detector = ForegroundDetector(interval_seconds=args.focus_check_ms / 1000.0)
    gate = CameraArmingGate()
    print("Foreground lookup: {}. Unknown focus disables camera input."
          .format(detector.provider), flush=True)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rumble_fn = getattr(sdl, 'SDL_GameControllerRumble', None)
    haptics = haptic_feedback.HapticScheduler(args.haptic_strength,
                                               enabled=not args.no_haptics and rumble_fn is not None)
    haptic_sock = None
    if haptics.enabled:
        try:
            haptic_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            haptic_sock.bind((HOST, HAPTIC_PORT))
            haptic_sock.setblocking(False)
        except OSError as exc:
            print('Haptic channel unavailable (camera unaffected):', exc, flush=True)
            if haptic_sock:
                haptic_sock.close()
            haptic_sock = None
            haptics.enabled = False
    session = uuid.uuid4().hex
    seq = 0
    device = None
    last_scan = -9999.0
    last_mode = None
    previous_dirs = set()
    previous_buttons = {key: False for key in BUTTONS}
    rhino_presses = {key: 0 for key in BUTTONS}
    rhino_presses['voice'] = 0
    y_hold = voice_protocol.YHold()
    voice_id = None
    voice_phase = 'idle'
    voice_started_at = 0.0
    last_voice_check = 0.0
    voice_done_at = 0.0
    voice_rearm = False
    voice_worker = None
    voice_directory = os.path.dirname(os.path.abspath(__file__))
    interval = 1.0 / args.hz
    next_frame = time.monotonic()
    print("Started. Desktop backend: {} (default none). Ctrl+C to exit.".format(args.desktop_backend), flush=True)
    try:
        while True:
            sdl.SDL_PumpEvents()
            now = time.monotonic()
            if device and not sdl.SDL_GameControllerGetAttached(device):
                sdl.SDL_GameControllerClose(device)
                device = None
                previous_buttons = {key: False for key in BUTTONS}
                previous_dirs = set()
                y_hold.update(now, False, False)
                haptics.clear()
                print("Disconnected; input cleared.", flush=True)
            if device is None and now - last_scan >= 1.0:
                last_scan = now
                device = open_controller(sdl, args.device_index)
                if device is None and args.verbose:
                    print("No mapped gamepad; SDL sees:", list_devices(sdl), flush=True)
            axes, buttons = snapshot(sdl, device)
            foreground = detector.current(time.monotonic())
            requested_mode = choose_mode(bool(device), buttons, foreground)
            camera_armed = gate.allow(requested_mode, axes, buttons)
            mode = ("waiting_neutral" if requested_mode == "rhino" and not camera_armed
                    else requested_mode)
            if mode != last_mode:
                print("Mode: {}  frontmost: {}".format(mode, foreground or "unknown"), flush=True)
            if args.verbose and detector.last_error and mode != last_mode:
                print("Foreground lookup warning:", detector.last_error, flush=True)

            # Receive small known haptic events from Rhino's local UDP input
            # socket (source 127.0.0.1:47881) matching this bridge session.
            if haptic_sock is not None:
                for _ in range(12):
                    try:
                        blob, src = haptic_sock.recvfrom(512)
                    except BlockingIOError:
                        break
                    if src != (HOST, PORT) or mode != 'rhino' or not device:
                        continue
                    try:
                        event = json.loads(blob.decode('utf-8'))
                        if (isinstance(event, dict) and
                            event.get('bridge_tag') == BRIDGE_TAG and
                            event.get('session') == session and
                            event.get('event') in haptic_feedback.PROFILES):
                            haptics.submit(event['event'], now)
                    except (ValueError, TypeError, UnicodeError):
                        continue
            if mode != 'rhino' or not device:
                haptics.clear()
                if last_mode == 'rhino' and device and rumble_fn:
                    rumble_fn(device, 0, 0, 0)
            elif haptics.enabled and rumble_fn is not None:
                def send_rumble(lo, hi, duration):
                    if device and sdl.SDL_GameControllerGetAttached(device):
                        rumble_fn(device, lo, hi, duration)
                haptics.pump(now, send_rumble)

            # Y uses tap-vs-hold detection. Tap exports the basket as before;
            # hold >= 650ms asks Rhino for a request-scoped snapshot and starts
            # a separate Shortcuts -> VS Code worker. Neither shortcut nor HTTP
            # work runs on the SDL polling thread or Rhino UI thread.
            if voice_phase in ('recording', 'ready', 'sending') and now - last_voice_check > .15:
                last_voice_check = now
                try:
                    with open(voice_protocol.status_path(voice_id), encoding='utf-8') as stream:
                        report = json.load(stream)
                    next_phase = report.get('phase')
                    if ((next_phase == 'ready' and voice_phase == 'recording') or
                            next_phase in ('error', 'sent', 'cancelled')):
                        print('Voice workflow: {} {}'.format(next_phase, report.get('detail','')), flush=True)
                        if next_phase == 'ready':
                            voice_phase = 'ready'
                        else:
                            voice_phase = 'done'
                            voice_done_at = now
                            voice_rearm = True
                except (OSError, ValueError):
                    pass
            if voice_phase == 'done' and now - voice_done_at >= .5 and not buttons.get('a') and not buttons.get('b') and not buttons.get('y'):
                voice_phase = 'idle'
                voice_id = None
            if voice_phase == 'idle':
                event = y_hold.update(now, buttons.get('y', False), mode == 'rhino' and bool(device))
                if event == 'tap':
                    rhino_presses['y'] += 1
                elif event == 'voice':
                    voice_id = uuid.uuid4().hex
                    voice_started_at = now
                    voice_phase = 'recording'
                    rhino_presses['voice'] += 1
                    voice_worker = subprocess.Popen(
                        [sys.executable, os.path.join(voice_directory, 'agent_handoff.py'),
                         '--request-id', voice_id, '--shortcut', args.voice_shortcut],
                        cwd=voice_directory, start_new_session=True)
                    print('Voice: launching macOS Shortcut; request {}'.format(voice_id[:8]), flush=True)
            else:
                y_hold.update(now, buttons.get('y', False), False)
            if voice_phase == 'ready':
                if buttons.get('a', False) and not previous_buttons.get('a', False):
                    subprocess.Popen([sys.executable, os.path.join(voice_directory, 'agent_handoff.py'),
                                      '--request-id', voice_id, '--send'], cwd=voice_directory)
                    voice_phase = 'sending'
                elif buttons.get('b', False) and not previous_buttons.get('b', False):
                    subprocess.Popen([sys.executable, os.path.join(voice_directory, 'agent_handoff.py'),
                                      '--request-id', voice_id, '--cancel'], cwd=voice_directory)
                    voice_phase = 'done'
                    voice_done_at = now
                    voice_rearm = True
            if voice_phase == 'recording' and (now - voice_started_at > 195 or
                (buttons.get('b', False) and not previous_buttons.get('b', False))):
                # Stop both the worker and its launched Shortcut when possible.
                if voice_worker is not None and voice_worker.poll() is None:
                    try:
                        os.killpg(voice_worker.pid, signal.SIGTERM)
                    except OSError:
                        pass
                voice_protocol.atomic_json(voice_protocol.status_path(voice_id),
                                           {'id':voice_id,'phase':'cancelled','detail':'Voice capture cancelled or timed out'})
                voice_phase = 'done'
                voice_done_at = now
                voice_rearm = True
            # Never leak A/B/Y into Rhino while voice capture or delivery is underway.
            voice_owns_buttons = voice_phase != 'idle' or voice_rearm
            if voice_rearm and voice_phase == 'idle' and not any(buttons.get(k, False) for k in ('a', 'b','y')):
                voice_rearm = False
                voice_owns_buttons = False
            if mode == 'rhino':
                for key in BUTTONS:
                    if key == 'y' or (voice_owns_buttons and key in ('a','b')):
                        continue
                    if buttons[key] and not previous_buttons[key] and last_mode == 'rhino':
                        rhino_presses[key] += 1
            previous_buttons = buttons

            # Don't trigger a desktop action merely from entering the layer with
            # D-pad already held. Require a fresh press after layer entry.
            down = {key for key in DIRECTIONS if buttons[key]} if mode == "desktop" else set()
            if mode == "desktop" and last_mode == "desktop" and args.desktop_backend == "yabai":
                for key in sorted(down - previous_dirs):
                    run_yabai(DIRECTIONS[key], "swap" if buttons["lb"] else "focus")
            previous_dirs = down
            last_mode = mode

            safe_axes = axes if mode == "rhino" and not voice_owns_buttons else {key: 0.0 for key in AXES}
            safe_buttons = (dict(buttons) if mode == 'rhino' else {key: False for key in BUTTONS})
            # Avoid raw-edge reconciliation interpreting a held voice-control
            # button as a normal Rhino A/B/Y press.
            safe_buttons['y'] = False
            if voice_owns_buttons:
                # No accidental target selection or extra Rhino command while
                # a spoken instruction is recording, awaiting approval or sending.
                safe_buttons = {key: False for key in BUTTONS}
            msg = {"v": 1, "bridge_tag": BRIDGE_TAG, "session": session, "seq": seq, "connected": bool(device),
                   "mode": mode, "axes": safe_axes, "buttons": safe_buttons,
                   "presses": rhino_presses, "voice_request_id": voice_id}
            sock.sendto(json.dumps(msg, separators=(",", ":")).encode("utf-8"), (HOST, PORT))
            seq += 1
            next_frame += interval
            delay = next_frame - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_frame = time.monotonic()
    except KeyboardInterrupt:
        print("Stopping bridge.", flush=True)
    finally:
        msg = {"v": 1, "bridge_tag": BRIDGE_TAG, "session": session, "seq": seq + 1, "connected": False,
               "mode": "inactive", "axes": {}, "buttons": {}, "presses": rhino_presses}
        try:
            sock.sendto(json.dumps(msg).encode("utf-8"), (HOST, PORT))
        finally:
            sock.close()
            if haptic_sock is not None:
                haptic_sock.close()
            if device:
                if rumble_fn is not None:
                    rumble_fn(device, 0, 0, 0)
                sdl.SDL_GameControllerClose(device)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnose", action="store_true", help="Print axes and buttons; no Rhino needed")
    parser.add_argument("--list-devices", action="store_true", help="Print SDL-mapped gamepads then exit")
    parser.add_argument("--diagnose-rate", type=float, metavar="SECONDS", default=0.,
                        help="Measure host SDL read rate and stick x changes (e.g. 5); NOT RF polling rate")
    parser.add_argument("--device-index", type=int, default=-1, help="SDL index to select (-1 = first mapped)")
    parser.add_argument("--desktop-backend", choices=("none", "yabai"), default="none")
    parser.add_argument("--hz", type=int, default=60)
    parser.add_argument("--no-haptics", action="store_true", help="Disable rumble entirely")
    parser.add_argument("--haptic-strength", type=float, default=1.25,
                        help="Rumble scale 0.20-1.25; perceived strength varies")
    parser.add_argument("--focus-check-ms", type=int, default=250,
                        help="osascript focus check period in ms (default 250); AppKit checks faster")
    parser.add_argument("--check-focus", action="store_true",
                        help="Print foreground-detection method and current app, then exit")
    parser.add_argument("--voice-shortcut", default="Rhino Agent Dictate",
                        help="Name of macOS Shortcut with Dictate Text + Stop and Output")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    if (not 15 <= args.hz <= 120 or args.device_index < -1 or
            not 100 <= args.focus_check_ms <= 1000 or
            not 0 <= args.diagnose_rate <= 30 or
            not 0.20 <= args.haptic_strength <= 1.25):
        parser.error("--hz: 15..120; --device-index: >= -1; --focus-check-ms: 100..1000")
    if args.check_focus:
        detector = ForegroundDetector(interval_seconds=args.focus_check_ms / 1000.0)
        name = detector.current(time.monotonic())
        print("Provider: {} | Frontmost: {} | Rhino active: {}".format(
              detector.provider, name or "UNKNOWN", is_rhino(name)))
        if detector.last_error:
            print("Lookup warning:", detector.last_error)
        return 0 if name else 2
    sdl = get_sdl2()
    bind_api(sdl)
    if sdl.SDL_InitSubSystem(SDL_INIT_GAMECONTROLLER) != 0:
        sys.exit("SDL2 initialization failed: " + sdl.SDL_GetError().decode(errors="replace"))
    try:
        if args.list_devices:
            print('SDL joystick devices (index, name, mapped as gamepad):', list_all_devices(sdl))
            return 0
        if args.diagnose:
            return diag_loop(sdl, args.device_index)
        if args.diagnose_rate:
            return rate_diagnostic(sdl, args.device_index, args.diagnose_rate)
        try:
            with BridgeSingleInstance():
                return run(args, sdl)
        except RuntimeError as exc:
            print('Bridge not started:', exc, file=sys.stderr)
            print('Stop the other bridge normally. Older versions do NOT use this lock.', file=sys.stderr)
            return 3
    finally:
        sdl.SDL_QuitSubSystem(SDL_INIT_GAMECONTROLLER)


if __name__ == "__main__":
    sys.exit(main())

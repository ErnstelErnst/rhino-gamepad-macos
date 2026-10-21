"""Rhino 8 Mac v0.5.5 voice handoff reliability update, based on v0.5.3 voice/basket/magnetic/haptics. Run ONCE to enable and AGAIN to disable.

Native RhinoCommon camera operations only; no mouse/keyboard emulation.
Requires gamepad_bridge.py running separately on the SAME Mac.
Treat as an experimental proof of concept; test on a disposable file.
"""

import importlib
import json
import math
import os
import socket
import sys
import time

import Rhino
import Rhino.Geometry as rg
import scriptcontext as sc

# ScriptEditor should run this file (not a pasted snippet): sibling modules live here.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# RhinoCode persists sys.modules across repeated runs and across version folders.
# Importing an old version's cached module then calling importlib.reload() would
# silently reload the OLD PATH. Purge only our names if their paths differ.
if SCRIPT_DIR in sys.path:
    sys.path.remove(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)
for _name in ("picker_logic", "native_picker", "selection_export", "selection_basket", "button_events",
              "cursor_logic", "topology_nav", "bridge_protocol", "target_logic", "magnetic_logic", "voice_protocol"):
    _module = sys.modules.get(_name)
    if _module is not None:
        _expected = os.path.realpath(os.path.join(SCRIPT_DIR, _name + ".py"))
        _actual = os.path.realpath(getattr(_module, "__file__", ""))
        if _actual != _expected:
            del sys.modules[_name]
# Import modules, not individual callables. Always reload when STARTING a
# listener; stop the existing listener before enabling this version.
import picker_logic
import native_picker
import selection_export
import selection_basket
import button_events
import cursor_logic
import topology_nav
import bridge_protocol
import target_logic
import magnetic_logic
import voice_protocol


def reload_components_for_development():
    # IMPORTANT: Stop the previous listener first. Reloading modules does not
    # replace an existing controller instance or its event callbacks.
    importlib.reload(picker_logic)
    importlib.reload(cursor_logic)
    importlib.reload(topology_nav)
    importlib.reload(bridge_protocol)
    importlib.reload(native_picker)
    importlib.reload(selection_export)
    importlib.reload(selection_basket)
    importlib.reload(button_events)
    importlib.reload(target_logic)
    importlib.reload(magnetic_logic)
    importlib.reload(voice_protocol)


feedback = native_picker.feedback

PORT = 47881
# Experimental scheduler: Eto.Forms.UITimer fires on the Rhino UI thread,
# avoiding the measured 10 Hz RhinoApp.Idle bottleneck on the test Mac.
# Switch to 'idle' to compare directly, or if the Eto timer proves unstable.
CAMERA_SCHEDULER = 'eto'   # 'eto' (experimental) or 'idle' (known fallback)
TARGET_CAMERA_HZ = 60.0
STICK_DEADZONE = 0.13
STICK_EXPONENT = 1.7
TRIGGER_DEADZONE = 0.08
ORBIT_DEG_PER_SEC = 130.0
PAN_DIST_PER_SEC = 0.8        # latest user-preferred pan speed (not re-tested in this package)
ZOOM_EXP_PER_SEC = 1.50       # multiplicative dolly rate
PRECISION_FACTOR = 0.25
MIN_CAMERA_DISTANCE = 0.00001
# SDL2 standard gamepad stick-click buttons. A hardware paddle may be mapped
# to L3 on the controller, but actual Mac/2.4 GHz exposure must be diagnosed.
PAN_CLUTCH_BUTTON = "l3"    # HOLD to pan during Point & Select
LOCK_BUTTON = "r3"          # PRESS to toggle persistent target highlight
PAN_NEUTRAL_THRESHOLD = 0.18

# User-tested 8BitDo Ultimate 2 / Switch Pro directional convention (v0.2).
# Change a sign to -1 or +1 if you prefer the opposite direction.
ORBIT_YAW_SIGN = -1.0       # right stick horizontal (was -1 in v0.1)
ORBIT_ELEVATION_SIGN = +1.0 # right stick vertical   (was +1 in v0.1)
PAN_HORIZONTAL_SIGN = +1.0 # left stick horizontal  (was -1 in v0.1)
PAN_VERTICAL_SIGN = -1.0   # left stick vertical    (was +1 in v0.1)

# Retain the same sticky key to make upgrading from v0.1 behave as a toggle.
# Always stop the old version before enabling this one.
KEY = "cad_gamepad_mac_rhino_v01"


def shaped_stick(x, y, deadzone=STICK_DEADZONE, exponent=STICK_EXPONENT):
    """Radial deadzone and smooth magnitude curve, normalized to [0,1]."""
    length = math.hypot(x, y)
    if not math.isfinite(length) or length <= deadzone:
        return 0.0, 0.0
    magnitude = min(1.0, (length - deadzone) / (1.0 - deadzone)) ** exponent
    return (x / length) * magnitude, (y / length) * magnitude


def shaped_trigger(value):
    if not math.isfinite(value) or value <= TRIGGER_DEADZONE:
        return 0.0
    return min(1.0, (value - TRIGGER_DEADZONE) / (1.0 - TRIGGER_DEADZONE))


def selected_bounds(doc):
    """Return combined world AABB of selected objects, or None."""
    bounds = None
    for obj in doc.Objects.GetSelectedObjects(False, False):
        if obj.Geometry is None:
            continue
        box = obj.Geometry.GetBoundingBox(False)
        if box.IsValid:
            bounds = box if bounds is None else rg.BoundingBox.Union(bounds, box)
    return bounds


class RhinoGamepad:
    def __init__(self, document):
        self.document = document
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", PORT))
        self.sock.setblocking(False)
        self.state = None
        self.received_at = -9999.0
        self.last_tick = time.monotonic()
        self.last_seq = -1
        self.last_session = None
        self.button_events = button_events.ButtonEvents()
        self.session_changed = False
        self.running = False
        self.handler = self.on_idle  # legacy fallback event handler
        self.timer_handler = self.on_timer  # retain for Eto event -=
        self.timer = None
        self.scheduler = None
        self.picker = native_picker.NativePicker()
        self.camera_rearm = False
        self.pan_cursor_rearm = False
        self.picker.on_feedback = self.emit_haptic
        self.basket = selection_basket.SelectionBasket()
        self.picker.basket = self.basket
        self.pending_basket_press = None  # deferred only when camera invalidated hover

    def emit_haptic(self, event):
        """Send a bounded, local-only haptic event back to the SDL bridge.

        This does not contain model geometry or user text. The bridge accepts
        only known events from the active Rhino session, on a loopback socket.
        """
        if event not in ('tick', 'lock', 'confirm') or not self.last_session:
            return
        try:
            packet = {'bridge_tag': bridge_protocol.BRIDGE_TAG,
                      'session': self.last_session, 'event': event}
            self.sock.sendto(json.dumps(packet).encode('utf-8'), ('127.0.0.1', 47882))
        except OSError:
            pass  # Haptics are never essential to selection.

    def start(self):
        # START on Rhino UI thread (ScriptEditor). All camera/picker/RhinoCommon
        # calls remain on this thread. Never create a worker-thread timer that
        # directly modifies a viewport.
        self.running = True
        self.last_tick = time.monotonic()
        if CAMERA_SCHEDULER == 'eto':
            timer = None
            try:
                import Eto.Forms as eto_forms
                timer = eto_forms.UITimer()
                timer.Interval = 1.0 / TARGET_CAMERA_HZ  # seconds, not milliseconds
                timer.Elapsed += self.timer_handler
                self.timer = timer  # strong reference retained in controller
                self.scheduler = 'eto'
                timer.Start()
            except Exception as exc:
                feedback('Eto UI timer unavailable ({}); using Idle fallback.'.format(repr(exc)))
                if timer is not None:
                    try:
                        timer.Stop()
                        timer.Elapsed -= self.timer_handler
                    except Exception:
                        pass
                self.timer = None
                self.scheduler = None
        if self.scheduler is None:
            Rhino.RhinoApp.Idle += self.handler
            self.scheduler = 'idle'
        feedback('v0.5.5 ON (scheduler={}, requested={} Hz). RB=Target; A=Basket; tap Y=Export; hold Y=Voice.'.format(
            self.scheduler, int(TARGET_CAMERA_HZ) if self.scheduler == 'eto' else 'system Idle'))

    def stop(self):
        if self.timer is not None:
            timer = self.timer
            self.timer = None
            try:
                timer.Stop()
            except Exception as exc:
                feedback('Timer stop warning: {}'.format(repr(exc)))
            try:
                timer.Elapsed -= self.timer_handler
            except Exception:
                pass
        if self.scheduler == 'idle':
            try:
                Rhino.RhinoApp.Idle -= self.handler
            except Exception:
                pass
        self.scheduler = None
        self.running = False
        self.picker.close(self.document)
        self.pending_basket_press = None
        self.basket.reset()  # Rhino selections remain, but basket is session-local
        self.sock.close()
        feedback('Gamepad listener OFF')

    def on_timer(self, sender, event):
        self.on_scheduler_tick()

    def on_idle(self, sender, event):
        self.on_scheduler_tick()

    def on_scheduler_tick(self):
        if not self.running:
            return
        try:
            self.update()
        except Exception as exc:
            feedback('UI {} scheduler error (stopped): {}'.format(self.scheduler, repr(exc)))
            try:
                self.stop()
            finally:
                sc.sticky.pop(KEY, None)

    def read_latest(self):
        packet = None
        # Clear backlog: if Rhino was busy, don't replay old movement.
        for _ in range(200):
            try:
                data, source = self.sock.recvfrom(4096)
            except BlockingIOError:
                break
            if source[0] != "127.0.0.1":
                continue
            try:
                candidate = json.loads(data.decode("utf-8"))
                if not bridge_protocol.compatible(candidate):
                    continue  # ignore any v0.2-v0.3.2 orphan streams
                session = candidate.get("session")
                sequence = int(candidate.get("seq", -1))
                if not isinstance(session, str) or len(session) != 32:
                    continue
                if session != self.last_session:
                    self.last_session = session
                    self.last_seq = -1
                    self.button_events.reset()
                    self.session_changed = True
                    self.camera_rearm = True
                if sequence > self.last_seq:
                    self.last_seq = sequence
                    packet = candidate
            except (ValueError, TypeError, UnicodeError, AttributeError):
                continue
        return packet

    def update(self):
        now = time.monotonic()
        latest = self.read_latest()
        if self.session_changed:
            self.session_changed = False
            self.close_picker_safely()
            self.pending_basket_press = None
        if latest is not None:
            self.state = latest
            self.received_at = now

        # Preserve existing 10 ms minimum update spacing and 50 ms dt cap.
        # With a 60 Hz UI timer, the expected dt is ~16.7ms, if delivered.
        elapsed = now - self.last_tick
        if elapsed < 0.010:
            return
        self.last_tick = now
        dt = min(0.050, max(0.0, elapsed))

        if self.state is None or now - self.received_at > 0.25:
            self.close_picker_safely()
            return
        pressed = self.button_events.consume(
            self.state.get('presses', {}), self.state.get('buttons', {}),
            eligible=(self.state.get('mode') == 'rhino' and bool(self.state.get('connected'))))
        if pressed:
            feedback('received controller presses: {} | bridge mode={}'.format(
                ', '.join(sorted(pressed)), self.state.get('mode', 'unknown')))
        if self.state.get("mode") != "rhino" or not self.state.get("connected"):
            if pressed:
                feedback('ignored: bridge not in rhino mode / controller disconnected')
            self.close_picker_safely()
            return

        if Rhino.RhinoApp.InCommand > 0:
            if pressed:
                feedback('ignored: Rhino is running a command (InCommand={})'.format(Rhino.RhinoApp.InCommand))
            self.close_picker_safely()
            return
        doc = self.document
        active = Rhino.RhinoDoc.ActiveDoc
        if active is None or doc is None or active.RuntimeSerialNumber != doc.RuntimeSerialNumber:
            self.close_picker_safely()
            return
        view = doc.Views.ActiveView
        if view is None:
            self.close_picker_safely()
            return
        vp = view.ActiveViewport
        if vp is None or vp.LockedProjection or not vp.IsPerspectiveProjection:
            if pressed:
                feedback('ignored: active viewport is not an unlocked Perspective view')
            self.close_picker_safely()
            return

        if "voice" in pressed:
            self.write_voice_snapshot(doc, self.state.get('voice_request_id'))
            return

        if "rb" in pressed:
            self.pending_basket_press = None
            try:
                if self.picker.enabled:
                    self.close_picker_safely()
                else:
                    self.picker.open(vp, doc)
            except Exception as exc:
                feedback("Look & Select could not open: {}".format(repr(exc)))
                self.close_picker_safely()
            return
        if self.picker.enabled:
            if self.picker.viewport_id != vp.Id:
                self.close_picker_safely()
                return
            if "b" in pressed:
                self.pending_basket_press = None
                result = self.basket.undo(self.apply_basket_select)
                feedback('Basket: {} ({} element(s)).'.format(result or 'nothing to undo', len(self.basket)))
                doc.Views.Redraw()
                return
            axes = self.state.get("axes", {})
            buttons = self.state.get("buttons", {})
            pan_clutch = bool(buttons.get(PAN_CLUTCH_BUTTON, False))
            # A held left stick click temporarily redirects left-stick motion
            # to viewplane pan. On release, require a neutral stick before it
            # becomes a cursor again (no surprise cursor movement).
            if pan_clutch:
                self.pan_cursor_rearm = True
            elif self.pan_cursor_rearm:
                try:
                    self.pan_cursor_rearm = not (
                        abs(float(axes.get("lx", 0.0))) < PAN_NEUTRAL_THRESHOLD and
                        abs(float(axes.get("ly", 0.0))) < PAN_NEUTRAL_THRESHOLD)
                except (ValueError, TypeError, AttributeError):
                    self.pan_cursor_rearm = True
            self.picker.set_pan_active(pan_clutch, doc)

            # The camera is allowed to orbit/zoom in selection mode. Left
            # stick only pans with the explicit clutch held.
            camera_changed = self.move_camera(vp, view, axes, buttons, dt,
                                               allow_pan=pan_clutch)
            if camera_changed:
                self.picker.camera_moved(vp, doc)
            try:
                if not pan_clutch and not self.pan_cursor_rearm:
                    mx, my = shaped_stick(float(axes.get("lx", 0.0)),
                                          float(axes.get("ly", 0.0)))
                    if self.picker.selection_style == 'magnetic':
                        self.picker.move_magnetic(vp, doc, mx, my, dt,
                                                  bool(buttons.get("lb", False)))
                    else:
                        self.picker.move_cursor(vp, doc, mx, my, dt,
                                                bool(buttons.get("lb", False)))
                else:
                    self.picker.poll(vp, doc)
            except (ValueError, TypeError, AttributeError) as exc:
                feedback('cursor data invalid: {}'.format(repr(exc)))

            if pressed.intersection({'start', 'x', 'dleft', 'dright', 'dup', 'ddown', LOCK_BUTTON}):
                # New intent supersedes an uncommitted A requested during orbit.
                self.pending_basket_press = None
            # Explicit lock is not Rhino selection. A still selects, Y still
            # only exports when the user explicitly asks for it.
            if LOCK_BUTTON in pressed:
                self.picker.toggle_lock(vp, doc)
            if "start" in pressed:
                self.picker.toggle_style(vp, doc)
            if "x" in pressed:
                self.picker.filter_next(vp, doc)
            if "dleft" in pressed or "dright" in pressed:
                self.picker.ensure_fresh(vp, doc)
                self.picker.cycle(-1 if "dleft" in pressed else +1, vp, doc)
            if "dup" in pressed:
                self.picker.navigate_topology('up', vp, doc)
            if "ddown" in pressed:
                self.picker.navigate_topology('down', vp, doc)
            if "a" in pressed:
                # Select the target that was VISIBLY highlighted on this press.
                # Do not force a synchronous repick that can silently switch it.
                current = self.picker.current()
                if current is None:
                    feedback('Basket: no highlighted target; glide toward a part.')
                elif (self.picker.selection_style == 'magnetic' and
                      self.picker.locked_entry is None and
                      self.picker.magnetic_needs_validation):
                    # On camera motion, wait for a verified SAME target. Do not
                    # require a second A press, and never select a replacement.
                    self.pending_basket_press = (magnetic_logic.key(current), now + 0.65)
                    feedback('Basket: checking highlighted target after camera motion...')
                else:
                    self.pending_basket_press = None
                    self.toggle_basket_target(doc)
            self.resolve_pending_basket_press(now, doc)
            if "y" in pressed:
                self.pending_basket_press = None
                self.export_basket(doc)
            return

        if self.camera_rearm:
            axes = self.state.get("axes", {})
            buttons = self.state.get("buttons", {})
            try:
                neutral = (all(abs(float(axes.get(k, 0))) < .18 for k in ("lx", "ly", "rx", "ry"))
                           and all(float(axes.get(k, 0)) < .14 for k in ("lt", "rt"))
                           and not any(buttons.values()))
            except (ValueError, TypeError, AttributeError):
                neutral = False
            if neutral:
                self.camera_rearm = False
            return

        if "y" in pressed:
            self.export_basket(doc)
        if "a" in pressed:
            self.frame_selection(vp, doc)

        axes = self.state.get("axes", {})
        buttons = self.state.get("buttons", {})
        self.move_camera(vp, view, axes, buttons, dt, allow_pan=True)

    def resolve_pending_basket_press(self, now, doc):
        """Complete a previously pressed A only when SAME target is verified.

        Never commit a replacement candidate after orbit or viewport movement.
        B/RB cancels pending work. Called on Rhino UI thread by the scheduler.
        """
        pending = self.pending_basket_press
        if pending is None:
            return
        identity, deadline = pending
        if now > deadline:
            self.pending_basket_press = None
            feedback('Basket: A timed out while camera was moving; nothing selected.')
            return
        if self.picker.magnetic_needs_validation:
            return
        target = self.picker.current()
        self.pending_basket_press = None
        if magnetic_logic.key(target) != identity:
            feedback('Basket: target changed after camera move; not selecting the wrong part.')
            return
        self.toggle_basket_target(doc)

    @staticmethod
    def basket_is_selected(entry, doc):
        obj = doc.Objects.FindId(entry['guid'])
        if obj is None:
            return False
        try:
            if entry['kind'] in ('face', 'edge') and int(entry['index']) >= 0:
                ct = (rg.ComponentIndexType.BrepFace if entry['kind'] == 'face'
                      else rg.ComponentIndexType.BrepEdge)
                return bool(obj.IsSubObjectSelected(rg.ComponentIndex(ct, int(entry['index']))))
            return bool(obj.IsSelected(False))
        except Exception:
            return False

    def apply_basket_select(self, entry, on):
        """Mutate a *single* entity; never UnselectAll or run Rhino commands."""
        obj = self.document.Objects.FindId(entry['guid'])
        if obj is None:
            feedback('Basket item no longer exists in Rhino: {}'.format(entry['id'][:8]))
            return False
        try:
            if entry['kind'] in ('face', 'edge') and int(entry['index']) >= 0:
                ct = (rg.ComponentIndexType.BrepFace if entry['kind'] == 'face'
                      else rg.ComponentIndexType.BrepEdge)
                ci = rg.ComponentIndex(ct, int(entry['index']))
                if not on:  # Rhinocommon returns 0 on a successful DESELECT!
                    obj.SelectSubObject(ci, False, True, True)
                    return not obj.IsSubObjectSelected(ci)
                return obj.SelectSubObject(ci, True, True, True) != 0
            if not on:
                obj.Select(False, True)
                return not obj.IsSelected(False)
            return obj.Select(True, True) != 0
        except Exception as exc:
            feedback('Basket selection API error: {}'.format(repr(exc)))
            return False

    def toggle_basket_target(self, doc):
        entry = self.picker.current()
        if entry is None:
            feedback('Basket: no target. Glide to geometry first.')
            return
        if self.picker.selection_style == 'magnetic' and self.picker.magnetic_needs_validation and self.picker.locked_entry is None:
            feedback('Basket: target not freshly confirmed after camera motion.')
            return
        obj = doc.Objects.FindId(entry['guid'])
        if obj is None or not native_picker._selectable(obj):
            feedback('Basket: geometry missing or not selectable.')
            return
        result = self.basket.toggle(entry, lambda e: self.basket_is_selected(e, doc), self.apply_basket_select)
        if result is None:
            feedback('Basket: could not change selected item (selection unchanged).')
            return
        feedback('Basket: {} {} | {} items total. A toggles; B undoes; Y exports.'.format(
            result.upper(), native_picker.describe(entry), len(self.basket)))
        self.picker._pulse('confirm')
        # Important for multi-select flow: do not strand the user in R3 lock.
        self.picker.release_lock_after_basket_commit(doc)
        self.picker._highlight(doc)
        doc.Views.Redraw()

    def write_voice_snapshot(self, doc, request_id):
        """Produce a request-scoped immutable basket context for external voice capture.

        No agent/network calls are executed from the Rhino main thread.
        """
        if not voice_protocol.valid_id(request_id):
            feedback('Voice: invalid request ID; nothing shared.')
            return
        try:
            basket = selection_export.describe_basket(doc, self.basket.entries())
            snapshot = {
                'voice_request_id': request_id,
                'basket': basket,
                'notes': 'Snapshot of basket metadata only, not full geometry or the 3DM file.',
            }
            voice_protocol.atomic_json(voice_protocol.snapshot_path(request_id), snapshot)
            feedback('Voice: snapshot ready ({} elements). Dictation is handled outside Rhino.'.format(
                basket['basket_count']))
        except Exception as exc:
            feedback('Voice: failed to prepare basket snapshot: {}'.format(repr(exc)))

    def export_basket(self, doc):
        """Explicit local export and optional macOS clipboard; no HTTP/MCP calls."""
        entries = self.basket.entries()
        if not entries:
            feedback('Basket empty. Use RB then A to add elements; no export performed.')
            return
        try:
            output, markdown, count, copied = selection_export.export_basket_with_prompt(doc, entries)
            if count:
                feedback('BASKET READY: {} items. {} | {}. Clipboard: {}. Not sent to agent.'.format(
                    count, output, markdown, 'copied (paste into agent)' if copied else 'unavailable'))
            else:
                feedback('Basket export failed: none of the referenced geometry still exists.')
        except Exception as exc:
            feedback('Basket export failed (nothing sent): {}'.format(repr(exc)))

    def move_camera(self, vp, view, axes, buttons, dt, allow_pan=True):
        """Preserves the user-verified v0.2 orbit/pan/zoom math exactly.

        Selection mode calls with allow_pan=False unless L3 is held.
        """
        try:
            lx, ly = shaped_stick(float(axes.get("lx", 0.0)), float(axes.get("ly", 0.0)))
            rx, ry = shaped_stick(float(axes.get("rx", 0.0)), float(axes.get("ry", 0.0)))
            zoom = shaped_trigger(float(axes.get("rt", 0.0))) - shaped_trigger(float(axes.get("lt", 0.0)))
        except (ValueError, TypeError, AttributeError):
            return False  # Invalid local packet; preserve listener.
        if max(abs(lx), abs(ly), abs(rx), abs(ry), abs(zoom)) < 0.0001:
            return False

        precision = PRECISION_FACTOR if buttons.get("lb", False) else 1.0
        target = vp.CameraTarget
        radius = (vp.CameraLocation - target).Length
        if radius <= MIN_CAMERA_DISTANCE or not math.isfinite(radius):
            return False
        changed = False
        if rx:
            changed = bool(vp.Rotate(ORBIT_YAW_SIGN * math.radians(ORBIT_DEG_PER_SEC) * rx * dt * precision,
                                     rg.Vector3d.ZAxis, target)) or changed
        if ry:
            vec = vp.CameraLocation - vp.CameraTarget
            elev = math.asin(max(-1.0, min(1.0, vec.Z / max(vec.Length, MIN_CAMERA_DISTANCE))))
            desired = max(math.radians(-85), min(math.radians(85),
                                                 elev + ORBIT_ELEVATION_SIGN * math.radians(ORBIT_DEG_PER_SEC) * ry * dt * precision))
            change = desired - elev
            if abs(change) > 1e-7:
                changed = bool(vp.Rotate(-change, vp.CameraX, vp.CameraTarget)) or changed
        if allow_pan and (lx or ly):
            radius = max((vp.CameraLocation - vp.CameraTarget).Length, MIN_CAMERA_DISTANCE)
            translation = (vp.CameraX * (PAN_HORIZONTAL_SIGN * lx) + vp.CameraY * (PAN_VERTICAL_SIGN * ly)) * (PAN_DIST_PER_SEC * radius * dt * precision)
            vp.SetCameraLocations(vp.CameraTarget + translation, vp.CameraLocation + translation)
            changed = True
        if abs(zoom) > 1e-7:
            target = vp.CameraTarget
            delta = (vp.CameraLocation - target) * math.exp(-ZOOM_EXP_PER_SEC * zoom * dt * precision)
            if delta.Length > MIN_CAMERA_DISTANCE:
                vp.SetCameraLocations(target, target + delta)  # ORDER: target, camera
                changed = True
        if changed:
            view.Redraw()
        return changed

    def close_picker_safely(self):
        self.pending_basket_press = None
        if not self.picker.enabled:
            return
        self.camera_rearm = True
        self.pan_cursor_rearm = False
        try:
            self.picker.close(self.document)
        except Exception as exc:
            feedback("Picker cleanup warning: {}".format(repr(exc)))

    @staticmethod
    def export_selection(doc):
        try:
            path, prompt_path, count = selection_export.export_with_prompt(doc)
            if path is None:
                feedback("Nothing selected. Select a face/curve/edge or object, then press Y.")
            else:
                print("Exported {} selected object(s) to {} and {} (NOT uploaded).".format(
                    count, path, prompt_path))
        except Exception as exc:
            print("Export failed (no data sent):", repr(exc))

    @staticmethod
    def frame_selection(vp, doc):
        box = selected_bounds(doc)
        if box is not None:
            # Zoom to bounds AND explicitly set the subsequent orbit pivot.
            if vp.ZoomBoundingBox(box):
                vp.SetCameraTarget(box.Center, False)
                print("Framed selected geometry; orbit target = selection center")
            else:
                print("Frame-selection could not zoom to selected bounds")
        else:
            vp.ZoomExtents()
            print("No selection: zoomed to full scene")
        doc.Views.Redraw()


def toggle():
    old = sc.sticky.get(KEY)
    if old is not None:
        try:
            old.stop()
        finally:
            sc.sticky.pop(KEY, None)
        return
    # RhinoCode may retain sibling modules even after a script is re-run.
    # Reload after removing any previous Idle handler (toggle OFF first).
    reload_components_for_development()
    controller = RhinoGamepad(sc.doc)
    try:
        controller.start()
        sc.sticky[KEY] = controller
    except Exception:
        controller.sock.close()
        raise


if __name__ == "__main__":
    toggle()

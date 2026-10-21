"""Experimental point-and-topology picker for Rhino 8 on macOS.

No meshes or simulated mouse/Rhino commands. A nonessential 2D conduit shows the cursor.

The RhinoCommon PickContext route is documented, but its behavior with Brep
subobjects varies. A clearly labeled *object-only* approximate fallback is
used only if native picking returns no acceptable candidates.

Scan only when entering picker or changing type filter. D-pad cycling reads
cached candidate IDs, not the document. All Rhino calls run in the Rhino idle
handler/UI context. Always test on a duplicate model.
"""

import math
import Rhino
import Rhino.Geometry as rg
import Rhino.DocObjects as rd
import Rhino.Input.Custom as ric
from System.Drawing import Rectangle, Point, Color
import time
import cursor_logic
import topology_nav
import target_logic
import magnetic_logic

from picker_logic import next_mode, next_index

MAX_FALLBACK_OBJECTS = 1200
MAX_FALLBACK_CANDIDATES = 20
BBOX_PADDING_PX = 8.0
PICK_BOX_HALF_PX = 16   # 32 x 32 pixel target; verified in Ghosted viewport


def feedback(message):
    # Unlike print(), appears in Rhino's main command history.
    Rhino.RhinoApp.WriteLine('Gamepad pick: ' + str(message))


def _kind_from_component(component_type, geometry):
    if component_type == rg.ComponentIndexType.BrepFace:
        return 'face'
    if component_type == rg.ComponentIndexType.BrepEdge:
        return 'edge'
    if isinstance(geometry, rg.Curve):
        return 'curve'
    return 'object'


def mode_accepts(mode, kind):
    if mode == 'faces':
        return kind == 'face'
    if mode == 'curves':
        return kind in ('curve', 'edge')
    return kind in ('curve', 'edge', 'face', 'object')


def describe(entry):
    return '{} {}{}'.format(entry['kind'], entry['name'] or entry['id'][:8],
                           ' #' + str(entry['index'] + 1) if entry['index'] >= 0 else '')


def _selectable(obj):
    try:
        return bool(obj.IsSelectable(True, False, False, False))
    except (AttributeError, TypeError):
        return bool(obj.IsSelectable())


def _get_line(vp, x, y):
    result = vp.GetFrustumLine(float(x), float(y))
    if not isinstance(result, tuple) or len(result) < 2 or not result[0]:
        raise RuntimeError('GetFrustumLine did not return (success, line)')
    return result[1]


def _native_pick_pass(doc, vp, mode, pick_mode, x=None, y=None, half_box=PICK_BOX_HALF_PX):
    """Run one native Rhino pick pass at the chosen viewport-local cursor.

    The rectangular pick transform and CrossingPick are required for the
    user's Rhino 8 Mac Ghosted viewport. No scene meshing is performed.
    """
    view = doc.Views.ActiveView
    if view is None:
        raise RuntimeError('No active Rhino view')
    x = int(vp.Size.Width // 2 if x is None else x)
    y = int(vp.Size.Height // 2 if y is None else y)
    rect = Rectangle(x - half_box, y - half_box,
                     2 * half_box, 2 * half_box)
    ctx = ric.PickContext()
    try:
        ctx.View = view
        ctx.PickStyle = ric.PickStyle.CrossingPick
        ctx.PickMode = pick_mode
        ctx.SubObjectSelectionEnabled = True
        ctx.SetPickTransform(vp.GetPickTransform(rect))
        ctx.PickLine = _get_line(vp, x, y)
        ctx.UpdateClippingPlanes()
        refs = doc.Objects.PickObjects(ctx)
        results, seen = [], set()
        for ref in refs or []:
            obj = ref.Object()
            if obj is None or not _selectable(obj):
                continue
            ci = ref.GeometryComponentIndex
            index = int(ci.Index)
            kind = _kind_from_component(ci.ComponentIndexType, obj.Geometry)
            if not mode_accepts(mode, kind):
                continue
            identity = (str(obj.Id), kind, index)
            if identity in seen:
                continue
            seen.add(identity)
            results.append({'id': str(obj.Id), 'guid': obj.Id,
                            'name': str(obj.Name or ''), 'kind': kind,
                            'index': index, 'approx': False})
        return results
    finally:
        ctx.Dispose()


def _native_candidates(doc, vp, mode, x=None, y=None, half_box=PICK_BOX_HALF_PX, quiet=False):
    """Two-stage native pick; prefer Shaded except for curves/edges.

    Ghosted / Wireframe can return no matches using Shaded pick mode.
    Retry with Wireframe *only when the initial filtered result is empty*.
    Propagate error details if both passes fail; the caller can then try
    explicitly-labelled approximate whole-object bounding boxes.
    """
    modes = ((ric.PickMode.Wireframe, ric.PickMode.Shaded)
             if mode == 'curves' else (ric.PickMode.Shaded, ric.PickMode.Wireframe))
    errors = []
    for number, pick_mode in enumerate(modes, 1):
        try:
            results = (_native_pick_pass(doc, vp, mode, pick_mode, x, y)
                       if half_box == PICK_BOX_HALF_PX else
                       _native_pick_pass(doc, vp, mode, pick_mode, x, y, half_box))
            if results:
                if number == 2 and not quiet:
                    feedback('native {} pick fallback succeeded ({} candidate(s)).'.format(
                        'Wireframe' if pick_mode == ric.PickMode.Wireframe else 'Shaded',
                        len(results)))
                return results
        except Exception as exc:
            errors.append('{}: {}'.format(type(exc).__name__, exc))
    if len(errors) == len(modes):
        raise RuntimeError('both native picking passes failed: ' + ' | '.join(errors))
    if errors and not quiet:
        feedback('native pick warning: {}'.format(' | '.join(errors)))
    return []


def _screen_bounds_overlap_center(vp, bounds, x, y):
    if not bounds.IsValid:
        return None
    # Cheap, approximate object-level broad phase. Not face-level ray picking.
    camera = vp.CameraLocation
    look = vp.CameraDirection
    corners = bounds.GetCorners()
    front = [p for p in corners if rg.Vector3d.Multiply(p - camera, look) > 0]
    if not front:
        return None
    points = [vp.WorldToClient(p) for p in front]
    xmin, xmax = min(p.X for p in points), max(p.X for p in points)
    ymin, ymax = min(p.Y for p in points), max(p.Y for p in points)
    if not (xmin - BBOX_PADDING_PX <= x <= xmax + BBOX_PADDING_PX and
            ymin - BBOX_PADDING_PX <= y <= ymax + BBOX_PADDING_PX):
        return None
    center = bounds.Center
    depth = rg.Vector3d.Multiply(center - camera, look)
    if not math.isfinite(depth) or depth < 0:
        return None
    return depth


def _approx_object_candidates(doc, vp, mode, x=None, y=None):
    """Fallback for whole objects only; never claims a Brep face/edge hit."""
    if mode == 'faces':
        return [], 0, False
    x = float(vp.Size.Width) / 2 if x is None else float(x)
    y = float(vp.Size.Height) / 2 if y is None else float(y)
    mask = rd.ObjectType.Curve | rd.ObjectType.Surface | rd.ObjectType.Brep | rd.ObjectType.Extrusion
    found, inspected = [], 0
    for obj in doc.Objects.GetObjectList(mask):
        inspected += 1
        if inspected > MAX_FALLBACK_OBJECTS:
            break
        try:
            if not _selectable(obj) or obj.Geometry is None:
                continue
            is_curve = isinstance(obj.Geometry, rg.Curve)
            if mode == 'curves' and not is_curve:
                continue
            depth = _screen_bounds_overlap_center(
                vp, obj.Geometry.GetBoundingBox(False), x, y)
            if depth is None:
                continue
            found.append({'id': str(obj.Id), 'guid': obj.Id,
                          'name': str(obj.Name or ''),
                          'kind': 'curve' if is_curve else 'object',
                          'index': -1, 'approx': True, 'depth': depth})
        except Exception:
            continue
    found.sort(key=lambda item: (item['depth'], item['id']))
    return found[:MAX_FALLBACK_CANDIDATES], inspected, inspected > MAX_FALLBACK_OBJECTS


class SelectionCursorConduit(Rhino.Display.DisplayConduit):
    """Optional visual aid; picking functions even if 2D overlay fails on Mac."""
    def __init__(self, picker):
        super().__init__()
        self.picker = picker
        self.warning_sent = False

    def DrawForeground(self, event):
        picker = self.picker
        if not picker.enabled or picker.viewport_id != event.Viewport.Id:
            return
        try:
            x, y = (int(picker.cursor_x), int(picker.cursor_y))
            # Basket count remains visible in BOTH selection styles. This
            # optional overlay must never prevent geometry selection.
            if picker.basket is not None:
                try:
                    kinds = picker.basket.counts()
                    summary = ', '.join('{} {}'.format(n, k) for k, n in sorted(kinds.items()))
                    label = 'BASKET {} [{}]   A add/remove   B undo   Y copy'.format(
                        len(picker.basket), summary)
                    event.Display.Draw2dText(label, Color.Cyan, Point(24, 45), False, 15)
                except Exception:
                    pass  # Rhinos may differ in Draw2dText overloads.
            if picker.selection_style == "magnetic":
                return  # No crosshair in magnetic selection: highlighted geometry is the focus.
            # Two-stroke high-contrast crosshair. A black halo stays visible on
            # light Ghosted backgrounds; bright cyan/white works on dark ones.
            # Color conveys distinct states. Drawings use the same tested
            # Draw2dLine primitive as v0.4.1 (no new HUD dependencies).
            col = (Color.Gold if picker.locked_entry is not None else
                   Color.Magenta if picker.pan_active else
                   Color.Cyan if picker.current() else Color.White)
            arm, gap = 22, 6
            segments = ((Point(x - arm, y), Point(x - gap, y)),
                        (Point(x + gap, y), Point(x + arm, y)),
                        (Point(x, y - arm), Point(x, y - gap)),
                        (Point(x, y + gap), Point(x, y + arm)))
            for p, q in segments:
                event.Display.Draw2dLine(p, q, Color.Black, 6.0)
            for p, q in segments:
                event.Display.Draw2dLine(p, q, col, 3.0)
            # Add a visible square when target is explicitly locked.
            if picker.locked_entry is not None:
                corners = ((Point(x - 10, y - 10), Point(x + 10, y - 10)),
                           (Point(x + 10, y - 10), Point(x + 10, y + 10)),
                           (Point(x + 10, y + 10), Point(x - 10, y + 10)),
                           (Point(x - 10, y + 10), Point(x - 10, y - 10)))
                for p, q in corners:
                    event.Display.Draw2dLine(p, q, Color.Black, 6.0)
                    event.Display.Draw2dLine(p, q, Color.Gold, 3.0)
            # Center pip: distinct even when geometry obscures the arms.
            event.Display.Draw2dLine(Point(x - 2, y), Point(x + 2, y), Color.Black, 6.0)
            event.Display.Draw2dLine(Point(x - 2, y), Point(x + 2, y), col, 3.0)
        except Exception as exc:
            # Avoid throwing every display frame. The picker still works.
            if not self.warning_sent:
                self.warning_sent = True
                feedback('cursor overlay unavailable: {} (selection still works)'.format(repr(exc)))
            self.Enabled = False


class NativePicker:
    def __init__(self):
        self.enabled = False
        self.viewport_id = None
        self.mode = 'all'
        self.candidates = []
        self.index = 0
        self.preview = None
        self.native_error = ''
        self.cursor_x = 0.0
        self.cursor_y = 0.0
        self.cursor_pending = False
        self.last_pick_at = -999.0
        self.topology_origin = None
        self.locked_entry = None
        self.soft_preference = None
        self.pan_active = False
        self.selection_style = 'crosshair'
        self.on_feedback = None  # provided by Rhino listener; never makes network calls by itself
        self.basket = None  # persistent, explicit collection; may be empty
        self.focus_at = (0., 0.)
        self.last_magnetic_scan = -999.
        self.last_magnetic_probe = None
        self.last_magnetic_pick_cost = 0.
        self.magnetic_needs_validation = False
        self.last_magnetic_direction = (0., 0.)
        self.focus_gate = magnetic_logic.FocusGate()
        self.last_feedback_key = None
        self.last_camera_motion = -999.0
        try:
            self.conduit = SelectionCursorConduit(self)
        except Exception as exc:
            self.conduit = None
            feedback('Optional crosshair unavailable: {} (picking still works)'.format(repr(exc)))

    def current(self):
        if self.locked_entry is not None:
            return self.locked_entry
        if self.candidates:
            return self.candidates[self.index]
        return None

    def _clear_preview(self):
        if not self.preview:
            return
        obj, kind, ci = self.preview
        try:
            if kind in ('face', 'edge'):
                if not obj.IsSubObjectSelected(ci):
                    obj.HighlightSubObject(ci, False)
            elif not obj.IsSelected(False):
                obj.Highlight(False)
        except Exception:
            pass
        self.preview = None

    def _highlight(self, doc):
        self._clear_preview()
        entry = self.current()
        if entry is None:
            return
        obj = doc.Objects.FindId(entry['guid'])
        if obj is None:
            return
        try:
            if entry['kind'] in ('face', 'edge') and entry['index'] >= 0:
                kind = (rg.ComponentIndexType.BrepFace if entry['kind'] == 'face'
                        else rg.ComponentIndexType.BrepEdge)
                ci = rg.ComponentIndex(kind, entry['index'])
                if not obj.IsSubObjectSelected(ci):
                    obj.HighlightSubObject(ci, True)
                    self.preview = (obj, entry['kind'], ci)
            elif not obj.IsSelected(False):
                obj.Highlight(True)
                self.preview = (obj, entry['kind'], None)
        except Exception as exc:
            feedback('preview error: {}'.format(type(exc).__name__))
        doc.Views.Redraw()
        # One feedback event for every *committed* visual focus change,
        # including D-pad/topology/crosshair changes. Repeated redraws do not
        # trigger ticks. The external bridge schedules these light pulses.
        identity = magnetic_logic.key(entry)
        if identity != self.last_feedback_key:
            self.last_feedback_key = identity
            self._pulse('tick')

    def _report(self):
        entry = self.current()
        if entry is None:
            feedback('no {} hits near cursor ({},{}); move left stick and pause.'.format(self.mode, int(self.cursor_x), int(self.cursor_y)))
            return
        feedback('{}/{}: {}{} — D-pad L/R cycle, X filter, A select, B/RB cancel.'.format(
            self.index + 1, len(self.candidates), describe(entry),
            (' [approximate FACE anchor — verify highlight]' if entry['approx'] and entry['kind'] == 'face'
             else ' [approximate WHOLE OBJECT]' if entry['approx'] else ' [native/topology]')))

    def refresh(self, vp, doc, verbose=True):
        if self.locked_entry is not None:
            return  # An explicit lock is not silently overwritten by camera picks.
        previous = self.current() or self.soft_preference
        self._clear_preview()
        self.candidates = []
        self.index = 0
        try:
            self.candidates = _native_candidates(doc, vp, self.mode, self.cursor_x, self.cursor_y)
            self.native_error = ''
            if verbose:
                feedback('Rhino native pick returned {} matching candidate(s).'.format(len(self.candidates)))
        except Exception as exc:
            message = '{}: {}'.format(type(exc).__name__, exc)
            if verbose or message != self.native_error:
                feedback('native pick error: {}'.format(message))
            self.native_error = message
        if not self.candidates:
            self.candidates, scanned, capped = _approx_object_candidates(doc, vp, self.mode, self.cursor_x, self.cursor_y)
            if self.candidates and verbose:
                feedback('using APPROXIMATE whole-object fallback ({} object(s) scanned{}).'.format(
                    scanned, '; scan capped' if capped else ''))
            elif not self.candidates and self.mode == 'faces' and verbose:
                feedback('Face pick unavailable. X switches filter; all mode can pick whole surfaces.')
        # "Soft target" = keep the same face/edge if it remains in the fresh
        # pick bank, even if Rhino reorders overlapping candidates.
        self.index = target_logic.preferred_index(self.candidates, previous)
        self.soft_preference = None
        self._highlight(doc)
        self.topology_origin = None
        self.cursor_pending = False
        self.last_pick_at = time.monotonic()
        if verbose:
            self._report()

    def open(self, vp, doc):
        if self.enabled:
            self.close(doc)
            return
        self.enabled = True
        self.selection_style = 'magnetic'  # New experiment; Start returns to v0.4.2 crosshair.
        self.viewport_id = vp.Id
        self.mode = 'all'
        self.cursor_x = float(vp.Size.Width) / 2.0
        self.cursor_y = float(vp.Size.Height) / 2.0
        self.cursor_pending = False
        self.topology_origin = None
        self.locked_entry = None
        self.soft_preference = None
        self.pan_active = False
        self.last_camera_motion = -999.0
        self.focus_at = (self.cursor_x, self.cursor_y)
        self.last_magnetic_scan = -999.
        self.last_magnetic_probe = (self.cursor_x, self.cursor_y)
        self.magnetic_needs_validation = False
        self.last_magnetic_direction = (0., 0.)
        self.focus_gate.reset()
        self.last_feedback_key = None
        try:
            if self.conduit is not None:
                self.conduit.Enabled = True
        except Exception as exc:
            feedback('cursor overlay startup unavailable: {}'.format(repr(exc)))
        feedback('MAGNETIC SELECT ON. Left stick glides focus; Start toggles CROSSHAIR; D-pad cycles; A selects.')
        self.refresh(vp, doc)

    def close(self, doc):
        if not self.enabled:
            return
        self._clear_preview()
        self.enabled = False
        self.viewport_id = None
        self.candidates = []
        self.cursor_pending = False
        self.topology_origin = None
        self.locked_entry = None
        self.soft_preference = None
        self.pan_active = False
        self.magnetic_needs_validation = False
        self.focus_gate.reset()
        self.last_feedback_key = None
        try:
            if self.conduit is not None:
                self.conduit.Enabled = False
        except Exception:
            pass
        if doc is not None:
            doc.Views.Redraw()
        feedback('OFF')

    def cycle(self, direction, vp, doc):
        if self.locked_entry is not None:
            feedback('Target LOCKED. Click R3 to unlock before cycling.')
            return
        self.index = next_index(self.index, len(self.candidates), direction)
        self._highlight(doc)
        self._report()

    def filter_next(self, vp, doc):
        if self.locked_entry is not None:
            feedback('Target LOCKED. Click R3 to unlock before changing filter.')
            return
        self.mode = next_mode(self.mode)
        feedback('filter: {}'.format(self.mode))
        self.refresh(vp, doc)

    def _pulse(self, event):
        if callable(self.on_feedback):
            try:
                self.on_feedback(event)
            except Exception:
                pass  # Haptics never block Rhino selection.

    def toggle_style(self, vp, doc):
        """Start (+) switches magnetic focus vs exact movable crosshair."""
        if self.locked_entry is not None:
            feedback('Target LOCKED. R3 unlocks before changing selection style.')
            return
        self.selection_style = 'crosshair' if self.selection_style == 'magnetic' else 'magnetic'
        self.focus_at = (self.cursor_x, self.cursor_y)
        self.magnetic_needs_validation = False
        self.focus_gate.reset()
        self.last_magnetic_scan = -999.
        self.last_magnetic_probe = (self.cursor_x, self.cursor_y)
        self.soft_preference = None
        self.refresh(vp, doc, verbose=False)
        feedback('Selection style: {}. Start (+) switches again.'.format(self.selection_style.upper()))
        doc.Views.Redraw()

    @staticmethod
    def _entry_metrics(entry, vp, doc, probe_x, probe_y):
        """Bounded per-component projection: approximate depth/visible screen box.

        No meshing and no full-document iteration. Bounding rectangles can be
        loose for curved faces and never establish exact occlusion.
        """
        try:
            obj = doc.Objects.FindId(entry['guid'])
            if obj is None or obj.Geometry is None:
                return None, (probe_x, probe_y)
            geo = obj.Geometry
            index = int(entry['index'])
            if index >= 0 and entry['kind'] == 'face' and isinstance(geo, rg.Brep):
                geo = geo.Faces[index]
            elif index >= 0 and entry['kind'] == 'edge' and isinstance(geo, rg.Brep):
                geo = geo.Edges[index]
            bounds = geo.GetBoundingBox(False)
            if not bounds.IsValid:
                return None, (probe_x, probe_y)
            depth = float(rg.Vector3d.Multiply(bounds.Center - vp.CameraLocation,
                                               vp.CameraDirection))
            depth = depth if math.isfinite(depth) and depth >= 0 else None
            corners = bounds.GetCorners()
            projectable = [vp.WorldToClient(p) for p in corners
                           if rg.Vector3d.Multiply(p - vp.CameraLocation,
                                                   vp.CameraDirection) > 0]
            if not projectable:
                return depth, (probe_x, probe_y)
            xs = [float(pt.X) for pt in projectable]
            ys = [float(pt.Y) for pt in projectable]
            nearest_x = max(min(xs), min(probe_x, max(xs)))
            nearest_y = max(min(ys), min(probe_y, max(ys)))
            return depth, (nearest_x, nearest_y)
        except Exception:
            return None, (probe_x, probe_y)

    def _magnetic_scan(self, vp, doc, force=False):
        """Bounded native picking along short segments of the analog glide.

        Selection never relies on mesh creation or whole-document scans.
        A camera move cancels the old path because screen coordinates changed.
        """
        if self.locked_entry is not None:
            return
        now = time.monotonic()
        if not force and now - self.last_magnetic_scan < magnetic_logic.SCAN_INTERVAL:
            return
        if not force and now - self.last_camera_motion < 0.05:
            return
        self.last_magnetic_scan = now
        previous = self.current()
        if previous is not None and self.last_feedback_key is None:
            # A pre-existing focus (including one restored from cached picker
            # state) is not itself a new target transition.
            self.last_feedback_key = magnetic_logic.key(previous)
        target = (self.cursor_x, self.cursor_y)
        prior = self.last_magnetic_probe or target
        points = ([target] if force or self.magnetic_needs_validation else
                  magnetic_logic.sweep_positions(
                      prior, target, max_samples=magnetic_logic.scan_sample_budget(
                          self.last_magnetic_pick_cost)))
        pick_started = time.monotonic()
        self.last_magnetic_probe = target
        banks = []
        for px, py in points:
            try:
                found = _native_candidates(doc, vp, self.mode, px, py,
                                           magnetic_logic.MAGNETIC_PICK_HALF_PX, quiet=True)
            except Exception as exc:
                msg = '{}: {}'.format(type(exc).__name__, exc)
                if msg != self.native_error:
                    feedback('Magnetic native picking unavailable: ' + msg)
                self.native_error = msg
                return
            for entry in found:
                entry['depth'], nearest = self._entry_metrics(entry, vp, doc, px, py)
                entry['screen_x'], entry['screen_y'] = nearest
            banks.append(((px, py), found))
        self.last_magnetic_pick_cost = max(0., time.monotonic() - pick_started)
        try:
            camera_radius = float((vp.CameraLocation - vp.CameraTarget).Length)
        except Exception:
            camera_radius = 1.0
        chosen, hit_position = magnetic_logic.choose_swept(
            banks, previous, self.focus_at, self.last_magnetic_direction,
            camera_radius, force)
        if chosen is None:
            if math.hypot(target[0] - self.focus_at[0],
                          target[1] - self.focus_at[1]) > 2.0:
                self.focus_at = target
            # Crossing an empty gap must NOT invalidate a visibly highlighted
            # target. Only actual camera movement causes a stale focus.
            self.cursor_pending = False
            self.focus_gate.forget_candidate()
            return
        if not self.focus_gate.accept(previous, chosen, self.focus_at,
                                      self.last_magnetic_direction, now, force):
            # Keep scanning the proposed destination until the direction is
            # stable. The viewport keeps showing the last accepted focus.
            self.cursor_pending = True
            return
        self._clear_preview()
        self.candidates = [chosen]
        self.index = 0
        self.focus_at = hit_position
        self.topology_origin = None
        self.cursor_pending = False
        self.last_pick_at = now
        self.magnetic_needs_validation = False
        self._highlight(doc)

    def move_magnetic(self, vp, doc, lx, ly, dt, precision=False):
        if not self.enabled or self.selection_style != 'magnetic':
            return
        x, y, moved = magnetic_logic.advance(self.cursor_x, self.cursor_y, lx, ly, dt,
                                             vp.Size.Width, vp.Size.Height, precision)
        if moved:
            self.cursor_x, self.cursor_y = x, y
            self.cursor_pending = True
            self.last_magnetic_direction = (float(lx), float(ly))
        if self.cursor_pending:
            self._magnetic_scan(vp, doc)

    def move_cursor(self, vp, doc, lx, ly, dt, precision=False):
        if not self.enabled:
            return
        x, y, moved = cursor_logic.advance(self.cursor_x, self.cursor_y, lx, ly, dt,
                                          vp.Size.Width, vp.Size.Height, precision)
        if moved:
            self.cursor_x, self.cursor_y = x, y
            self.cursor_pending = True
            self.topology_origin = None
            # Crosshair redraw is independent from expensive picking.
            doc.Views.ActiveView.Redraw()
        self.poll(vp, doc)

    def poll(self, vp, doc):
        if self.enabled and self.selection_style == 'magnetic':
            if self.cursor_pending and self.locked_entry is None:
                self._magnetic_scan(vp, doc)
            return
        if (self.enabled and self.locked_entry is None and self.cursor_pending and
                target_logic.can_refresh(time.monotonic(), self.last_pick_at,
                                         self.last_camera_motion,
                                         cursor_logic.PICK_UPDATE_SECONDS)):
            self.refresh(vp, doc, verbose=False)

    def camera_moved(self, vp, doc):
        """Drop stale hover during motion; a separately locked target persists."""
        self.last_camera_motion = time.monotonic()
        self.last_magnetic_probe = (self.cursor_x, self.cursor_y)
        self.focus_gate.reset()  # camera motion invalidates screen-space anchors
        if self.selection_style == 'magnetic':
            if self.locked_entry is None:
                self.magnetic_needs_validation = bool(self.current())
                self.cursor_pending = True
            return  # Keep visual focus, revalidate after camera stops.
        if self.locked_entry is None:
            # Remember prior hover only as a preference, not an actionable
            # candidate, until a fresh pick confirms it remains under cursor.
            if self.candidates:
                self.soft_preference = dict(self.current())
            self._clear_preview()
            self.candidates = []
            self.index = 0
            self.cursor_pending = True
            self.topology_origin = None

    def set_pan_active(self, value, doc):
        value = bool(value)
        if self.pan_active != value:
            self.pan_active = value
            doc.Views.Redraw()

    def toggle_lock(self, vp, doc):
        """R3 toggles intent lock. A still performs actual Rhino selection."""
        if self.locked_entry is not None:
            self._clear_preview()
            self.locked_entry = None
            self.soft_preference = None
            self.cursor_pending = True
            self.last_camera_motion = -999.0
            self.refresh(vp, doc, verbose=False)
            feedback('Target UNLOCKED. Live hover restored.')
            return
        if self.selection_style == 'magnetic':
            self._magnetic_scan(vp, doc, force=True)
        else:
            self.ensure_fresh(vp, doc)
        if self.selection_style == 'magnetic' and self.magnetic_needs_validation:
            feedback('Cannot lock stale magnetic focus. Move aim toward visible geometry first.')
            return
        entry = self.current()
        if entry is None:
            feedback('No candidate to lock. Aim at geometry and pause (or move closer).')
            return
        self.locked_entry = dict(entry)
        self._pulse('lock')
        self.soft_preference = None
        self._highlight(doc)
        feedback('TARGET LOCKED: {}. Orbit, zoom, or pan freely; A selects; R3 unlocks.'.format(
            describe(entry)))

    def release_lock_after_basket_commit(self, doc):
        """A commits the locked item to the basket, freeing focus for next item.

        No expensive pick here; the next update reacquires near the current
        focus position. R3 remains available for temporary inspection lock.
        """
        if self.locked_entry is None:
            return
        self.locked_entry = None
        self.soft_preference = None
        self.cursor_pending = True
        self.last_magnetic_scan = -999.0
        self.topology_origin = None
        self._highlight(doc)
        feedback('Target unlocked after basket change; ready to glide to the next element.')

    def recenter(self, vp, doc):
        self.cursor_x = float(vp.Size.Width) / 2.0
        self.cursor_y = float(vp.Size.Height) / 2.0
        feedback('cursor recentered at viewport midpoint (Start button).')
        if self.locked_entry is None:
            self.refresh(vp, doc, verbose=True)
        else:
            doc.Views.Redraw()

    def ensure_fresh(self, vp, doc):
        if self.selection_style == 'magnetic' and self.locked_entry is None:
            self._magnetic_scan(vp, doc, force=True)
            return
        if self.locked_entry is not None:
            return
        if self.cursor_pending:
            self.refresh(vp, doc, verbose=False)

    def _seed_face_from_object(self, entry, vp, doc):
        """Give topology an anchor when Rhino picks a whole Brep in Ghosted.

        Only inspect faces of the ONE candidate object. No meshes, document
        traversal, or pretence that bounding boxes identify visible surfaces.
        Returns True only if an approximate face highlight was established.
        """
        obj = doc.Objects.FindId(entry['guid'])
        brep = obj.Geometry if obj is not None else None
        if brep is None or not isinstance(brep, rg.Brep):
            feedback('Topology needs a Brep face/edge. This is a standalone curve or unsupported object.')
            return False
        if brep.Faces.Count > 800:
            feedback('Large Brep: approximate face scan limited to its first 800 faces.')
        indices = topology_nav.face_anchors_near_cursor(
            brep, vp, self.cursor_x, self.cursor_y)
        if not indices:
            feedback('Whole Brep hit, but no face bounding box meets cursor. Aim at a face or use X faces filter.')
            return False
        bank = [{'id': entry['id'], 'guid': entry['guid'], 'name': entry['name'],
                 'kind': 'face', 'index': i, 'approx': True} for i in indices]
        self._clear_preview()
        self.candidates = bank
        self.index = 0
        self.topology_origin = None
        self._highlight(doc)
        feedback('Whole Brep -> {} APPROXIMATE face anchor(s) near cursor. '
                 'Check cyan highlight; D-pad L/R chooses face.'.format(len(bank)))
        self._report()
        return True

    def navigate_topology(self, direction, vp, doc):
        """Walk within one Brep. Up explores faces; Down explores edges.

        A whole-Brep native pick must first be resolved to a face. This is
        common in Ghosted mode, especially when X filter is still `all`.
        """
        if self.locked_entry is not None:
            feedback('Target LOCKED. Click R3 to unlock before navigating topology.')
            return
        if self.cursor_pending:
            self.ensure_fresh(vp, doc)
        entry = self.current()
        if entry is None:
            feedback('D-pad {} received, but no candidate is under cursor. Move cursor over geometry.'.format(direction))
            return
        feedback('D-pad {}: {} ({})'.format(direction, describe(entry), self.mode))
        if entry['kind'] not in ('face', 'edge'):
            # Seed first. Up leaves face highlighted so the user can choose
            # an anchor; Down directly explores the face boundary edges.
            if not self._seed_face_from_object(entry, vp, doc):
                return
            if direction == 'up':
                feedback('Face anchor ready. Up again: adjacent faces; Down: boundary edges.')
                return
            entry = self.current()
        # Repeated Up or Down cycles the same adjacency bank without recursing.
        if self.topology_origin is not None and self.topology_origin[0] == direction:
            self.cycle(+1, vp, doc)
            return
        entry = self.current()
        obj = doc.Objects.FindId(entry['guid'])
        brep = obj.Geometry if obj is not None else None
        if brep is None or not isinstance(brep, rg.Brep):
            feedback('Topology requires a Brep face or edge in this object.')
            return
        pairs = topology_nav.neighbor_indices(brep, entry['kind'], entry['index'], direction)
        bank = [{'id': entry['id'], 'guid': entry['guid'], 'name': entry['name'],
                 'kind': kind, 'index': idx, 'approx': False}
                for kind, idx in pairs]
        if not bank:
            if direction == 'up' and entry['kind'] == 'face' and brep.Faces.Count == 1:
                feedback('This is a SINGLE-FACE surface. No adjacent faces exist within this Brep; Down shows its edges.')
            else:
                feedback('No connected {} in this Brep from {}. Separate Rhino objects are not adjacent.'.format(
                    'faces' if direction == 'up' else 'edges', describe(entry)))
            return
        self._clear_preview()
        self.candidates = topology_nav.deduplicate(bank)
        self.index = 0
        self.topology_origin = (direction, entry['id'], entry['kind'], entry['index'])
        self._highlight(doc)
        feedback('Connected {}: {} candidate(s); repeat D-pad {} or L/R to cycle.'.format(
            'faces' if direction == 'up' else 'edges', len(bank), direction))
        self._report()

    def select(self, doc, additive=False):
        if self.selection_style == 'magnetic' and self.locked_entry is None and self.magnetic_needs_validation:
            feedback('Magnetic target not verified after camera movement. Aim or release stick to reacquire.')
            return False
        entry = self.current()
        if entry is None:
            feedback('No candidate to select. Exit with B/RB, aim at geometry and retry.')
            return False
        obj = doc.Objects.FindId(entry['guid'])
        if obj is None or not _selectable(obj):
            feedback('Candidate no longer selectable')
            return False
        self._clear_preview()
        kind, index = entry['kind'], entry['index']
        try:
            # Only modify the selection after successfully resolving the target.
            if not additive:
                doc.Objects.UnselectAll()
            if kind == 'face' and index >= 0:
                ci = rg.ComponentIndex(rg.ComponentIndexType.BrepFace, index)
                okay = obj.SelectSubObject(ci, True, True, True) != 0
            elif kind == 'edge' and index >= 0:
                ci = rg.ComponentIndex(rg.ComponentIndexType.BrepEdge, index)
                okay = obj.SelectSubObject(ci, True, True, True) != 0
            else:
                okay = obj.Select(True, True) != 0
        except Exception as exc:
            feedback('selection API error: {}'.format(repr(exc)))
            okay = False
        doc.Views.Redraw()
        if okay:
            feedback('SELECTED: {}'.format(describe(entry)))
            self._pulse('confirm')
            if not additive:
                self.close(doc)
            else:
                self.topology_origin = None  # next adjacency action re-anchors here
                self._highlight(doc)
        else:
            feedback('Rhino refused selection; check object/layer lock state')
        return okay

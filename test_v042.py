"""v0.4.2 offline behavior tests. Mac/Rhino/controller integration remains untested."""
import ast
import pathlib
import unittest
from unittest.mock import MagicMock, patch

import bridge_protocol
import gamepad_bridge
import target_logic
from test_native_picker import picker

ROOT = pathlib.Path(__file__).parent


def hit(kind='face', index=1, ident='a'):
    return {'id': ident * 32, 'guid': ident + 'GUID', 'kind': kind,
            'index': index, 'name': 'part', 'approx': False}


class SoftHoverTests(unittest.TestCase):
    def test_same_candidate_survives_pick_order_changes(self):
        a, b, c = hit(index=1), hit(index=2), hit(index=3)
        self.assertEqual(target_logic.preferred_index([b, c, a], a), 2)

    def test_off_cursor_candidate_is_not_reused_as_actionable(self):
        self.assertEqual(target_logic.preferred_index([hit(index=8)], hit(index=2)), 0)

    def test_missing_hit_returns_first_or_none_as_appropriate(self):
        self.assertEqual(target_logic.preferred_index([], hit()), 0)
        self.assertEqual(target_logic.preferred_index([hit()], None), 0)

    def test_stable_key_includes_subobject_component(self):
        self.assertNotEqual(target_logic.target_key(hit(index=1)),
                            target_logic.target_key(hit(index=2)))
        self.assertNotEqual(target_logic.target_key(hit(kind='edge')),
                            target_logic.target_key(hit(kind='face')))

    def test_repick_waits_until_camera_stops(self):
        self.assertFalse(target_logic.can_refresh(now=10., last_pick=9., last_camera_motion=9.9))
        self.assertTrue(target_logic.can_refresh(now=10., last_pick=9., last_camera_motion=9.7))

    def test_repick_is_rate_limited(self):
        self.assertFalse(target_logic.can_refresh(now=10., last_pick=9.90, last_camera_motion=8.))
        self.assertTrue(target_logic.can_refresh(now=10., last_pick=9.7, last_camera_motion=8.))


class LockAndRefreshTests(unittest.TestCase):
    def setUp(self):
        self.p = picker.NativePicker()
        self.p.enabled = True
        self.p.viewport_id = 'fake-view'
        self.p.mode = 'all'
        self.p.cursor_x = 120
        self.p.cursor_y = 120
        self.obj = MagicMock()
        self.obj.IsSelected.return_value = False
        self.obj.IsSubObjectSelected.return_value = False
        self.doc = MagicMock()
        self.doc.Objects.FindId.return_value = self.obj
        self.vp = MagicMock()
        self.vp.Size.Width = 1000
        self.vp.Size.Height = 800
        self.p.conduit = None
        feedback_patch = patch.object(picker, 'feedback')
        feedback_patch.start()
        self.addCleanup(feedback_patch.stop)

    def test_lock_is_distinct_from_rhino_select(self):
        self.p.candidates = [hit()]
        self.p.toggle_lock(self.vp, self.doc)
        self.assertEqual(self.p.locked_entry['index'], 1)
        self.doc.Objects.UnselectAll.assert_not_called()
        self.obj.Select.assert_not_called()
        self.obj.SelectSubObject.assert_not_called()

    def test_lock_survives_camera_motion(self):
        self.p.candidates = [hit()]
        self.p.toggle_lock(self.vp, self.doc)
        self.p.camera_moved(self.vp, self.doc)
        self.assertEqual(self.p.current()['index'], 1)
        self.assertIsNotNone(self.p.locked_entry)

    def test_unlocked_target_not_actionable_after_camera_motion(self):
        self.p.candidates = [hit()]
        self.p.camera_moved(self.vp, self.doc)
        self.assertIsNone(self.p.current())
        self.assertTrue(self.p.cursor_pending)
        self.assertEqual(self.p.soft_preference['index'], 1)

    def test_hover_preference_restored_only_when_found(self):
        self.p.candidates = [hit(index=7)]
        self.p.camera_moved(self.vp, self.doc)
        bank = [hit(index=2), hit(index=7), hit(index=1)]
        with patch.object(picker, '_native_candidates', return_value=bank):
            self.p.refresh(self.vp, self.doc, verbose=False)
        self.assertEqual(self.p.current()['index'], 7)
        self.assertIsNone(self.p.soft_preference)

    def test_candidate_not_preserved_when_fresh_pick_misses(self):
        self.p.candidates = [hit(index=7)]
        self.p.camera_moved(self.vp, self.doc)
        with patch.object(picker, '_native_candidates', return_value=[]), \
             patch.object(picker, '_approx_object_candidates', return_value=([], 0, False)):
            self.p.refresh(self.vp, self.doc, verbose=False)
        self.assertIsNone(self.p.current())
        self.assertIsNone(self.p.soft_preference)

    def test_locked_target_skips_expensive_repick(self):
        self.p.candidates = [hit()]
        self.p.toggle_lock(self.vp, self.doc)
        with patch.object(picker, '_native_candidates') as fn:
            self.p.refresh(self.vp, self.doc)
            self.p.camera_moved(self.vp, self.doc)
            self.p.poll(self.vp, self.doc)
            fn.assert_not_called()

    def test_unlock_reenables_live_hover(self):
        self.p.candidates = [hit()]
        self.p.toggle_lock(self.vp, self.doc)
        with patch.object(picker, '_native_candidates', return_value=[hit(index=4)]):
            self.p.toggle_lock(self.vp, self.doc)
        self.assertIsNone(self.p.locked_entry)
        self.assertEqual(self.p.current()['index'], 4)

    def test_locked_target_blocks_candidate_cycle(self):
        self.p.candidates = [hit(), hit(index=2)]
        self.p.toggle_lock(self.vp, self.doc)
        self.p.cycle(1, self.vp, self.doc)
        self.assertEqual(self.p.current()['index'], 1)

    def test_pan_color_status_updates_without_changing_cursor(self):
        self.p.cursor_x, self.p.cursor_y = 175, 210
        self.p.set_pan_active(True, self.doc)
        self.assertTrue(self.p.pan_active)
        self.assertEqual((self.p.cursor_x, self.p.cursor_y), (175, 210))
        self.p.set_pan_active(False, self.doc)
        self.assertFalse(self.p.pan_active)


class BridgeAndCameraPolicyTests(unittest.TestCase):
    def test_bridge_emits_stick_click_buttons(self):
        self.assertEqual(gamepad_bridge.BUTTONS['l3'], 7)
        self.assertEqual(gamepad_bridge.BUTTONS['r3'], 8)

    def test_bridge_can_diagnose_optional_paddles(self):
        self.assertEqual(gamepad_bridge.BUTTONS['paddle1'], 16)
        self.assertEqual(gamepad_bridge.BUTTONS['paddle2'], 17)

    def test_new_bridge_incompatible_with_prior_tag(self):
        self.assertTrue(bridge_protocol.compatible({'v': 1, 'bridge_tag': bridge_protocol.BRIDGE_TAG}))
        self.assertFalse(bridge_protocol.compatible({'v': 1, 'bridge_tag': 'rhino_gamepad_v04'}))

    def test_camera_shared_between_modes(self):
        tree = ast.parse((ROOT / 'rhino_gamepad_toggle.py').read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'RhinoGamepad')
        funcs = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
        self.assertIn('move_camera', funcs)
        self.assertIn('update', funcs)
        self.assertGreaterEqual(sum(1 for n in ast.walk(funcs['update'])
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and
               n.func.attr == 'move_camera'), 2)
        self.assertIn('allow_pan', ast.unparse(funcs['move_camera']))

    def test_no_forced_camera_pause_in_picker(self):
        src = (ROOT / 'rhino_gamepad_toggle.py').read_text()
        self.assertNotIn('Strictly no camera movement while selecting', src)
        self.assertIn('pan_cursor_rearm', src)
        self.assertIn('PAN_CLUTCH_BUTTON', src)
        self.assertIn('LOCK_BUTTON', src)

    def test_cached_sibling_modules_are_purged_before_imports(self):
        src = (ROOT / 'rhino_gamepad_toggle.py').read_text()
        self.assertIn('del sys.modules[_name]', src)
        self.assertIn('os.path.realpath', src)


if __name__ == '__main__':
    unittest.main()

class CameraExtractionTests(unittest.TestCase):
    """Run the exact shipped camera function against lightweight Rhino vectors."""

    class Vec:
        def __init__(self, x=0, y=0, z=0):
            self.x, self.y, self.z = x, y, z

        def __add__(self, other):
            return self.__class__(self.x + other.x, self.y + other.y, self.z + other.z)

        def __sub__(self, other):
            return self.__class__(self.x - other.x, self.y - other.y, self.z - other.z)

        def __mul__(self, factor):
            return self.__class__(self.x * factor, self.y * factor, self.z * factor)

        __rmul__ = __mul__

        @property
        def Length(self):
            return (self.x ** 2 + self.y ** 2 + self.z ** 2) ** .5

    def setUp(self):
        import math
        from types import SimpleNamespace
        tree = ast.parse((ROOT / 'rhino_gamepad_toggle.py').read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'RhinoGamepad')
        fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'move_camera')
        funcs = {'shaped_stick', 'shaped_trigger'}
        constants = {'MIN_CAMERA_DISTANCE', 'PRECISION_FACTOR', 'ORBIT_YAW_SIGN',
                     'ORBIT_ELEVATION_SIGN', 'PAN_HORIZONTAL_SIGN', 'PAN_VERTICAL_SIGN',
                     'ORBIT_DEG_PER_SEC', 'PAN_DIST_PER_SEC', 'ZOOM_EXP_PER_SEC',
                     'STICK_DEADZONE', 'STICK_EXPONENT', 'TRIGGER_DEADZONE'}
        required = [n for n in tree.body if
                    isinstance(n, ast.FunctionDef) and n.name in funcs or
                    isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in constants
                                                           for t in n.targets)]
        code = ast.fix_missing_locations(ast.Module(body=required + [fn], type_ignores=[]))
        scope = {'math': math, 'rg': SimpleNamespace(Vector3d=SimpleNamespace(ZAxis=self.Vec(0, 0, 1)))}
        exec(compile(code, str(ROOT / 'rhino_gamepad_toggle.py'), 'exec'), scope)
        self.move = scope['move_camera']
        self.vp = MagicMock()
        self.vp.CameraLocation = self.Vec(0, -10, 0)
        self.vp.CameraTarget = self.Vec(0, 0, 0)
        self.vp.CameraX = self.Vec(1, 0, 0)
        self.vp.CameraY = self.Vec(0, 0, 1)
        self.vp.Rotate.return_value = True
        self.view = MagicMock()
        self.axes = dict(lx=0., ly=0., rx=0., ry=0., rt=0., lt=0.)
        self.buttons = dict(lb=False, l3=False)

    def test_orbit_available_without_pan_in_selection(self):
        self.axes['rx'] = .8
        changed = self.move(None, self.vp, self.view, self.axes, self.buttons,
                            .016, allow_pan=False)
        self.assertTrue(changed)
        self.vp.Rotate.assert_called()
        self.vp.SetCameraLocations.assert_not_called()

    def test_zoom_available_without_pan_in_selection(self):
        self.axes['rt'] = .8
        changed = self.move(None, self.vp, self.view, self.axes, self.buttons,
                            .016, allow_pan=False)
        self.assertTrue(changed)
        self.vp.SetCameraLocations.assert_called_once()
        self.view.Redraw.assert_called_once()

    def test_left_stick_does_not_pan_without_clutch(self):
        self.axes['lx'] = .8
        changed = self.move(None, self.vp, self.view, self.axes, self.buttons,
                            .016, allow_pan=False)
        self.assertFalse(changed)
        self.vp.SetCameraLocations.assert_not_called()

    def test_left_stick_pans_with_clutch(self):
        self.axes['lx'] = .8
        changed = self.move(None, self.vp, self.view, self.axes, self.buttons,
                            .016, allow_pan=True)
        self.assertTrue(changed)
        self.vp.SetCameraLocations.assert_called_once()

    def test_live_tuned_orbit_yaw_negative(self):
        self.axes['rx'] = .8
        self.move(None, self.vp, self.view, self.axes, self.buttons,
                  .016, allow_pan=False)
        angle = self.vp.Rotate.call_args.args[0]
        self.assertLess(angle, 0)

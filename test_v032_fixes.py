"""Offline v0.3.2 regression tests. No Rhino or SDL installation required."""
import types
import unittest
from unittest.mock import MagicMock, patch

from button_events import ButtonEvents
from test_native_picker import picker


class EventReconciliationTests(unittest.TestCase):
    def test_fast_tap_captured_via_counter_even_when_button_up(self):
        ev = ButtonEvents()
        self.assertEqual(ev.consume({'rb': 0}, {'rb': False}), set())
        self.assertEqual(ev.consume({'rb': 1}, {'rb': False}), {'rb'})
        self.assertEqual(ev.consume({'rb': 1}, {'rb': False}), set())

    def test_raw_rising_edge_only_once_while_held(self):
        ev = ButtonEvents()
        ev.consume({'a': 0}, {'a': False})
        self.assertEqual(ev.consume({'a': 0}, {'a': True}), {'a'})
        self.assertEqual(ev.consume({'a': 0}, {'a': True}), set())
        self.assertEqual(ev.consume({'a': 0}, {'a': True}), set())
        self.assertEqual(ev.consume({'a': 0}, {'a': False}), set())
        self.assertEqual(ev.consume({'a': 0}, {'a': True}), {'a'})

    def test_counter_plus_raw_rise_deduped(self):
        ev = ButtonEvents()
        ev.consume({'x': 0}, {'x': False})
        self.assertEqual(ev.consume({'x': 1}, {'x': True}), {'x'})
        self.assertEqual(ev.consume({'x': 1}, {'x': True}), set())
        ev.consume({'x': 1}, {'x': False})
        self.assertEqual(ev.consume({'x': 2}, {'x': True}), {'x'})

    def test_later_counter_on_same_held_raw_press_suppressed(self):
        ev = ButtonEvents()
        ev.consume({'rb': 0}, {'rb': False})
        self.assertEqual(ev.consume({'rb': 0}, {'rb': True}), {'rb'})
        self.assertEqual(ev.consume({'rb': 1}, {'rb': True}), set())

    def test_baseline_session_reset_does_not_replay_pressed_button(self):
        ev = ButtonEvents()
        ev.consume({'a': 3}, {'a': True})
        self.assertEqual(ev.consume({'a': 3}, {'a': True}), set())
        ev.reset()
        self.assertEqual(ev.consume({'a': 0}, {'a': True}), set())
        self.assertEqual(ev.consume({'a': 0}, {'a': False}), set())
        self.assertEqual(ev.consume({'a': 1}, {'a': True}), {'a'})

    def test_ineligible_still_consumes_press(self):
        ev = ButtonEvents()
        ev.consume({'a': 0}, {'a': False})
        self.assertEqual(ev.consume({'a': 1}, {'a': True}, eligible=False), set())
        self.assertEqual(ev.consume({'a': 1}, {'a': True}), set())

    def test_invalid_payload_resets_safely(self):
        ev = ButtonEvents()
        ev.consume({'a': 0}, {'a': False})
        self.assertEqual(ev.consume({'a': 'bad'}, {'a': True}), set())
        self.assertEqual(ev.consume({'a': 1}, {'a': True}), set())


class TwoPassNativePickerTests(unittest.TestCase):
    def setUp(self):
        self.pm = types.SimpleNamespace(Shaded='shaded', Wireframe='wireframe')
        self.original_pick_mode = getattr(picker.ric, 'PickMode', None)
        picker.ric.PickMode = self.pm

    def tearDown(self):
        if self.original_pick_mode is None:
            del picker.ric.PickMode
        else:
            picker.ric.PickMode = self.original_pick_mode

    def test_shaded_then_wireframe_fallback(self):
        with patch.object(picker, '_native_pick_pass', side_effect=[[], [{'kind':'face'}]]) as p:
            with patch.object(picker, 'feedback'):
                hits = picker._native_candidates(None, None, 'faces')
        self.assertEqual(hits, [{'kind':'face'}])
        self.assertEqual([call.args[3] for call in p.call_args_list], ['shaded', 'wireframe'])

    def test_curves_start_in_wireframe(self):
        with patch.object(picker, '_native_pick_pass', return_value=[{'kind':'edge'}]) as p:
            hits = picker._native_candidates(None, None, 'curves')
        self.assertEqual(hits[0]['kind'], 'edge')
        p.assert_called_once_with(None, None, 'curves', 'wireframe', None, None)

    def test_first_success_does_not_rerun(self):
        with patch.object(picker, '_native_pick_pass', return_value=[{'kind':'object'}]) as p:
            picker._native_candidates(None, None, 'all')
        p.assert_called_once()

    def test_both_picker_modes_fail_error_is_visible(self):
        with patch.object(picker, '_native_pick_pass', side_effect=RuntimeError('bad')):
            with self.assertRaisesRegex(RuntimeError, 'both native picking passes failed'):
                picker._native_candidates(None, None, 'all')

    def test_uses_rectangle_crossing_pick_and_no_meshing(self):
        ctx = MagicMock()
        doc = MagicMock()
        doc.Objects.PickObjects.return_value = []
        vp = MagicMock()
        vp.Size.Width = 1000
        vp.Size.Height = 800
        vp.GetFrustumLine.return_value = (True, object())
        picker.ric.PickStyle = types.SimpleNamespace(CrossingPick='crossing')
        picker.ric.PickContext = lambda: ctx
        picker.Rectangle = lambda x,y,w,h: (x,y,w,h)
        result = picker._native_pick_pass(doc, vp, 'all', 'wireframe')
        self.assertEqual(result, [])
        vp.GetPickTransform.assert_called_once_with((484, 384, 32, 32))
        self.assertEqual(ctx.PickStyle, 'crossing')
        self.assertEqual(ctx.PickMode, 'wireframe')
        ctx.Dispose.assert_called_once()


class SelectionOverloadTests(unittest.TestCase):
    def setUp(self):
        self.doc = MagicMock()
        self.obj = MagicMock()
        self.obj.IsSelectable.return_value = True
        self.obj.Select.return_value = 1
        self.obj.SelectSubObject.return_value = 2
        self.doc.Objects.FindId.return_value = self.obj
        self.p = picker.NativePicker()
        self.p.enabled = True
        self.p.preview = None
        self.p.candidates = [{'id':'a'*32, 'guid':'some-guid', 'kind':'object',
                              'index':-1, 'name':'Thing', 'approx':False}]
        self.p.index = 0

    def test_whole_object_select_has_two_arguments(self):
        self.assertTrue(self.p.select(self.doc))
        self.obj.Select.assert_called_once_with(True, True)
        self.doc.Objects.UnselectAll.assert_called_once()

    def test_subobject_select_has_four_arguments(self):
        self.p.candidates[0]['kind'] = 'face'
        self.p.candidates[0]['index'] = 3
        self.assertTrue(self.p.select(self.doc, additive=True))
        self.obj.SelectSubObject.assert_called_once_with((1, 3), True, True, True)
        self.doc.Objects.UnselectAll.assert_not_called()


if __name__ == '__main__':
    unittest.main()

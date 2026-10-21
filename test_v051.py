"""Regression tests for v0.5.1: no ignored A, bounded swept picks."""
import importlib
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

import magnetic_logic as ml
from test_native_picker import picker


def hit(i, x=100, y=80):
    return {'id': str(i)*32, 'guid': str(i)+'-guid', 'kind':'face',
            'index':i, 'approx':False, 'screen_x': x,
            'screen_y': y, 'depth':8., 'name':'Face'+str(i)}


class SweptTests(unittest.TestCase):
    def test_short_motion_one_pick(self):
        self.assertEqual(ml.sweep_positions((0,0),(20,0)), [(20.0,0.0)])

    def test_fast_motion_samples_midpoint_and_endpoint(self):
        self.assertEqual(ml.sweep_positions((0,0),(120,0)),[(60.,0.),(120.,0.)])

    def test_diagonal_sampling(self):
        self.assertEqual(ml.sweep_positions((0,0),(80,80)),[(40.,40.),(80.,80.)])

    def test_sample_count_never_exceeds_budget(self):
        self.assertEqual(len(ml.sweep_positions((0,0),(1000,0))),2)

    def test_slow_native_pick_limits_sweep_to_one(self):
        self.assertEqual(ml.scan_sample_budget(.08),1)
        self.assertEqual(ml.scan_sample_budget(.002),2)

    def test_intermediate_target_wins_over_more_distant_end_target(self):
        first, far = hit(2,40,80), hit(3,100,80)
        res,point=ml.choose_swept([((40,80),[first]),((100,80),[far])],
                hit(1,0,80), (0,80), (1,0),5)
        self.assertEqual(res['index'],2)
        self.assertEqual(point,(40,80))

    def test_previous_is_retained_when_no_new_candidate(self):
        old=hit(1,0,80)
        res,_=ml.choose_swept([((30,80),[old]),((80,80),[])],old,(0,80),(1,0),10)
        self.assertEqual(res['index'],1)

    def test_tiny_motion_retains_previous_with_competing_hit(self):
        old=hit(1,0,80)
        new=hit(2,15,80)
        res,_=ml.choose_swept([((5,80),[old,new])],old,(0,80),(1,0),10)
        self.assertEqual(res['index'],1)

    def test_direction_disallows_behind_sample(self):
        old=hit(1,0,80)
        left=hit(2,-40,80)
        res,_=ml.choose_swept([((40,80),[left])],old,(0,80),(1,0),10)
        self.assertIsNone(res)


class PickerTests(unittest.TestCase):
    def setUp(self):
        self.p=picker.NativePicker()
        self.p.enabled=True
        self.p.selection_style='magnetic'
        self.p.mode='all'
        self.p.cursor_x=200.
        self.p.cursor_y=80.
        self.p.last_magnetic_probe=(80.,80.)
        self.p.focus_at=(80.,80.)
        self.vp=MagicMock()
        self.doc=MagicMock()
        self.doc.Objects.FindId.return_value.IsSubObjectSelected.return_value=False

    def test_magnetic_scan_samples_intermediate_part(self):
        early=hit(2,130,80)
        late=hit(3,200,80)
        seen=[]
        def fake_pick(doc,vp,mode,x,y,half_box,quiet=False):
            seen.append((x,y))
            return [early] if x<180 else [late]
        with patch.object(picker,'_native_candidates',side_effect=fake_pick), \
             patch.object(self.p,'_entry_metrics',side_effect=lambda e,v,d,x,y:(8,(e['screen_x'],e['screen_y']))), \
             patch.object(self.p,'_highlight'), patch.object(self.p,'_pulse'):
            self.p._magnetic_scan(self.vp,self.doc,force=False)
        self.assertEqual(len(seen),2)
        self.assertEqual(self.p.current()['index'],2)

    def test_empty_gap_keeps_target_valid_without_camera_motion(self):
        self.p.candidates=[hit(1)]
        with patch.object(picker,'_native_candidates',return_value=[]):
            self.p._magnetic_scan(self.vp,self.doc,force=True)
        self.assertFalse(self.p.magnetic_needs_validation)

    def test_empty_gap_stays_invalid_after_camera_motion(self):
        self.p.candidates=[hit(1)]
        self.p.camera_moved(self.vp,self.doc)
        # Simulate camera settling before the next scan
        self.p.last_camera_motion=-999.
        with patch.object(picker,'_native_candidates',return_value=[]):
            self.p._magnetic_scan(self.vp,self.doc,force=True)
        self.assertTrue(self.p.magnetic_needs_validation)


class DeferredA(unittest.TestCase):
    def setUp(self):
        import test_native_picker  # installs Rhino mocks
        if 'scriptcontext' not in sys.modules:
            sys.modules['scriptcontext']=types.SimpleNamespace(sticky={})
        self.listener=importlib.import_module('rhino_gamepad_toggle')
        self.ctrl=self.listener.RhinoGamepad.__new__(self.listener.RhinoGamepad)
        self.ctrl.picker=MagicMock()
        self.ctrl.pending_basket_press=None
        self.ctrl.toggle_basket_target=MagicMock()

    def test_deferred_press_executes_once_after_same_target_verified(self):
        t=hit(1)
        self.ctrl.pending_basket_press=(ml.key(t),100.5)
        self.ctrl.picker.magnetic_needs_validation=True
        self.ctrl.picker.current.return_value=t
        with patch.object(self.listener,'feedback'):
            self.ctrl.resolve_pending_basket_press(100.0,None)
            self.ctrl.toggle_basket_target.assert_not_called()
            self.ctrl.picker.magnetic_needs_validation=False
            self.ctrl.resolve_pending_basket_press(100.1,None)
            self.ctrl.resolve_pending_basket_press(100.2,None)
        self.ctrl.toggle_basket_target.assert_called_once()

    def test_changed_target_never_auto_selected(self):
        self.ctrl.pending_basket_press=(ml.key(hit(1)),100.5)
        self.ctrl.picker.magnetic_needs_validation=False
        self.ctrl.picker.current.return_value=hit(2)
        with patch.object(self.listener,'feedback'):
            self.ctrl.resolve_pending_basket_press(100.1,None)
        self.ctrl.toggle_basket_target.assert_not_called()

    def test_pending_press_expires_instead_of_late_commit(self):
        self.ctrl.pending_basket_press=(ml.key(hit(1)),100.5)
        self.ctrl.picker.magnetic_needs_validation=False
        self.ctrl.picker.current.return_value=hit(1)
        with patch.object(self.listener,'feedback'):
            self.ctrl.resolve_pending_basket_press(101.0,None)
        self.ctrl.toggle_basket_target.assert_not_called()


if __name__=='__main__': unittest.main()

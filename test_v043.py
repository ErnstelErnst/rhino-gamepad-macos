"""New v0.4.3 offline tests; does not substitute for a Rhino-on-Mac run."""
import ast
import math
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

import bridge_protocol
import magnetic_logic as mag
import haptic_feedback as hap
from test_native_picker import picker

ROOT = Path(__file__).parent


def hit(index=1, ident='a', depth=12.0, x=100, y=90):
    return {'id': ident*32, 'guid': ident+'GUID', 'kind': 'face', 'index': index,
            'name': 'part', 'depth': depth, 'screen_x': x, 'screen_y': y,
            'approx': False}


class GlideTests(TestCase):
    def test_full_speed_glides_gradually(self):
        a,b,moved = mag.advance(120,100,1,0,0.02,1000,800)
        self.assertTrue(moved)
        self.assertAlmostEqual(a,168.0)
        self.assertEqual(b,100)

    def test_precision_slows_without_reversing(self):
        x,_,_ = mag.advance(120,100,1,0,0.02,1000,800,precision=True)
        self.assertAlmostEqual(x-120, 12.0)

    def test_screen_vertical_moves_down(self):
        _,y,_ = mag.advance(120,100,0,1,0.02,1000,800)
        self.assertGreater(y,100)

    def test_releases_stop_not_glide(self):
        self.assertEqual(mag.advance(120,100,0,0,.05,1000,800), (120,100,False))

    def test_clamp_screen_edges(self):
        x, y, _ = mag.advance(994,794,1,1,.1,1000,800)
        self.assertEqual((x,y),(995.,795.))

    def test_nonfinite_input_does_not_change_focus(self):
        self.assertEqual(mag.advance(40,80,float('nan'),0,0.02,1000,800), (40,80,False))


class GeometryScoringTests(TestCase):
    def test_prefers_nearest_in_right_direction(self):
        near=hit(2, 'n', 11, x=145, y=90)
        far=hit(3, 'f', 10, x=190, y=90)
        got=mag.choose([far,near],hit(1), (100,90), (150,90), (1,0), 15)
        self.assertEqual(mag.key(got),mag.key(near))

    def test_rejects_leftward_candidate_when_going_right(self):
        west=hit(2,'w', 8, x=65, y=90)
        east=hit(3,'e', 8, x=145, y=90)
        got=mag.choose([west,east],hit(1), (100,90), (150,90), (1,0), 15)
        self.assertEqual(mag.key(got),mag.key(east))

    def test_prefers_aligned_over_diagonal(self):
        aligned=hit(2,'a',8,x=158,y=100)
        diagonal=hit(3,'d',8,x=153,y=145)
        got=mag.choose([diagonal,aligned],hit(1), (100,100), (150,100), (1,0), 15)
        self.assertEqual(mag.key(got),mag.key(aligned))

    def test_respects_depth_gap(self):
        current=hit(1,depth=10)
        bg=hit(2,'b',depth=90,x=145)
        fg=hit(3,'f',depth=8,x=155)
        got=mag.choose([bg,fg],current,(100,90),(150,90),(1,0), 15)
        self.assertEqual(mag.key(got),mag.key(fg))

    def test_no_far_jump_if_no_candidate_in_direction(self):
        current=hit(1,depth=10)
        self.assertEqual(mag.key(mag.choose([hit(2,'b',depth=110)],current,(100,90),(150,90),(1,0),15)), mag.key(hit(2,'b',depth=110)))

    def test_focus_retained_for_small_motion(self):
        original=hit(1,depth=10)
        other=hit(2,'b',depth=9)
        self.assertEqual(mag.key(mag.choose([other,original],original,(100,90),(110,90),(1,0),15)),
                         mag.key(original))

    def test_too_large_search_gap_defers_jump(self):
        self.assertIsNotNone(mag.choose([hit(2)],hit(1),(0,0),(300,0),(1,0),20))

    def test_identity_detects_subobject_transition(self):
        self.assertTrue(mag.should_tick(hit(1),hit(2)))
        self.assertFalse(mag.should_tick(hit(1),hit(1)))
        self.assertFalse(mag.should_tick(hit(1),None))


class HapticTests(TestCase):
    def test_each_switch_tick_is_scheduled(self):
        h=hap.HapticScheduler()
        self.assertTrue(h.submit('tick',1.0))
        self.assertTrue(h.submit('tick',1.05))
        self.assertTrue(h.submit('tick',1.16))
        self.assertEqual(len(h.pending),3)

    def test_confirmation_is_nonblocking_double_pulse(self):
        h=hap.HapticScheduler()
        out=[]
        self.assertTrue(h.submit('confirm',3.0))
        self.assertTrue(h.pump(3.0,lambda *args:out.append(args)))
        self.assertEqual(len(out),1)
        self.assertFalse(h.pump(3.1,lambda *args:out.append(args)))
        self.assertTrue(h.pump(3.22,lambda *args:out.append(args)))
        self.assertEqual(len(out),2)

    def test_confirmation_does_not_drop_subsequent_focus_ticks(self):
        h=hap.HapticScheduler()
        h.submit('confirm',2.)
        self.assertTrue(h.submit('tick',2.12))
        self.assertEqual(len(h.pending),3)

    def test_unsupported_event_ignored(self):
        h=hap.HapticScheduler()
        self.assertFalse(h.submit('download-file',1.0))
        self.assertFalse(h.pending)

    def test_strength_bounded(self):
        low,high=hap.motors(0.8,0.9,2.0)
        self.assertLessEqual(max(low,high),int(65535*hap.MAX_POWER))

    def test_disable_mutes_all(self):
        h=hap.HapticScheduler(enabled=False)
        self.assertFalse(h.submit('tick',1))
        self.assertFalse(h.pump(1,lambda *args:None))


class PickerIntegrationTests(TestCase):
    def setUp(self):
        self.p = picker.NativePicker()
        self.p.conduit = None
        self.p.enabled = True
        self.p.selection_style='magnetic'
        self.p.cursor_x = 100.
        self.p.cursor_y = 90.
        self.p.focus_at=(100.,90.)
        self.vp=MagicMock()
        self.vp.Size.Width=1000
        self.vp.Size.Height=700
        self.vp.CameraLocation=MagicMock()
        self.doc=MagicMock()
        self.obj=MagicMock()
        self.obj.IsSelected.return_value=False
        self.obj.IsSubObjectSelected.return_value=False
        self.doc.Objects.FindId.return_value=self.obj
        self.p.on_feedback=MagicMock()
        f=patch.object(picker,'feedback')
        f.start()
        self.addCleanup(f.stop)

    def test_magnetic_transition_sends_one_tick(self):
        a,b=hit(1),hit(2)
        self.p.candidates=[a]
        self.p.cursor_x=145
        with patch.object(picker, '_native_candidates', return_value=[b]), \
             patch.object(self.p, '_entry_metrics', return_value=(8,(145,90))):
            self.p._magnetic_scan(self.vp,self.doc,force=True)
        self.assertEqual(self.p.current()['index'],2)
        self.p.on_feedback.assert_called_once_with('tick')

    def test_no_tick_if_same_target(self):
        a=hit(1)
        self.p.candidates=[a]
        with patch.object(picker,'_native_candidates',return_value=[a]), \
             patch.object(self.p, '_entry_metrics', return_value=(12,(100,90))):
            self.p._magnetic_scan(self.vp,self.doc,force=True)
        self.p.on_feedback.assert_not_called()

    def test_empty_gap_retains_stable_highlight_without_stale_flag(self):
        self.p.candidates=[hit(1)]
        with patch.object(picker,'_native_candidates',return_value=[]):
            self.p._magnetic_scan(self.vp,self.doc,force=True)
        self.assertFalse(self.p.magnetic_needs_validation)
        self.assertEqual(self.p.current()['index'],1)

    def test_lock_suppresses_auto_gliding_selection(self):
        self.p.locked_entry=hit(9)
        with patch.object(picker,'_native_candidates') as found:
            self.p._magnetic_scan(self.vp,self.doc,force=True)
            found.assert_not_called()

    def test_camera_motion_retains_highlight_requires_revalidation(self):
        self.p.candidates=[hit(1)]
        self.p.camera_moved(self.vp,self.doc)
        self.assertEqual(self.p.current()['index'],1)
        self.assertTrue(self.p.magnetic_needs_validation)

    def test_start_switches_back_to_crosshair(self):
        with patch.object(self.p,'refresh'):
            self.p.toggle_style(self.vp,self.doc)
        self.assertEqual(self.p.selection_style,'crosshair')

    def test_protocol_tag_updated(self):
        self.assertTrue(bridge_protocol.compatible({'v':1,'bridge_tag':'rhino_gamepad_v05'}))
        self.assertFalse(bridge_protocol.compatible({'v':1,'bridge_tag':'rhino_gamepad_v042'}))

    def test_source_wires_bridge_haptic_port_and_precise_fallback(self):
        bridge=(ROOT/'gamepad_bridge.py').read_text()
        listener=(ROOT/'rhino_gamepad_toggle.py').read_text()
        self.assertIn('HAPTIC_PORT = 47882',bridge)
        self.assertIn("self.picker.move_magnetic",listener)
        self.assertIn("self.picker.toggle_style",listener)
        self.assertIn("self.picker.on_feedback = self.emit_haptic",listener)
        self.assertIn('last_session',listener)


if __name__ == '__main__':
    import unittest
    unittest.main()

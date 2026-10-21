"""v0.5.2 regression coverage for stable directional focus and per-switch haptics."""
import unittest
from unittest.mock import MagicMock, patch
import magnetic_logic as m
import haptic_feedback as h
from test_native_picker import picker


def face(num, x, y=100):
    return dict(id=str(num)*32, guid=str(num)+'-guid', kind='face',
                index=num, screen_x=float(x), screen_y=float(y),
                depth=10., approx=False, name=str(num))


class FocusGateTests(unittest.TestCase):
    def setUp(self):
        self.g=m.FocusGate()
        self.a=face(1,100)
        self.b=face(2,135)

    def test_initial_focusing_is_immediate(self):
        self.assertTrue(self.g.accept(None,self.a,(100,100),(1,0),1.0))

    def test_forward_focus_requires_two_confirmations(self):
        self.assertFalse(self.g.accept(self.a,self.b,(100,100),(1,0),1.5))
        self.assertTrue(self.g.accept(self.a,self.b,(100,100),(1,0),1.54))

    def test_tiny_forward_displacement_cannot_oscillate(self):
        near=face(2,103)
        for i in range(4):
            self.assertFalse(self.g.accept(self.a,near,(100,100),(1,0),1+i*.04))

    def test_backward_target_is_rejected_on_right_stick(self):
        behind=face(3,70)
        for i in range(4):
            self.assertFalse(self.g.accept(self.a,behind,(100,100),(1,0),1+i*.04))

    def test_direction_reverses_when_stick_reverses(self):
        behind=face(3,70)
        self.assertFalse(self.g.accept(self.a,behind,(100,100),(-1,0),1))
        self.assertTrue(self.g.accept(self.a,behind,(100,100),(-1,0),1.04))

    def test_off_axis_target_is_rejected(self):
        sideways=face(3,115,200)
        for i in range(4):
            self.assertFalse(self.g.accept(self.a,sideways,(100,100),(1,0),1+i*.04))

    def test_hesitation_with_alternating_hits_never_switches(self):
        c=face(3,148)
        for i in range(10):
            candidate=self.b if i%2==0 else c
            self.assertFalse(self.g.accept(self.a,candidate,(100,100),(1,0),1+i*.04))

    def test_minimum_pause_between_commits(self):
        self.assertTrue(self.g.accept(None,self.a,(100,100),(1,0),2.0))
        self.assertFalse(self.g.accept(self.a,self.b,(100,100),(1,0),2.02))
        self.assertFalse(self.g.accept(self.a,self.b,(100,100),(1,0),2.06))
        self.assertFalse(self.g.accept(self.a,self.b,(100,100),(1,0),2.09))
        self.assertTrue(self.g.accept(self.a,self.b,(100,100),(1,0),2.13))

    def test_same_target_is_not_counted_as_switch(self):
        self.assertTrue(self.g.accept(self.a,self.a,(100,100),(1,0),1))
        self.assertEqual(self.g.pending_count,0)

    def test_force_allows_explicit_revalidation(self):
        self.assertTrue(self.g.accept(self.a,self.b,(100,100),(0,0),1,force=True))


class HapticSequenceTests(unittest.TestCase):
    def test_every_tick_is_accepted_and_sent(self):
        sched=h.HapticScheduler(strength=1.25)
        for t in (1.,1.01,1.02,1.03):
            self.assertTrue(sched.submit('tick',t))
        sent=[]
        for i in range(75):
            sched.pump(1.+i*.0167,lambda *args:sent.append(args))
        self.assertEqual(len(sent),4)
        self.assertEqual(len(sched.pending),0)

    def test_tick_much_lighter_than_confirmation(self):
        t=h.PROFILES['tick'][0]
        c=h.PROFILES['confirm'][0]
        self.assertLess(t[0],c[0])
        self.assertLess(t[2],c[2])

    def test_ticks_are_preserved_around_selection_confirmation(self):
        sched=h.HapticScheduler()
        for kind in ('tick','tick','confirm','tick'):
            self.assertTrue(sched.submit(kind,1.0))
        sent=[]
        for i in range(140):
            sched.pump(1+i*.0167,lambda *args:sent.append(args))
        self.assertEqual(len(sent),5)  # three ticks + double confirm

    def test_bridge_mode_switch_clears_pending_events(self):
        sched=h.HapticScheduler()
        sched.submit('tick',1.)
        sched.clear()
        self.assertEqual(sched.pending,[])


class PickerFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.p=picker.NativePicker()
        self.p.enabled=True
        self.p.on_feedback=MagicMock()
        self.doc=MagicMock()
        self.doc.Objects.FindId.return_value.IsSelected.return_value=False
        self.doc.Objects.FindId.return_value.IsSubObjectSelected.return_value=False

    def test_one_tick_per_distinct_committed_highlight(self):
        a,b=face(1,100),face(2,130)
        self.p.candidates=[a]
        self.p._highlight(self.doc)
        self.p._highlight(self.doc)
        self.p.candidates=[b]
        self.p._highlight(self.doc)
        self.p._highlight(self.doc)
        self.assertEqual(self.p.on_feedback.call_args_list,[unittest.mock.call('tick'),unittest.mock.call('tick')])

    def test_no_haptic_when_new_candidate_proposal_rejected(self):
        self.p.candidates=[face(1,100)]
        self.p.last_feedback_key=m.key(self.p.current())
        self.p.selection_style='magnetic'
        self.p.last_magnetic_probe=(100,100)
        self.p.focus_at=(100,100)
        self.p.cursor_x=130
        self.p.cursor_y=100
        self.p.last_magnetic_direction=(1,0)
        self.p.last_magnetic_scan=-999
        self.p.last_camera_motion=-999
        vp=MagicMock()
        new=face(2,130)
        with patch.object(picker,'_native_candidates',return_value=[new]), \
             patch.object(self.p,'_entry_metrics',return_value=(10,(130,100))), \
             patch.object(self.p,'_highlight') as hi:
            self.p._magnetic_scan(vp,self.doc,force=False)
        self.assertEqual(m.key(self.p.current()),m.key(face(1,100)))
        hi.assert_not_called()
        self.p.on_feedback.assert_not_called()

if __name__=='__main__': unittest.main()

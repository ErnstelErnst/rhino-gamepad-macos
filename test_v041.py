"""Targeted v0.4.1 tests. All Rhino APIs are represented by mocks."""
import types
import unittest
from unittest.mock import MagicMock, patch
import topology_nav
from test_native_picker import picker


def face(x0, y0, x1, y1, adjacent_faces, adjacent_edges):
    f = MagicMock()
    f.AdjacentFaces.return_value = adjacent_faces
    f.AdjacentEdges.return_value = adjacent_edges
    bounds = MagicMock()
    bounds.IsValid = True
    bounds.GetCorners.return_value = [types.SimpleNamespace(X=x0, Y=y0),
                                      types.SimpleNamespace(X=x1, Y=y0),
                                      types.SimpleNamespace(X=x0, Y=y1),
                                      types.SimpleNamespace(X=x1, Y=y1)]
    f.GetBoundingBox.return_value = bounds
    return f


class Collection(list):
    @property
    def Count(self):
        return len(self)


class FakeBrep:
    def __init__(self):
        self.Faces = Collection([
            face(100, 100, 200, 200, [1], [0, 1]),
            face(190, 100, 250, 210, [0], [1, 2]),
            face(400, 300, 450, 350, [], [3]),
        ])
        self.Edges = Collection([MagicMock() for _ in range(4)])


class FaceAnchorTests(unittest.TestCase):
    def setUp(self):
        self.brep = FakeBrep()
        self.vp = MagicMock()
        self.vp.WorldToClient.side_effect = lambda p: p

    def test_near_cursor_face_candidates_and_order(self):
        self.assertEqual(topology_nav.face_anchors_near_cursor(self.brep, self.vp, 150, 150), [0])
        self.assertEqual(topology_nav.face_anchors_near_cursor(self.brep, self.vp, 220, 160), [1])

    def test_no_approximate_face_away_from_object(self):
        self.assertEqual(topology_nav.face_anchors_near_cursor(self.brep, self.vp, 900, 900), [])

    def test_limited_scan(self):
        b = FakeBrep()
        b.Faces = Collection([face(0, 0, 10, 10, [], []) for _ in range(805)])
        self.assertEqual(len(topology_nav.face_anchors_near_cursor(b, self.vp, 5, 5)), 20)
        b.Faces[803].GetBoundingBox.assert_not_called()


class PickerTopologyTests(unittest.TestCase):
    def setUp(self):
        self.brep = FakeBrep()
        self.obj = MagicMock()
        self.obj.Geometry = self.brep
        self.obj.IsSubObjectSelected.return_value = False
        self.obj.IsSelected.return_value = False
        self.doc = MagicMock()
        self.doc.Objects.FindId.return_value = self.obj
        self.vp = MagicMock()
        self.vp.WorldToClient.side_effect = lambda p: p
        self.p = picker.NativePicker()
        self.p.enabled = True
        self.p.cursor_x = 150
        self.p.cursor_y = 150
        self.p.candidates = [{'id': 'a'*32, 'guid': 'obj-id', 'name': 'Test', 'kind': 'object',
                              'index': -1, 'approx': False}]
        self.rg_patch = patch.object(picker.rg, 'Brep', FakeBrep, create=True)
        self.rg_patch.start()
        self.addCleanup(self.rg_patch.stop)
        self.feedback_patch = patch.object(picker, 'feedback')
        self.messages = self.feedback_patch.start()
        self.addCleanup(self.feedback_patch.stop)

    def test_up_first_seeds_face_then_walks_connected(self):
        self.p.navigate_topology('up', self.vp, self.doc)
        self.assertEqual(self.p.current()['kind'], 'face')
        self.assertEqual(self.p.current()['index'], 0)
        self.assertTrue(self.p.current()['approx'])
        self.p.navigate_topology('up', self.vp, self.doc)
        self.assertEqual(self.p.current()['kind'], 'face')
        self.assertEqual(self.p.current()['index'], 1)
        self.assertFalse(self.p.current()['approx'])

    def test_down_from_whole_brep_directly_shows_edges(self):
        self.p.navigate_topology('down', self.vp, self.doc)
        self.assertEqual(self.p.current()['kind'], 'edge')
        self.assertEqual([e['index'] for e in self.p.candidates], [0, 1])
        self.assertFalse(self.p.current()['approx'])

    def test_non_brep_does_not_guess_subobject(self):
        self.obj.Geometry = object()
        self.p.navigate_topology('up', self.vp, self.doc)
        self.assertEqual(self.p.current()['kind'], 'object')
        self.assertIn('Topology needs a Brep', str(self.messages.call_args_list))

    def test_single_face_has_no_adjacent_but_edges_work(self):
        self.brep.Faces = Collection([face(100, 100, 200, 200, [], [0, 1])])
        self.p.navigate_topology('up', self.vp, self.doc)
        self.p.navigate_topology('up', self.vp, self.doc)
        self.assertIn('SINGLE-FACE', str(self.messages.call_args_list))
        self.p.navigate_topology('down', self.vp, self.doc)
        self.assertEqual(self.p.current()['kind'], 'edge')

    def test_no_candidates_gives_button_specific_feedback(self):
        self.p.candidates = []
        self.p.navigate_topology('up', self.vp, self.doc)
        self.assertIn('D-pad up received', str(self.messages.call_args_list))


class CrosshairTests(unittest.TestCase):
    def test_dual_stroke_visibility(self):
        picker.Color = types.SimpleNamespace(Cyan='cyan', White='white', Black='black')
        p = picker.NativePicker()
        p.enabled = True
        p.viewport_id = 'p'
        p.cursor_x, p.cursor_y = 150, 150
        p.candidates = [{'kind': 'object'}]
        evt = MagicMock()
        evt.Viewport.Id = 'p'
        p.conduit.DrawForeground(evt)
        self.assertEqual(evt.Display.Draw2dLine.call_count, 10)
        weights = [c.args[3] for c in evt.Display.Draw2dLine.call_args_list]
        self.assertEqual(weights[:4], [6.0]*4)
        self.assertEqual(weights[4:8], [3.0]*4)
        self.assertEqual(evt.Display.Draw2dLine.call_args_list[-1].args[2], 'cyan')


if __name__ == '__main__':
    unittest.main()

"""Offline v0.4 functional-policy tests; Rhino integration must be tested on Mac."""
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import cursor_logic
import bridge_protocol
import topology_nav
import gamepad_bridge as bridge
from test_native_picker import picker


class CursorTests(unittest.TestCase):
    def test_full_stick_moves_right_at_nominal_rate(self):
        x, y, changed = cursor_logic.advance(200, 100, 1., 0., .05, 1000, 800)
        self.assertTrue(changed)
        self.assertAlmostEqual(x, 235.)
        self.assertEqual(y, 100)

    def test_precision_reduces_motion(self):
        fast = cursor_logic.advance(200, 100, 1., 0., .04, 1000, 800)
        slow = cursor_logic.advance(200, 100, 1., 0., .04, 1000, 800, True)
        self.assertAlmostEqual((slow[0] - 200) / (fast[0] - 200), .22)

    def test_screen_edge_clamped(self):
        x, y, _ = cursor_logic.advance(990, 790, 1., 1., .05, 1000, 800)
        self.assertEqual((x, y), (995., 795.))

    def test_invalid_data_does_not_move(self):
        self.assertEqual(cursor_logic.advance(50, 50, float('nan'), 1., .02, 100, 100),
                         (50, 50, False))

    def test_negative_y_moves_up_in_top_left_coords(self):
        x, y, moved = cursor_logic.advance(50, 50, 0., -1., .02, 200, 200)
        self.assertTrue(moved)
        self.assertLess(y, 50)
        self.assertEqual(x, 50)


class FakeCollection(list):
    @property
    def Count(self):
        return len(self)


class TopologyTests(unittest.TestCase):
    def make_brep(self):
        face0 = MagicMock()
        face0.AdjacentFaces.return_value = [1, 2, 1]
        face0.AdjacentEdges.return_value = [3, 5]
        face1 = MagicMock()
        face1.AdjacentEdges.return_value = [3, 9]
        face2 = MagicMock()
        face2.AdjacentEdges.return_value = [5, 7]
        edge3 = MagicMock()
        edge3.AdjacentFaces.return_value = [0, 1]
        edges = [MagicMock() for _ in range(10)]
        edges[3] = edge3
        return MagicMock(Faces=FakeCollection([face0, face1, face2]),
                         Edges=FakeCollection(edges))

    def test_faces_share_topology(self):
        b = self.make_brep()
        self.assertEqual(topology_nav.neighbor_indices(b, 'face', 0, 'up'), [('face', 1), ('face', 2)])

    def test_face_boundary_edges(self):
        b = self.make_brep()
        self.assertEqual(topology_nav.neighbor_indices(b, 'face', 0, 'down'), [('edge', 3), ('edge', 5)])

    def test_edge_incident_faces(self):
        b = self.make_brep()
        self.assertEqual(topology_nav.neighbor_indices(b, 'edge', 3, 'up'), [('face', 0), ('face', 1)])

    def test_edge_related_edges_not_claimed_edge_loop(self):
        b = self.make_brep()
        self.assertEqual(topology_nav.neighbor_indices(b, 'edge', 3, 'down'),
                         [('edge', 5), ('edge', 9)])

    def test_invalid_or_non_topological(self):
        b = self.make_brep()
        self.assertEqual(topology_nav.neighbor_indices(b, 'curve', -1, 'up'), [])


class CursorPickerTests(unittest.TestCase):
    def test_pick_transform_uses_given_cursor(self):
        vp = MagicMock()
        vp.Size.Width, vp.Size.Height = 1000, 800
        vp.GetFrustumLine.return_value = (True, object())
        doc = MagicMock()
        doc.Objects.PickObjects.return_value = []
        picker.ric.PickContext = MagicMock()
        picker.ric.PickStyle = MagicMock(CrossingPick='crossing')
        picker._native_pick_pass(doc, vp, 'all', 'wireframe', 250, 300)
        vp.GetPickTransform.assert_called_once_with((234, 284, 32, 32))

    def test_picker_cursor_starts_center_and_moves(self):
        p = picker.NativePicker()
        p.enabled = True
        p.cursor_x, p.cursor_y = 300., 200.
        p.last_pick_at = 1e20  # skip actual Rhino pick in policy test
        vp = MagicMock()
        vp.Size.Width, vp.Size.Height = 600, 400
        doc = MagicMock()
        p.move_cursor(vp, doc, 1., 0., .02)
        self.assertGreater(p.cursor_x, 300)
        self.assertTrue(p.cursor_pending)
        doc.Views.ActiveView.Redraw.assert_called_once()


class ProtocolTests(unittest.TestCase):
    def test_new_packets_accepted_and_older_ignored(self):
        self.assertTrue(bridge_protocol.compatible({'v': 1, 'bridge_tag': bridge_protocol.BRIDGE_TAG}))
        self.assertFalse(bridge_protocol.compatible({'v': 1, 'seq': 50}))
        self.assertFalse(bridge_protocol.compatible({'v': 1, 'bridge_tag': 'rhino_gamepad_v04'}))
        self.assertFalse(bridge_protocol.compatible({'v': 2, 'bridge_tag': 'rhino_gamepad_v04'}))


class LockTests(unittest.TestCase):
    def test_single_instance_blocks_duplicate_without_killing(self):
        if not hasattr(bridge, 'fcntl'):
            self.skipTest('macOS/Unix only')
        with tempfile.TemporaryDirectory() as path:
            lock_path = os.path.join(path, 'bridge.lock')
            with bridge.BridgeSingleInstance(lock_path):
                with self.assertRaises(RuntimeError):
                    with bridge.BridgeSingleInstance(lock_path):
                        pass
            with bridge.BridgeSingleInstance(lock_path):
                pass


if __name__ == '__main__':
    unittest.main()

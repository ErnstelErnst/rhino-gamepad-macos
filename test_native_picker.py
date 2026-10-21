"""Offline tests for independent picker policies; NOT in-Rhino integration tests."""
import importlib
import sys
import types
import unittest
from unittest.mock import MagicMock


def mock_import():
    rhino = types.ModuleType('Rhino')
    rhino.Geometry = types.ModuleType('Rhino.Geometry')
    rhino.DocObjects = types.ModuleType('Rhino.DocObjects')
    rhino.Input = types.ModuleType('Rhino.Input')
    rhino.Input.Custom = types.ModuleType('Rhino.Input.Custom')
    rhino.RhinoApp = types.SimpleNamespace(WriteLine=lambda s: None)
    rhino.Display = types.ModuleType('Rhino.Display')
    rhino.Display.DisplayConduit = type('DisplayConduit', (), {})
    rhino.Geometry.Curve = type('Curve', (), {})
    rhino.Geometry.ComponentIndexType = types.SimpleNamespace(BrepFace=1, BrepEdge=2)
    rhino.Geometry.ComponentIndex = lambda k, n: (k, n)
    sys.modules['Rhino'] = rhino
    sys.modules['Rhino.Geometry'] = rhino.Geometry
    sys.modules['Rhino.DocObjects'] = rhino.DocObjects
    sys.modules['Rhino.Input'] = rhino.Input
    sys.modules['Rhino.Input.Custom'] = rhino.Input.Custom
    sys.modules['Rhino.Display'] = rhino.Display
    system = types.ModuleType('System')
    drawing = types.ModuleType('System.Drawing')
    drawing.Point = lambda x, y: (x, y)
    drawing.Color = types.SimpleNamespace(Gold='gold', LimeGreen='lime')
    drawing.Rectangle = lambda x, y, w, h: (x, y, w, h)
    system.Drawing = drawing
    sys.modules['System'] = system
    sys.modules['System.Drawing'] = drawing
    sys.modules.pop('native_picker', None)
    return importlib.import_module('native_picker')


picker = mock_import()


class NativePickerPolicyTests(unittest.TestCase):
    def test_filters_do_not_claim_whole_brep_is_face(self):
        self.assertFalse(picker.mode_accepts('faces', 'object'))
        self.assertTrue(picker.mode_accepts('faces', 'face'))
        self.assertFalse(picker.mode_accepts('faces', 'edge'))

    def test_curves_accept_edges_not_brep_faces(self):
        self.assertTrue(picker.mode_accepts('curves', 'curve'))
        self.assertTrue(picker.mode_accepts('curves', 'edge'))
        self.assertFalse(picker.mode_accepts('curves', 'face'))

    def test_mode_all_supports_all_kinds(self):
        for kind in ('object', 'face', 'edge', 'curve'):
            self.assertTrue(picker.mode_accepts('all', kind))

    def test_subobject_detection(self):
        self.assertEqual(picker._kind_from_component(1, object()), 'face')
        self.assertEqual(picker._kind_from_component(2, object()), 'edge')
        self.assertEqual(picker._kind_from_component(9, picker.rg.Curve()), 'curve')
        self.assertEqual(picker._kind_from_component(9, object()), 'object')

    def test_fallback_does_not_fabricate_faces(self):
        candidates, scanned, capped = picker._approx_object_candidates(None, None, 'faces')
        self.assertEqual(candidates, [])
        self.assertEqual(scanned, 0)
        self.assertFalse(capped)

    def test_selection_does_not_change_model_on_missing_candidate(self):
        p = picker.NativePicker()
        doc = MagicMock()
        self.assertFalse(p.select(doc))
        doc.Objects.UnselectAll.assert_not_called()

    def test_approximate_entry_labeled(self):
        entry = {'id': 'a'*32, 'kind': 'object', 'index': -1, 'name': 'Block'}
        self.assertEqual(picker.describe(entry), 'object Block')

    def test_native_hit_deduplicated_after_serializing(self):
        p = picker.NativePicker()
        self.assertFalse(p.enabled)
        self.assertEqual(p.current(), None)


if __name__ == '__main__':
    unittest.main()

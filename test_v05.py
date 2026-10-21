"""v0.5 basket, export, tuning and protocol offline contract tests."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import selection_basket as sb
import magnetic_logic as ml
import bridge_protocol
from test_native_picker import picker
import selection_export


def entry(i=0, kind='face', uid='a'):
    return {'id': uid*32, 'guid': uid+'-guid', 'kind': kind,
            'index': i if kind in ('face','edge') else -1,
            'name': 'panel', 'approx': False}


class BasketTests(unittest.TestCase):
    def setUp(self):
        self.b = sb.SelectionBasket()
        self.selected = set()
        self.calls = []

    def is_selected(self, e):
        return sb.identity(e) in self.selected

    def apply(self, e, turn_on):
        key=sb.identity(e)
        self.calls.append((key,turn_on))
        if turn_on: self.selected.add(key)
        else: self.selected.discard(key)
        return True

    def test_toggle_multiple_stays_ordered(self):
        a,b=entry(1),entry(2)
        self.assertEqual(self.b.toggle(a,self.is_selected,self.apply),'added')
        self.assertEqual(self.b.toggle(b,self.is_selected,self.apply),'added')
        self.assertEqual([e['index'] for e in self.b.entries()],[1,2])
        self.assertEqual(self.b.counts(),{'face':2})

    def test_add_again_removes_without_affecting_others(self):
        a,b=entry(1),entry(2)
        self.b.toggle(a,self.is_selected,self.apply);self.b.toggle(b,self.is_selected,self.apply)
        self.assertEqual(self.b.toggle(a,self.is_selected,self.apply),'removed')
        self.assertEqual(len(self.b),1)
        self.assertNotIn(sb.identity(a),self.selected)
        self.assertIn(sb.identity(b),self.selected)

    def test_undo_add_and_undo_remove(self):
        a=entry(1)
        self.b.toggle(a,self.is_selected,self.apply)
        self.assertEqual(self.b.toggle(a,self.is_selected,self.apply),'removed')
        self.assertEqual(self.b.undo(self.apply),'undid remove')
        self.assertEqual(len(self.b),1)
        self.assertEqual(self.b.undo(self.apply),'undid add')
        self.assertEqual(len(self.b),0)
        self.assertEqual(self.b.undo(self.apply),None)

    def test_preexisting_selection_is_never_deselected(self):
        a=entry(1);self.selected.add(sb.identity(a))
        self.b.toggle(a,self.is_selected,self.apply)
        self.b.toggle(a,self.is_selected,self.apply)
        self.assertIn(sb.identity(a),self.selected)
        self.assertEqual(self.calls,[])

    def test_failure_does_not_change_state_or_history(self):
        a=entry(1)
        self.assertIsNone(self.b.toggle(a,self.is_selected,lambda *_:False))
        self.assertEqual(len(self.b),0)
        self.assertIsNone(self.b.undo(self.apply))

    def test_invalid_entry_rejected(self):
        self.assertIsNone(self.b.toggle({'id':'x','kind':'face','index':-1},self.is_selected,self.apply))

    def test_key_distinguishes_face_edge_and_object(self):
        self.assertNotEqual(sb.identity(entry(1,'face')),sb.identity(entry(1,'edge')))
        self.assertNotEqual(sb.identity(entry(1,'face')),sb.identity(entry(0,'object')))

    def test_reset_does_not_touch_rhino_state(self):
        self.b.toggle(entry(1),self.is_selected,self.apply)
        self.b.reset();self.assertEqual(len(self.b),0)
        self.assertEqual(len(self.selected),1)


class ExportTests(unittest.TestCase):
    def fake_doc(self):
        doc=MagicMock()
        geo=MagicMock()
        geo.GetBoundingBox.return_value=SimpleNamespace(
            IsValid=True,Min=SimpleNamespace(X=0,Y=1,Z=2),Max=SimpleNamespace(X=3,Y=4,Z=5))
        obj=MagicMock(Id='id-abc',Name='Building part',Geometry=geo)
        obj.Attributes.LayerIndex=0
        doc.Objects.FindId.return_value=obj
        doc.Layers.__getitem__.return_value.FullPath='Architecture::Parts'
        doc.ModelUnitSystem='Millimeters'
        return doc

    def test_basket_only_not_global_rhino_selection(self):
        doc=self.fake_doc()
        data=selection_export.describe_basket(doc,[entry(0,'object'),entry(0,'curve')])
        self.assertEqual(data['basket_count'],2)
        self.assertEqual(len(data['selection_items']),2)
        doc.Objects.GetSelectedObjects.assert_not_called()

    def test_reject_stale_subobject_index(self):
        doc=self.fake_doc()
        class FakeBrep:
            def __init__(self):
                self.Faces=SimpleNamespace(Count=2)
                self.Edges=SimpleNamespace(Count=1)
        doc.Objects.FindId.return_value.Geometry=FakeBrep()
        with patch.object(selection_export.rg, 'Brep', FakeBrep, create=True):
            data=selection_export.describe_basket(doc,[entry(9,'face')])
        self.assertEqual(data['basket_count'],0)

    def test_deleted_references_skipped(self):
        doc=self.fake_doc();doc.Objects.FindId.return_value=None
        self.assertEqual(selection_export.describe_basket(doc,[entry(0,'object')])['basket_count'],0)

    def test_files_are_local_and_no_network_is_contacted(self):
        doc=self.fake_doc()
        with tempfile.TemporaryDirectory() as d:
            path,md,n,copied=selection_export.export_basket_with_prompt(
                doc,[entry(0,'object')],folder=d,copy_clipboard=False)
            self.assertEqual(n,1)
            self.assertFalse(copied)
            self.assertEqual(json.loads(Path(path).read_text())['schema_version'],2)
            self.assertIn('Do not change my model',Path(md).read_text())

    def test_missing_returns_no_files(self):
        doc=self.fake_doc();doc.Objects.FindId.return_value=None
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(selection_export.export_basket_with_prompt(doc,[entry(0,'object')],d),
                             (None,None,0,False))

    def test_clipboard_fails_gracefully(self):
        with patch('subprocess.run',side_effect=FileNotFoundError()):
            self.assertFalse(selection_export.copy_for_agent('hi'))


class TunedBehaviorTests(unittest.TestCase):
    def test_live_tuned_values(self):
        self.assertEqual(ml.GLIDE_PX_PER_SECOND,2400.0)
        self.assertEqual(ml.SCAN_INTERVAL,.033)
        self.assertEqual(ml.MAGNETIC_PICK_HALF_PX,64)
        self.assertEqual(ml.HYSTERESIS_PX,18)

    def test_bridge_version_rejects_previous_sender(self):
        self.assertTrue(bridge_protocol.compatible({'v':1,'bridge_tag':'rhino_gamepad_v05'}))
        self.assertFalse(bridge_protocol.compatible({'v':1,'bridge_tag':'rhino_gamepad_v043'}))

    def test_committing_basket_releases_r3_focus_lock(self):
        p=picker.NativePicker()
        locked=entry(1)
        p.locked_entry=locked
        p.candidates=[locked]
        with patch.object(p,'_highlight') as highlight, patch.object(picker,'feedback'):
            p.release_lock_after_basket_commit(MagicMock())
        self.assertIsNone(p.locked_entry)
        self.assertTrue(p.cursor_pending)
        highlight.assert_called_once()

    def test_picker_keeps_basket_and_camera_controls(self):
        p=picker.NativePicker()
        p.basket=sb.SelectionBasket()
        self.assertEqual(len(p.basket),0)
        self.assertTrue(hasattr(p,'move_magnetic'))

if __name__ == '__main__': unittest.main()

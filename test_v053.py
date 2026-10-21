"""Offline tests, no Rhino, controller, macOS microphone or VS Code required."""
import json
import os
import tempfile
import unittest
import uuid
from unittest import mock
import voice_protocol as vp
import agent_handoff as ah

class VoiceInputTests(unittest.TestCase):
    def test_short_press_on_release(self):
        y=vp.YHold()
        self.assertIsNone(y.update(1,True,True))
        self.assertIsNone(y.update(1.4,True,True))
        self.assertEqual(y.update(1.45,False,True),'tap')
        self.assertIsNone(y.update(1.46,False,True))

    def test_long_press_once_and_no_tap(self):
        y=vp.YHold()
        self.assertIsNone(y.update(1,True,True))
        self.assertEqual(y.update(1.66,True,True),'voice')
        self.assertIsNone(y.update(1.67,True,True))
        self.assertIsNone(y.update(2,False,True))

    def test_disabled_context_drops_pending_y(self):
        y=vp.YHold()
        y.update(1,True,True)
        y.update(1.2,True,False)
        self.assertIsNone(y.update(1.3,False,True))

    def test_invalid_id_rejected(self):
        for invalid in ('../../bad', '', 'z'*32, 'A'*32, 9):
            with self.assertRaises(ValueError):
                vp.snapshot_path(invalid)

    def test_atomic_json(self):
        with tempfile.TemporaryDirectory() as d:
            dest=os.path.join(d,'sub','test.json')
            vp.atomic_json(dest, {'a':'ö','b':[1,2]})
            with open(dest) as stream:
                self.assertEqual(json.load(stream),{'a':'ö','b':[1,2]})
            self.assertEqual(os.stat(dest).st_mode & 0o777,0o600)
            vp.atomic_json(dest, {'a':7})
            with open(dest) as stream:
                self.assertEqual(json.load(stream),{'a':7})

    def test_wait_for_exact_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            ident=uuid.uuid4().hex
            fname=os.path.join(d,'sample.json')
            with open(fname,'w') as f: json.dump({'voice_request_id':ident,'basket':{'basket_count':1}},f)
            with mock.patch.object(vp,'snapshot_path',return_value=fname):
                self.assertEqual(ah.wait_for_snapshot(ident,timeout=.2), {'basket_count':1})

    def test_prompt_is_request_scoped_and_no_model_upload(self):
        p=ah.make_prompt('Offset by 4mm', {'units':'Millimeters','selection_items':[
            {'id':'guid-1','kind':'face','index':4,'layer':'A','name':'panel'},
            {'id':'guid-2','kind':'edge','index':3,'layer':'B','name':''}]})
        self.assertIn('Offset by 4mm',p)
        self.assertIn('guid-1',p)
        self.assertIn('face',p)
        self.assertIn('Millimeters',p)
        self.assertNotIn('Documents/',p)

    def test_empty_basket_allows_voice(self):
        self.assertIn('Basket count: 0',ah.make_prompt('What is the current view?',{'selection_items':[]}))

    def test_empty_prompt_rejected(self):
        with self.assertRaises(ValueError): ah.make_prompt('   ', {'selection_items':[]})

    def test_connection_refuses_non_loopback(self):
        with tempfile.TemporaryDirectory() as d:
            file=os.path.join(d,'connection.json')
            with open(file,'w') as f:json.dump({'host':'0.0.0.0','port':123,'token':'a'*64},f)
            with self.assertRaises(ValueError):ah.connection(file)

    def test_no_shortcut_shell_invocation(self):
        with mock.patch.object(ah.subprocess,'run') as run:
            run.return_value.returncode=0
            def write_out(argv,**kwargs):
                with open(argv[-1],'w') as f: f.write('Test from Shortcut')
                return mock.Mock(returncode=0)
            run.side_effect=write_out
            self.assertEqual(ah.shortcut_transcript('Rhino Agent Dictate'),'Test from Shortcut')
            self.assertEqual(run.call_args.args[0][:3], ['shortcuts','run','Rhino Agent Dictate'])

if __name__ == '__main__':unittest.main()

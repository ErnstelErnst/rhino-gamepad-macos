"""Offline tests for v0.5.5 dictation handoff settings and idempotent status."""
import unittest
from unittest import mock
import agent_handoff as ah

IDENT='0'*32
BASKET={'units':'Millimeters','selection_items':[{'id':'test-guid','kind':'face','index':4,'layer':'CAD'}]}
INFO={'host':'127.0.0.1','port':1234,'token':'x'*64,'autoSend':True}

class VoiceHandoffTests(unittest.TestCase):
    def test_auto_send_from_bound_extension_flag(self):
        def req(info,route,payload):
            if route=='status':return {'ok':True}
            if route=='draft':return {'ok':True,'state':'ready'}
            if route=='send':return {'ok':True,'state':'sent','submitted':True}
            self.fail('unexpected route '+route)
        with mock.patch.object(ah,'wait_for_snapshot',return_value=BASKET),\
             mock.patch.object(ah,'connection',return_value=INFO),\
             mock.patch.object(ah,'request',side_effect=req) as request,\
             mock.patch.object(ah,'status') as status:
            result=ah.do_draft(IDENT,'Analyze the face')
        self.assertEqual(result['state'],'sent')
        self.assertEqual([x.args[1] for x in request.call_args_list],['status','draft','send'])
        self.assertEqual(status.call_args.args[1],'sent')
    def test_manual_default_does_not_send(self):
        with mock.patch.object(ah,'wait_for_snapshot',return_value=BASKET),\
             mock.patch.object(ah,'connection',return_value={**INFO,'autoSend':False}),\
             mock.patch.object(ah,'request',side_effect=[{'ok':True},{'ok':True,'state':'ready'}]) as req,\
             mock.patch.object(ah,'status') as status:
            ah.do_draft(IDENT,'Test')
        self.assertEqual(req.call_count,2)
        self.assertEqual(status.call_args.args[1],'ready')
    def test_already_sent_never_sends_again(self):
        with mock.patch.object(ah,'wait_for_snapshot',return_value=BASKET),\
             mock.patch.object(ah,'connection',return_value=INFO),\
             mock.patch.object(ah,'request',side_effect=[{'ok':True},{'ok':True,'state':'sent','previous':True}]) as req,\
             mock.patch.object(ah,'status') as status:
            result=ah.do_draft(IDENT,'Test')
        self.assertEqual(result['state'],'sent')
        self.assertEqual(req.call_count,2)
        self.assertEqual(status.call_args.args[1],'sent')
    def test_failed_send_does_not_report_sent(self):
        with mock.patch.object(ah,'connection',return_value=INFO),\
             mock.patch.object(ah,'request',return_value={'ok':True,'state':'expired'}),\
             mock.patch.object(ah,'status') as status:
            with self.assertRaisesRegex(RuntimeError,'Draft cannot be sent'):
                ah.do_action(IDENT,'send')
        status.assert_not_called()

if __name__=='__main__': unittest.main()

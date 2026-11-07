import os,pathlib,sqlite3,sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from webhook_service import authorized,command_update,process
from monitor import ROOT,read_json,Telegram
from telegram_demo import Demo

class FakeStore:
 def __init__(self):self.ids=set();self.cool=set();self.results={}
 def snapshot(self):return {'sources':read_json(ROOT/'sources.json'),'posts':read_json(ROOT/'demo_samples.json')}
 def claim(self,ident,chat,command):
  if ident in self.ids:return False
  self.ids.add(ident);return True
 def cooldown(self,chat):
  if chat in self.cool:return False
  self.cool.add(chat);return True
 def finish(self,ident,count,status='sent'):self.results[ident]=(count,status)

class FakeTelegram:
 token='123456:testing'
 def __init__(self):self.calls=[]
 def call(self,method,payload):self.calls.append((method,payload));return {'message_id':len(self.calls)}
 def send(self,post,**kwargs):return Telegram.send(self,post,**kwargs)

class WebhookTests(unittest.TestCase):
 def setUp(self):
  self.store=FakeStore();self.client=FakeTelegram();self.sleep=patch('telegram_demo.time.sleep');self.sleep.start()
 def tearDown(self):self.sleep.stop()
 def update(self,text='/demo',ident=1,chat=123):return {'update_id':ident,'message':{'chat':{'id':chat,'type':'private'},'text':text}}
 def test_wrong_or_missing_secret_is_rejected(self):
  self.assertFalse(authorized(None,'secret'));self.assertFalse(authorized('',''));self.assertFalse(authorized('wrong','secret'));self.assertTrue(authorized('secret','secret'))
 def test_retry_is_not_replayed_across_handler_instances(self):
  a=process(self.update(),self.store,self.client);b=process(self.update(),self.store,FakeTelegram())
  self.assertEqual(a['messages_sent'],5);self.assertTrue(b['duplicate'])
 def test_new_person_receives_the_complete_saved_demo(self):
  process(self.update(),self.store,self.client);other=FakeTelegram();result=process(self.update(ident=2,chat=456),self.store,other)
  self.assertEqual(result['messages_sent'],5);self.assertTrue(all(p['chat_id']=='456' for _,p in other.calls))
 def test_same_person_can_replay_with_new_command_after_cooldown(self):
  process(self.update(),self.store,self.client);self.store.cool.clear();other=FakeTelegram()
  self.assertEqual(process(self.update(ident=2),self.store,other)['messages_sent'],5)
 def test_cooldown_shared_between_invocations(self):
  process(self.update(),self.store,self.client);other=FakeTelegram();process(self.update(ident=2),self.store,other)
  self.assertEqual(len(other.calls),1);self.assertIn('30',other.calls[0][1]['text'])
 def test_start_has_no_session_expiry_and_plain_start_works(self):
  process(self.update('start'),self.store,self.client)
  self.assertIn('/demo',self.client.calls[0][1]['text']);self.assertNotIn('جلسة التجربة حتى',self.client.calls[0][1]['text'])
 def test_ambiguous_send_is_not_repeated(self):
  with patch.object(self.client,'call',side_effect=RuntimeError('network failure')):result=process(self.update(),self.store,self.client)
  self.assertTrue(result['delivery_uncertain']);self.assertEqual(self.store.results[1][1],'delivery_uncertain')
  other=FakeTelegram();self.assertTrue(process(self.update(),self.store,other)['duplicate']);self.assertEqual(other.calls,[])
 def test_group_and_noncommands_do_not_touch_store(self):
  update=self.update();update['message']['chat']['type']='group'
  self.assertIsNone(command_update(update));self.assertIsNone(command_update(self.update('hello')))
if __name__=='__main__':unittest.main()

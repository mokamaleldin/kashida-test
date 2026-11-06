import pathlib,sqlite3,sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from telegram_demo import Demo
from monitor import ROOT,read_json,Telegram

class FakeTelegram:
 def __init__(self):self.calls=[]
 def call(self,method,payload):self.calls.append((method,payload));return {'message_id':len(self.calls)}
 def send(self,post,**kwargs):return Telegram.send(self,post,**kwargs)

class DemoTests(unittest.TestCase):
 def setUp(self):
  self.client=FakeTelegram();self.db=sqlite3.connect(':memory:')
  self.demo=Demo(self.client,read_json(ROOT/'sources.json'),read_json(ROOT/'demo_samples.json'),self.db,'2026-11-06T12:00:00Z')
  self.sleep=patch('telegram_demo.time.sleep');self.sleep.start()
 def tearDown(self):self.sleep.stop();self.db.close()
 def incoming(self,text,ident=1,kind='private'):
  return {'update_id':ident,'message':{'chat':{'id':12345,'type':kind},'text':text,'from':{'is_bot':False}}}
 def test_start_only_instructions_not_news(self):
  result=self.demo.handle(self.incoming('/start'));self.assertEqual(len(result),1)
  self.assertIn('/demo',self.client.calls[0][1]['text']);self.assertNotIn('فتح المنشور الأصلي',self.client.calls[0][1]['text'])
 def test_demo_one_saved_sample_per_source(self):
  result=self.demo.handle(self.incoming('/demo'));self.assertEqual(len(result),5)
  for _,payload in self.client.calls:self.assertNotIn('عينة محفوظة للاختبار',payload['text']);self.assertNotIn('مُعاد مشاركته',payload['text']);self.assertIn('فتح المنشور الأصلي',payload['text'])
  self.assertEqual(len({p['text'] for _,p in self.client.calls}),5)
 def test_same_update_not_delivered_twice(self):
  self.demo.handle(self.incoming('/demo'));self.demo.handle(self.incoming('/demo'));self.assertEqual(len(self.client.calls),5)
 def test_replay_requires_new_command_and_cooldown(self):
  with patch('telegram_demo.time.time',return_value=100):self.demo.handle(self.incoming('/demo',1))
  with patch('telegram_demo.time.time',return_value=110):self.demo.handle(self.incoming('/demo',2))
  self.assertEqual(len(self.client.calls),6);self.assertIn('انتظر30',self.client.calls[-1][1]['text'])
  with patch('telegram_demo.time.time',return_value=131):self.demo.handle(self.incoming('/demo',3))
  self.assertEqual(len(self.client.calls),11)
 def test_single_source_stays_single(self):
  self.demo.handle(self.incoming('/sample rassd'));self.assertEqual(len(self.client.calls),1)
  self.assertIn('شبكة رصد',self.client.calls[0][1]['text'])
 def test_groups_and_noncommands_ignored(self):
  self.demo.handle(self.incoming('/demo',1,'group'));self.demo.handle(self.incoming('hello',2));self.assertEqual(self.client.calls,[])
 def test_snapshot_has_no_group_bodies_or_direct_media(self):
  for p in self.demo.samples:
   self.assertEqual(p['media'],[])
   if p['source_id'].startswith('group-'):self.assertIn('نص المنشور وملفه غير مضمنين',p['text'])
   else:self.assertLessEqual(len(p['text'].split()),25)

if __name__=='__main__':unittest.main()

import pathlib,sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from monitor import Telegram,message,format_timestamp,utf16_units,stamp,TransportError,message_parts
from source_sample_check import latest_for_source,deliver_samples

def post(source='one',ident='1',published='2026-11-06T07:14:36Z',text='خبر تجريبي'):
 return {'source_id':source,'source_name':'مصدر تجريبي','platform':'Facebook','id':ident,'url':'https://www.facebook.com/test/posts/'+ident,'media_type':'photo','media':[{'type':'photo','url':'https://scontent.fbcdn.net/picture.jpg'}],'published_at':published,'collected_at':'2026-11-06T07:20:00Z','text':text,'shared_post':False}

class MessageTests(unittest.TestCase):
 def test_winter_cairo_date_is_readable_and_not_iso(self):
  actual=format_timestamp('2026-11-06T07:14:36Z')
  self.assertEqual(actual,'الجمعة 6 نوفمبر 2026، 9:14 صباحًا (القاهرة)');self.assertNotIn('T07:',actual)
 def test_summer_cairo_uses_daylight_saving(self):
  self.assertIn('10:00 صباحًا',format_timestamp('2026-07-06T07:00:00Z'))
 def test_missing_date_is_not_replaced_with_collection_time(self):self.assertEqual(format_timestamp(None),'غير متاح')
 def test_untrusted_text_escaped_and_metadata_preserved(self):
  p=post(text='<script>bad</script> & <b>raw</b>');text=message(p)
  self.assertIn('&lt;script&gt;',text);self.assertNotIn('<script>',text)
  for value in ['Facebook','صورة','النشر','الرصد',p['url']]:self.assertIn(value,text)
 def test_long_photo_caption_keeps_original_link_and_valid_html(self):
  p=post(text='😀 <نص> & '*2000);text=message(p,max_units=1000)
  self.assertLessEqual(utf16_units(text),1000);self.assertTrue(text.endswith('</a>'));self.assertIn(p['url'],text)
 def test_photo_payload_uses_html_without_slicing_link(self):
  client=Telegram('123456789:'+'x'*35,'1234567890')
  with patch.object(client,'call',return_value={'message_id':1,'photo':[{}]}) as call:
   client.send(post(text='نص طويل '*1000));method,payload=call.call_args.args
  self.assertEqual(call.call_args_list[0].args[0],'sendPhoto');self.assertEqual(payload['parse_mode'],'HTML');self.assertIn('/posts/1',payload.get('caption',payload.get('text','')))
 def test_requested_notes_are_removed(self):
  text=message({**post(),'sample_note':'عينة محفوظة للاختبار؛ ليست تحديثًا مباشرًا','shared_post':True})
  self.assertNotIn('عينة محفوظة',text);self.assertNotIn('مُعاد مشاركته',text)
 def test_long_article_is_sent_in_full_after_photo(self):
  client=Telegram('123456789:'+'x'*35,'1234567890');body='خبر طويل '*1000
  with patch.object(client,'call',return_value={'message_id':1,'photo':[{}]}) as call,patch('monitor.time.sleep'):
   client.send(post(text=body),chat_id='987654321')
  self.assertEqual(call.call_args_list[0].args[0],'sendPhoto')
  payloads=[c.args[1] for c in call.call_args_list];self.assertTrue(all(p['chat_id']=='987654321' for p in payloads))
  texts=[p['text'] for p in payloads if 'text' in p]
  self.assertEqual(sum(t.count('خبر') for t in texts),1000);self.assertTrue(all(utf16_units(t)<=3900 for t in texts))
 def test_unavailable_video_uses_returned_photo(self):
  client=Telegram('123456789:'+'x'*35,'1234567890');p=post();p['media_type']='video';p['media'].insert(0,{'type':'video','url':'https://scontent.fbcdn.net/clip.mp4'})
  with patch.object(client,'call',side_effect=[TransportError(400),{'message_id':2,'photo':[{'file_id':'cached-photo'}]}]) as call,patch('monitor.time.sleep'):
   client.send(p)
  self.assertEqual([c.args[0] for c in call.call_args_list],['sendVideo','sendPhoto']);self.assertEqual(p['telegram_media']['file_id'],'cached-photo')
 def test_cached_telegram_file_is_reused(self):
  client=Telegram('123456789:'+'x'*35,'1234567890');p={**post(),'telegram_media':{'type':'photo','file_id':'cached-photo'}}
  with patch.object(client,'call',return_value={'message_id':1,'photo':[{'file_id':'cached-photo'}]}) as call:client.send(p)
  self.assertEqual(call.call_args.args[1]['photo'],'cached-photo')
 def test_latest_per_source_not_first_response(self):
  old=post(published='2026-11-01T00:00:00Z');new=post(ident='2')
  self.assertEqual(latest_for_source([old,new],'one')['id'],'2')
 def test_source_samples_have_hard_five_message_cap(self):
  class Fake:
   chat='123'
   def __init__(self):self.calls=[]
   def call(self,method,payload):self.calls.append((method,payload));return {'message_id':len(self.calls)}
   def send(self,p):self.calls.append(('send',p));return {'message_id':len(self.calls),'photo':[{}]}
  client=Fake();sources=[{'id':str(i),'name':'مصدر '+str(i)} for i in range(7)]
  rows=[post(source=str(i),ident=str(i),published=stamp()) for i in range(7)]
  result=deliver_samples(client,sources,rows);self.assertEqual(len(result),5);self.assertEqual(len(client.calls),5)
  self.assertEqual(len(set(x['source_id'] for x in result)),5)
if __name__=='__main__':unittest.main()

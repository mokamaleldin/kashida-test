import datetime as dt,json,pathlib,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from monitor import *
SOURCE={'id':'test','name':'مصدر تجريبي','kind':'group','url':'https://www.facebook.com/groups/123'}

def raw(text='خبر محلي',kind='Photo',ident='1',published='2026-11-06T08:00:00Z'):
 return {'details':{'post_id':ident,'post_link':'https://www.facebook.com/groups/123/posts/'+ident,'comments_count':'2'},'values':{'text':text,'is_media':kind,'publish_time':published},'reactions':{'total_reaction_count':'10'},'attachments':[]}

@patch('monitor.get_usage', return_value={'creditsUsed':0,'creditsRemaining':197})
class MonitorTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.db=connect(pathlib.Path(self.tmp.name)/'state.sqlite')
 def tearDown(self):self.db.close();self.tmp.cleanup()
 def test_identity_deduplicates_but_keeps_updated_content(self,usage_mock):
  p=normalize(raw(),SOURCE,stamp());self.assertTrue(upsert(self.db,p));p['text']='نص محدث';self.assertFalse(upsert(self.db,p));self.assertEqual(len(all_posts(self.db)),1);self.assertEqual(all_posts(self.db)[0]['text'],'نص محدث')
 def test_identical_text_on_two_sources_is_retained(self,usage_mock):
  p=normalize(raw(),SOURCE,stamp());upsert(self.db,p);q={**p,'source_id':'second'};upsert(self.db,q);self.assertEqual(len(all_posts(self.db)),2)
 def test_original_time_not_ingestion_time(self,usage_mock):
  p=normalize(raw(),SOURCE,'2026-11-07T00:00:00+00:00');self.assertEqual(p['published_at'],'2026-11-06T08:00:00+00:00');self.assertNotEqual(p['published_at'],p['collected_at'])
 def test_missing_text_and_metrics_remain_missing(self,usage_mock):
  r=raw(None);r['reactions']={};p=normalize(r,SOURCE,stamp());self.assertIsNone(p['text']);self.assertIsNone(p['reactions'])
 def test_video_without_file_is_not_fake_downloadable_video(self,usage_mock):
  p=normalize(raw(kind='Video'),SOURCE,stamp());self.assertEqual(p['media_type'],'video');self.assertFalse(p['media_url_available'])
 def test_nested_media_and_no_avatar_extraction(self,usage_mock):
  r=raw();r['attachments']={'all_subattachments':{'nodes':[{'media':{'image':{'uri':'https://scontent.fbcdn.net/image.jpg'}}}]}};r['user_details']={'avatar':'https://scontent.fbcdn.net/avatar.jpg'}
  p=normalize(r,SOURCE,stamp());self.assertEqual(len(p['media']),1);self.assertTrue(p['media_url_available'])
 def test_keyword_media_and_time_filters(self,usage_mock):
  p=normalize(raw('إعلان بيع في القاهرة'),SOURCE,stamp());reasons=filter_post(p,{'media_types':['video'],'include_any':['الاسكندرية'],'exclude_any':['بيع']},parse_time('2026-11-06T09:00:00Z'));self.assertEqual(len(reasons),4)
 def test_media_and_post_urls_reject_local_or_javascript(self,usage_mock):
  self.assertIsNone(safe_url('http://127.0.0.1/admin',True));self.assertIsNone(safe_url('javascript:alert(1)'));self.assertIsNone(safe_url('https://fbcdn.net.attacker.example/x',True))
 def test_budget_and_deducted_credit_field(self,usage_mock):
  payload={'data':{'posts':[raw()], 'page_info':{'has_next':True}},'meta':{'creditsCharged':1,'creditsRemaining':197}}
  sources=[SOURCE,{**SOURCE,'id':'two'}]
  with patch('monitor.request_json',return_value=(payload,{'x-socialapis-credits-used':'50'})) as network:
   r=collect(self.db,sources,{'limit':3,'monthly_credit_cap':1},'test-token',2)
   self.assertEqual(network.call_count,1);self.assertEqual(r['credits_charged'],1);self.assertEqual(r['remaining'],197)
 def test_auth_failure_stops_remaining_sources(self,usage_mock):
  with patch('monitor.request_json',side_effect=TransportError(401)) as network:
   r=collect(self.db,[SOURCE,{**SOURCE,'id':'two'}],{},'test',2)
   self.assertEqual(network.call_count,1);self.assertEqual(r['requests'],1)
 def test_failed_telegram_is_not_marked_sent_or_auto_retried(self,usage_mock):
  p=normalize(raw(published=stamp()),SOURCE,stamp());upsert(self.db,p)
  class Bot:
   chat='123'
   def verify(self):return {'chat_verified':True}
   def send(self,post):raise TransportError()
  self.assertEqual(send_pending(self.db,Bot(),{},1)['sent'],0)
  self.assertEqual(self.db.execute('SELECT status FROM deliveries').fetchone()[0],'unknown')
  self.assertEqual(send_pending(self.db,Bot(),{},1)['sent'],0)
 def test_successful_telegram_not_sent_twice(self,usage_mock):
  p=normalize(raw(published=stamp()),SOURCE,stamp());upsert(self.db,p)
  class Bot:
   chat='123'
   def verify(self):return {'chat_verified':True}
   def send(self,post):return {'message_id':42}
  self.assertEqual(send_pending(self.db,Bot(),{},1)['sent'],1);self.assertEqual(send_pending(self.db,Bot(),{},1)['sent'],0)
 def test_provider_date_query_uses_actual_required_day_format(self,usage_mock):
  payload={'data':{'posts':[],'page_info':{}},'meta':{'creditsCharged':1}}
  with patch('monitor.request_json',return_value=(payload,{})) as network:
   collect(self.db,[SOURCE],{},'test',1)
   query=urllib.parse.parse_qs(urllib.parse.urlsplit(network.call_args.args[0]).query)
   self.assertRegex(query['after_time'][0],r'^\d{4}-\d{2}-\d{2}$')
 def test_telegram_credentials_trim_copy_paste_whitespace(self,usage_mock):
  token='123456789:unit_test_token_has_more_than_20_chars'
  client=Telegram(' \n'+token+'\n',' 1234567890\n')
  self.assertEqual(client.token,token);self.assertEqual(client.chat,'1234567890')
 def test_telegram_invalid_token_error_does_not_echo_secret(self,usage_mock):
  bad='invalid secret value\ninside'
  with self.assertRaises(ProbeError) as error:Telegram(bad,'1234567890')
  self.assertNotIn(bad,str(error.exception));self.assertIn('token format',str(error.exception))
 def test_cost_does_not_invent_enterprise_price(self,usage_mock):
  self.assertEqual(costs(60,30)['credits'],86400);self.assertEqual(costs(60,30)['plan']['monthly_usd'],179);self.assertIsNone(costs(60,15)['plan']);self.assertEqual(costs(60,30,2)['credits'],172800)
if __name__=='__main__':unittest.main()

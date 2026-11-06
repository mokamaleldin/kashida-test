import datetime as dt,pathlib,sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from trends_probe import parse_public_x,parse_google,facebook_sample,render_messages,trial_enabled,digest_messages,collect_once
from monitor import ProbeError,stamp,now

def post(source='a',ident='1',text='منتخب مصر يستعد للمباراة #منتخب_مصر',age=1):
 return {'source_id':source,'source_name':source,'id':ident,'text':text,'url':'https://www.facebook.com/test/posts/'+ident,'published_at':stamp(now()-dt.timedelta(hours=age)),'collected_at':stamp()}

class TrendTests(unittest.TestCase):
 def test_public_list_checks_country_and_ignores_second_table(self):
  raw='<h1>Twitter Trends in Egypt</h1><table><tr><td><a href="/egypt/trend/%23test/">#اختبار</a></td></tr><tr><td><a href="/egypt/trend/topic/">منتخب مصر</a></td></tr></table><table><tr><td><a href="/trend/old/">old</a></td></tr></table>'
  rows=parse_public_x(raw.encode());self.assertEqual(len(rows),2);self.assertEqual(rows[0]['kind'],'hashtag');self.assertEqual(rows[1]['kind'],'topic')
  with self.assertRaises(ProbeError):parse_public_x(raw.replace('Egypt','United States').encode())
 def test_google_queries_stay_search_queries(self):
  raw=b'<rss xmlns:ht="https://trends.google.com/trending/rss"><channel><item><title>Egypt News</title><pubDate>Fri, 06 Nov 2026 12:00:00 +0000</pubDate><ht:approx_traffic>1000+</ht:approx_traffic></item></channel></rss>'
  row=parse_google(raw)[0];self.assertEqual(row['kind'],'search_topic');self.assertEqual(row['traffic_label'],'1000+');self.assertIn('geo=EG',row['url'])
 def test_hashtags_count_posts_not_repetitions_inside_one_post(self):
  data=facebook_sample([post(text='#منتخب_مصر #منتخب_مصر')]);self.assertEqual(data['hashtags'][0]['post_count'],1)
 def test_repeated_phrase_needs_different_sources(self):
  data=facebook_sample([post(ident='1'),post(ident='2')]);self.assertEqual(data['repeated_phrases'],[])
  data=facebook_sample([post(ident='1'),post(source='b',ident='2')]);self.assertTrue(data['repeated_phrases']);self.assertFalse(data['growth_measured'])
 def test_stale_and_duplicate_posts_cannot_inflate_current_counts(self):
  p=post();data=facebook_sample([p,p,post(source='b',ident='2',age=48)])
  self.assertEqual(data['cached_posts'],2);self.assertEqual(data['posts_last_24h'],1)
 def test_failed_sources_are_visible_not_replaced_with_fabricated_topics(self):
  texts=render_messages({'created_at':stamp(),'sources':{'x':{'error':'HTTP 403'},'google':{'error':'HTTP 429'},'facebook':{'error':'no cache'}}})
  self.assertEqual(len(texts),3);self.assertIn('لم تكتمل',texts[0]);self.assertIn('تعذر',texts[2])
 def test_external_topic_names_are_html_escaped(self):
  text=render_messages({'created_at':stamp(),'sources':{'x':{'items':[{'name':'<b>unsafe</b>','kind':'topic'}],'provider':'GetDayTrends'}}})[0]
  self.assertIn('&lt;b&gt;',text);self.assertNotIn('<b>unsafe',text)
 def test_daily_trial_stops_at_configured_local_date(self):
  self.assertTrue(trial_enabled(dt.datetime(2026,11,13,12,tzinfo=dt.timezone.utc)))
  self.assertFalse(trial_enabled(dt.datetime(2026,11,13,22,tzinfo=dt.timezone.utc)))
 def test_daily_digest_is_one_message_when_it_fits(self):
  parts=digest_messages({'created_at':stamp(),'sources':{}});self.assertEqual(len(parts),1)
 def test_malformed_api_secret_cannot_appear_in_error(self):
  secret='private-value\nbad-line'
  with patch.dict('os.environ',{'X_BEARER_TOKEN':secret}):
   with self.assertRaises(ProbeError) as error:collect_once()
  self.assertNotIn(secret,str(error.exception))

if __name__=='__main__':unittest.main()

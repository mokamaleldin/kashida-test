import pathlib,sys,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from topic_links import link_topics,all_topics
from trends_probe import facebook_sample
from monitor import stamp

def p(ident,text,source='one'):
 return {'id':ident,'text':text,'source_id':source,'source_name':source,'url':'https://www.facebook.com/test/posts/'+ident,'published_at':stamp(),'collected_at':stamp()}

class TopicTests(unittest.TestCase):
 def test_related_reports_link_evidence_across_publishers(self):
  rows=[p('1','منتخب مصر يستعد لمواجهة البرتغال في مباراة ودية'),p('2','حسام حسن يعلن قائمة منتخب مصر لمباراة البرتغال','two')]
  groups=link_topics(rows,[{'name':'منتخب مصر','platform':'X'}])
  self.assertEqual(len(groups),1);self.assertEqual(groups[0]['title'],'منتخب مصر');self.assertEqual(groups[0]['source_count'],2)
  self.assertEqual({e['url'] for e in groups[0]['evidence']},{x['url'] for x in rows})
 def test_generic_news_words_do_not_link_unrelated_stories(self):
  rows=[p('1','عاجل من مصر اليوم اسعار البنزين الجديدة في محطات الوقود'),p('2','عاجل من مصر اليوم حسام حسن يعلن قائمة المنتخب البرتغال')]
  self.assertEqual(link_topics(rows),[])
 def test_bridge_post_cannot_merge_unrelated_topics(self):
  rows=[p('1','منتخب مصر البرتغال يستعد لمباراة ودية'),p('2','منتخب مصر البرتغال اسعار الدولار البنوك'),p('3','اسعار الدولار البنوك وقرض التمويل')]
  self.assertTrue(all(g['post_count']<3 for g in link_topics(rows)))
 def test_single_reports_remain_visible_without_claiming_a_link(self):
  rows=[p('1','افتتاح مكتبة جديدة للقراءة بالمدينة'),p('2','حسام حسن يعلن قائمة المنتخب البرتغال')]
  topics=all_topics(rows,link_topics(rows));self.assertEqual(len(topics),2);self.assertTrue(all(t['post_count']==1 for t in topics))
 def test_brand_hashtag_is_not_a_news_trend(self):
  row=p('1','خبر عن افتتاح جديد #مزيد #القاهرة');row['source_name']='مزيد'
  self.assertEqual([t['name'] for t in facebook_sample([row])['hashtags']],['#القاهرة'])

if __name__=='__main__':unittest.main()

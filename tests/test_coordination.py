import datetime as dt,io,pathlib,sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from coordination_probe import analyze,text_evidence,text_normalize,image_fingerprint,image_evidence,collect_image_hashes,identity
try:
 from PIL import Image,ImageDraw
 HAS_IMAGES=True
except ImportError:HAS_IMAGES=False

BODIES=[
 'افتتحت مديرية التعليم مكتبة رقمية جديدة تضم كتب العلوم واللغات والفنون وتتيح للطلاب استعارة المراجع والبحث داخل الفهارس باستخدام أجهزة المدرسة الحديثة',
 'أطلق المستشفى حملة تطعيم مجانية للأطفال بالتعاون مع الأطباء والممرضين لتوفير الرعاية الصحية والكشف المبكر وحماية الأسر من العدوى والأمراض الموسمية المنتشرة',
 'انتهت هيئة المياه من إصلاح محطة الري وتغيير المضخات وصيانة المواسير وتنظيف القنوات الزراعية لزيادة تدفق المياه وتوفير احتياجات المزارعين والحقول البعيدة']

def post(ident,source='a',body=BODIES[0],hour=0,seconds=0,verified=True):
 when=dt.datetime(2026,11,6,8,tzinfo=dt.timezone.utc)+dt.timedelta(hours=hour,seconds=seconds)
 return {'platform':'Facebook','source_id':source,'source_name':'مصدر اختبار '+source,'id':ident,'url':'https://example.test/posts/'+ident,'text':body,'published_at':when.isoformat(),'collected_at':when.isoformat(),'time_semantics_verified':verified,'shared_post':False,'media_type':'text','media':[]}

class CoordinationTests(unittest.TestCase):
 def test_identical_post_is_deduplicated_not_counted_as_coordination(self):
  p=post('one');r=analyze([p,p]);self.assertEqual(r['posts_analyzed'],1);self.assertEqual(r['pairs'],[])
 def test_exact_copy_and_near_time_are_observations_not_an_accusation(self):
  r=analyze([post('one'),post('two','b',seconds=90)])
  self.assertEqual(r['counts']['exact_text_pairs'],1);self.assertEqual(r['pairs'][0]['gap_seconds'],90)
  self.assertEqual(r['patterns'],[]);self.assertFalse(r['coordination_or_bot_identity_proven'])
 def test_small_edit_is_detected_but_same_topic_is_not_enough(self):
  self.assertEqual(text_evidence(BODIES[0],BODIES[0]+' وذلك حسب البيان')['kind'],'near_text')
  self.assertIsNone(text_evidence('يتابع المحرر مباراة المنتخب الوطني مع الفريق البرتغالي الليلة','أعلنت وزارة الرياضة موعد سفر لاعبي المنتخب المصري استعدادا للقاء'))
 def test_numbers_and_negation_are_preserved_and_flagged(self):
  first=BODIES[0]+' وتبدأ الدراسة يوم20';second=BODIES[0]+' ولا تبدأ الدراسة يوم21'
  # Explicit separate negation token is retained by the normalizer.
  changed=text_evidence(first,BODIES[0]+' لا تبدأ الدراسة يوم21')
  self.assertTrue(changed['numbers_changed']);self.assertTrue(changed['negation_changed']);self.assertEqual(changed['kind'],'near_text')
  self.assertEqual(text_normalize('عدد الطلاب١٢٣'),text_normalize('عدد الطلاب123'))
 def test_ingestion_time_never_substitutes_missing_publication_time(self):
  a,b=post('a'),post('b','b');a['published_at']=None;b['published_at']=None
  pair=analyze([a,b])['pairs'][0];self.assertIsNone(pair['gap_seconds']);self.assertFalse(pair['within_window'])
 def test_same_text_reposted_many_times_is_one_content_family(self):
  rows=[post(source+str(i),source,hour=i) for i in range(3) for source in ['a','b']]
  self.assertEqual(analyze(rows)['patterns'],[])
 def test_three_distinct_content_families_in_separate_windows_are_reviewable(self):
  rows=[post(source+str(i),source,body=body,hour=i,seconds=60 if source=='b' else 0) for i,body in enumerate(BODIES) for source in ['a','b']]
  r=analyze(rows);self.assertEqual(len(r['patterns']),1);self.assertEqual(r['patterns'][0]['different_content_families'],3)
  self.assertFalse(r['patterns'][0]['intent_determined'])
 def test_unverified_time_is_explicit(self):
  r=analyze([post('a',verified=False),post('b','b',verified=False)])
  self.assertIn('publication_time_semantics_unverified',r['pairs'][0]['context']);self.assertEqual(r['posts_with_verified_publication_time'],0)
 def test_generic_greetings_are_not_promoted_to_recurring_pattern(self):
  rows=[post(s+str(i),s,body='جمعة مباركة '+body,hour=i) for i,body in enumerate(BODIES) for s in ['a','b']]
  r=analyze(rows);self.assertEqual(r['patterns'],[]);self.assertTrue(all('generic_phrase_present' in p['context'] for p in r['pairs']))
 def test_common_original_post_id_is_not_independent_sources(self):
  r=analyze([post('same','a'),post('same','b')]);self.assertIn('same_original_post_id',r['pairs'][0]['context'])
 def test_shared_image_url_downloaded_once_still_maps_to_both_posts(self):
  a,b=post('a'),post('b','b')
  for row in [a,b]:row['media_type']='photo';row['media']=[{'type':'photo','url':'https://scontent.fbcdn.net/a.jpg'}]
  with patch('coordination_probe.fetch_image',return_value=({'sha256':'a','dhash':'0','width':32,'height':32,'low_information':False},None)) as fetch:
   images,status=collect_image_hashes([a,b],8)
  self.assertEqual(fetch.call_count,1);self.assertEqual(len(images),2);self.assertEqual(status['decoded'],1)

@unittest.skipUnless(HAS_IMAGES,'Optional Pillow image dependency not installed')
class ImageTests(unittest.TestCase):
 def test_reencoded_image_has_similar_visual_hash_but_different_bytes(self):
  image=Image.new('L',(128,128));draw=ImageDraw.Draw(image)
  for y in range(8):
   for x in range(8):draw.rectangle((x*16,y*16,x*16+15,y*16+15),fill=(x*37+y*83)%256)
  png,jpeg=io.BytesIO(),io.BytesIO();image.save(png,format='PNG');image.save(jpeg,format='JPEG',quality=90)
  first,second=image_fingerprint(png.getvalue()),image_fingerprint(jpeg.getvalue())
  self.assertNotEqual(first['sha256'],second['sha256']);self.assertEqual(image_evidence(first,second)['kind'],'similar_image')
 def test_flat_images_do_not_create_perceptual_matches(self):
  values=[]
  for color in [220,240]:
   raw=io.BytesIO();Image.new('L',(64,64),color).save(raw,format='PNG');values.append(image_fingerprint(raw.getvalue()))
  self.assertIsNone(image_evidence(*values))

if __name__=='__main__':unittest.main()

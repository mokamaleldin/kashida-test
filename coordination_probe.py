"""Evidence-first source co-activity experiment; never labels people/bots or intent."""
import argparse,collections,datetime as dt,difflib,hashlib,io,itertools,json,re,unicodedata,urllib.error,urllib.request,warnings
from concurrent.futures import ThreadPoolExecutor
from monitor import ROOT,ProbeError,NoRedirect,parse_time,read_json,write_json,stamp,safe_url

WINDOW_SECONDS=300
NEGATION={'لا','لم','لن','ليس','ليست','مش','مافيش'}
COMMON=[r'جمع[ةه]\s+مبارك[ةه]',r'صباح\s+الخير',r'مساء\s+الخير',r'صلوا\s+علي\s+النبي',r'اللهم\s+صل']

def text_normalize(text):
 text=unicodedata.normalize('NFKC',text or '').lower()
 text=re.sub(r'[\u200b-\u200f\u202a-\u202e\u2066-\u2069\u064b-\u065f\u0670\u0640]','',text)
 text=text.replace('أ','ا').replace('إ','ا').replace('آ','ا').replace('ى','ي')
 text=text.translate(str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹','01234567890123456789'))
 # Keep numbers and negation: similarity must not silently erase changed meaning.
 return ' '.join(re.findall(r'\w+',text))

def tokens(text):return text_normalize(text).split()
def shingles(words,size=3):return {tuple(words[i:i+size]) for i in range(len(words)-size+1)}
def identity(p):return (p.get('platform','Facebook'),p['source_id'],p['id'])
def source_key(p):return p.get('platform','Facebook')+':'+p['source_id']

def text_evidence(a,b):
 na,nb=text_normalize(a),text_normalize(b);wa,wb=na.split(),nb.split()
 if min(len(wa),len(wb))<8 or min(len(na),len(nb))<40:return None
 exact=na==nb
 if not exact and (min(len(wa),len(wb))<12 or max(len(na),len(nb))>20000):return None
 sa,sb=shingles(wa),shingles(wb);jaccard=len(sa&sb)/len(sa|sb) if sa|sb else 0
 if not exact and jaccard<0.72:return None
 ratio=1.0 if exact else difflib.SequenceMatcher(None,na,nb,autojunk=False).ratio()
 if not exact and ratio<0.88:return None
 generic=any(re.search(pattern,na) and re.search(pattern,nb) for pattern in COMMON)
 return {'kind':'exact_text' if exact else 'near_text','jaccard':round(jaccard,3),'character_similarity':round(ratio,3),'generic_phrase_present':generic,'numbers_changed':set(re.findall(r'\d+',na))!=set(re.findall(r'\d+',nb)),'negation_changed':(set(wa)&NEGATION)!=(set(wb)&NEGATION)}

def image_fingerprint(raw):
 from PIL import Image,ImageOps,ImageStat
 if len(raw)>5_000_000:raise ValueError('image byte limit')
 with warnings.catch_warnings():
  warnings.simplefilter('error',Image.DecompressionBombWarning)
  with Image.open(io.BytesIO(raw)) as image:
   if image.width*image.height>20_000_000:raise ValueError('image pixel limit')
   if image.format not in ['JPEG','PNG','WEBP']:raise ValueError('unsupported still image')
   image=ImageOps.exif_transpose(image).convert('L');width,height=image.size
   low_information=ImageStat.Stat(image).stddev[0]<8
   pixels=list(image.resize((9,8),Image.Resampling.LANCZOS).tobytes());value=0
   for y in range(8):
    for x in range(8):value=(value<<1)|int(pixels[y*9+x]>pixels[y*9+x+1])
 return {'sha256':hashlib.sha256(raw).hexdigest(),'dhash':f'{value:016x}','width':width,'height':height,'low_information':low_information}

def fetch_image(url):
 if not safe_url(url,media=True):return None,'invalid_media_url'
 try:
  request=urllib.request.Request(url,headers={'User-Agent':'KashidaResearch/0.1'})
  with urllib.request.build_opener(NoRedirect).open(request,timeout=12) as response:
   raw=response.read(5_000_001)
  return image_fingerprint(raw),None
 except urllib.error.HTTPError as exc:return None,'HTTP '+str(exc.code)
 except (OSError,ValueError,Warning):return None,'image_download_or_decode_failed'

def collect_image_hashes(posts,limit):
 buckets=collections.defaultdict(list);by_url=collections.defaultdict(list)
 for p in posts:
  if p.get('media_type')=='video':continue  # A thumbnail does not establish video identity.
  photo=next((m for m in p.get('media',[]) if m.get('type')=='photo' and safe_url(m.get('url'),media=True)),None)
  if photo:buckets[source_key(p)].append((p,photo['url']));by_url[photo['url']].append(p)
 tasks=[];seen=set()
 for layer in itertools.zip_longest(*buckets.values()):
  for item in layer:
   if item and item[1] not in seen:tasks.append(item);seen.add(item[1])
 tasks=tasks[:max(0,min(limit,10))];hashes={};errors=[];decoded=0
 with ThreadPoolExecutor(max_workers=2) as pool:
  futures=[(p,url,pool.submit(fetch_image,url)) for p,url in tasks]
  for p,url,future in futures:
   fingerprint,error=future.result()
   if fingerprint:
    decoded+=1
    for matched in by_url[url]:hashes[identity(matched)]=fingerprint
   else:errors.append({'post_key':identity(p),'error':error})
 return hashes,{'requested':len(tasks),'decoded':decoded,'posts_with_hash':len(hashes),'errors':errors,'algorithm':'SHA-256 + 64-bit dHash'}

def image_evidence(a,b):
 if not a or not b:return None
 if a['sha256']==b['sha256']:return {'kind':'exact_image_bytes','low_information':a['low_information'] or b['low_information']}
 distance=(int(a['dhash'],16)^int(b['dhash'],16)).bit_count()
 aspect_a=a['width']/a['height'];aspect_b=b['width']/b['height']
 if not a['low_information'] and not b['low_information'] and distance<=6 and abs(aspect_a/aspect_b-1)<=0.15:return {'kind':'similar_image','dhash_distance':distance,'requires_visual_review':True}
 return None

def public_evidence(p):
 return {'platform':p.get('platform','Facebook'),'source_id':p['source_id'],'source_name':p['source_name'],'post_id':p['id'],'url':p['url'],'published_at':p.get('published_at'),'excerpt':' '.join((p.get('text') or '').split()[:25])}

def analyze(posts,images=None,window=WINDOW_SECONDS):
 rows=list({identity(p):p for p in posts}.values())
 if len(rows)>500:raise ProbeError('Bounded experiment supports at most500 posts; candidate indexing required beyond this')
 images=images or {};pairs=[];parents=list(range(len(rows)))
 def find(i):
  while parents[i]!=i:parents[i]=parents[parents[i]];i=parents[i]
  return i
 def union(a,b):parents[find(b)]=find(a)
 for a,b in itertools.combinations(range(len(rows)),2):
  first,second=rows[a],rows[b];text=text_evidence(first.get('text'),second.get('text'));image=image_evidence(images.get(identity(first)),images.get(identity(second)))
  if not text and not image:continue
  ta,tb=parse_time(first.get('published_at')),parse_time(second.get('published_at'));gap=abs((ta-tb).total_seconds()) if ta and tb else None
  context=[]
  if source_key(first)==source_key(second):context.append('same_source')
  if first.get('platform','Facebook')==second.get('platform','Facebook') and first['id']==second['id']:context.append('same_original_post_id')
  if first.get('shared_post') or second.get('shared_post'):context.append('shared_post_possible_common_origin')
  verified=bool(first.get('time_semantics_verified') and second.get('time_semantics_verified'))
  if not verified:context.append('publication_time_semantics_unverified')
  if text and text['generic_phrase_present']:context.append('generic_phrase_present')
  if text and (text['numbers_changed'] or text['negation_changed']):context.append('meaning_may_have_changed')
  if text or (image and image['kind']=='exact_image_bytes' and not image.get('low_information')):union(a,b)
  pairs.append({'_indices':(a,b),'first':public_evidence(first),'second':public_evidence(second),'text':text,'image':image,'gap_seconds':gap,'within_window':gap is not None and gap<=window,'time_verified':verified,'context':context})
 edges={}
 for pair_index,pair in enumerate(pairs):
  if not pair['within_window'] or any(x in pair['context'] for x in ['same_source','same_original_post_id','shared_post_possible_common_origin','generic_phrase_present','meaning_may_have_changed']):continue
  if not pair['text'] and not (pair['image'] and pair['image']['kind']=='exact_image_bytes' and not pair['image'].get('low_information')):continue
  a,b=pair['_indices'];keys=tuple(sorted([source_key(rows[a]),source_key(rows[b])]))
  edge=edges.setdefault(keys,{'sources':keys,'families':set(),'time_blocks':set(),'verified_families':set(),'evidence_pair_indices':[]})
  family=find(a);edge['families'].add(family)
  edge['time_blocks'].add(int(parse_time(rows[a]['published_at']).timestamp())//1800)
  if pair['time_verified']:edge['verified_families'].add(family)
  edge['evidence_pair_indices'].append(pair_index)
 patterns=[]
 for edge in edges.values():
  if len(edge['families'])>=3 and len(edge['time_blocks'])>=3:
   patterns.append({'sources':edge['sources'],'different_content_families':len(edge['families']),'time_blocks':len(edge['time_blocks']),'verified_content_families':len(edge['verified_families']),'status':'recurring_pattern_for_human_review','intent_determined':False,'evidence_pair_indices':edge['evidence_pair_indices']})
 for pair in pairs:pair.pop('_indices')
 return {'created_at':stamp(),'scope':'source_containers_not_individual_authors','posts_analyzed':len(rows),'sources_analyzed':len({source_key(p) for p in rows}),'posts_with_verified_publication_time':sum(bool(p.get('time_semantics_verified')) for p in rows),'parameters':{'window_seconds':window,'near_text_minimum_tokens':12,'shingle_jaccard':0.72,'character_similarity':0.88,'dhash_max_distance':6,'thresholds_calibrated':False},'counts':{'exact_text_pairs':sum(bool(p['text'] and p['text']['kind']=='exact_text') for p in pairs),'near_text_pairs':sum(bool(p['text'] and p['text']['kind']=='near_text') for p in pairs),'exact_image_pairs':sum(bool(p['image'] and p['image']['kind']=='exact_image_bytes') for p in pairs),'similar_image_pairs':sum(bool(p['image'] and p['image']['kind']=='similar_image') for p in pairs),'matching_pairs_in_window':sum(p['within_window'] for p in pairs),'recurring_patterns_for_review':len(patterns)},'pairs':pairs,'patterns':patterns,'coordination_or_bot_identity_proven':False,'socialapis_requests':0,'baseline_comparison_performed':False}

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--cache',default=str(ROOT/'data/demo_media_samples.json'));parser.add_argument('--images',type=int,default=0);args=parser.parse_args()
 posts=read_json(args.cache);images,downloads=collect_image_hashes(posts,args.images) if args.images else ({},{'requested':0,'decoded':0})
 report=analyze(posts,images);report['image_downloads']=downloads;write_json(ROOT/'data/coordination_report.json',report)
 summary={key:report[key] for key in ['created_at','scope','posts_analyzed','sources_analyzed','posts_with_verified_publication_time','counts','coordination_or_bot_identity_proven','socialapis_requests']};summary['image_downloads']=downloads
 write_json(ROOT/'data/coordination_status.json',summary);print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':
 try:main()
 except (ProbeError,OSError) as exc:print('Stopped: '+(str(exc) if isinstance(exc,ProbeError) else 'Local input file unavailable'));raise SystemExit(1)

"""Small Egyptian trends experiment. No SocialAPIs calls, no protected-page bypass."""
import argparse,collections,datetime as dt,email.utils,hashlib,html,json,os,pathlib,re,sqlite3,time
import urllib.error,urllib.parse,urllib.request,urllib.robotparser,xml.etree.ElementTree as ET
from html.parser import HTMLParser
from monitor import ROOT,ProbeError,Telegram,now,stamp,parse_time,format_timestamp,read_json,write_json,utf16_units

USER_AGENT='KashidaResearch/0.1'
GOOGLE_RSS='https://trends.google.com/trending/rss?geo=EG'
GETDAY='https://getdaytrends.com/egypt/'
X_URL='https://api.x.com/2/trends/by/woeid/23424802?max_trends=20&trend.fields=trend_name,tweet_count'
STOP=set('في من علي على عن الي الى ان أن وان وأن هذا هذه الذي التي مع بعد قبل خلال بين عند منذ كل اي أو او هو هي هم لا لم لن ما كما قال وقال اليوم السابع رصد شبكة مزيد تابع التفاصيل المزيد عاجل بالصور بالفيديو'.split())

def norm(text):
 text=re.sub(r'[\u064b-\u065f\u0670\u0640]','',text).replace('أ','ا').replace('إ','ا').replace('آ','ا').replace('ى','ي')
 return re.sub(r'\s+',' ',text.replace('_',' ')).strip().lower()

def fetch(url,headers=None):
 request=urllib.request.Request(url,headers={'User-Agent':USER_AGENT,'Accept-Encoding':'identity',**(headers or {})})
 try:
  with urllib.request.urlopen(request,timeout=25) as response:
   body=response.read(2_000_001)
   if len(body)>2_000_000:raise ProbeError('Response size limit exceeded')
   return body,response.status,response.headers.get('Content-Type','')
 except urllib.error.HTTPError as exc:raise ProbeError('HTTP '+str(exc.code)) from None
 except (urllib.error.URLError,TimeoutError):raise ProbeError('Network error') from None
 except ValueError:raise ProbeError('Invalid request configuration') from None

class PublicTrendTable(HTMLParser):
 def __init__(self):super().__init__();self.h1=False;self.country_title='';self.row=False;self.anchor=None;self.entries=[];self.tables=0
 def handle_starttag(self,tag,attrs):
  values=dict(attrs)
  if tag=='h1':self.h1=True
  if tag=='table':self.tables+=1
  if tag=='tr' and self.tables==1:self.row=True
  if tag=='a' and self.row and '/trend/' in values.get('href',''):self.anchor={'name':'','url':urllib.parse.urljoin(GETDAY,values['href'])}
 def handle_data(self,text):
  if self.h1:self.country_title+=text
  if self.anchor is not None:self.anchor['name']+=text
 def handle_endtag(self,tag):
  if tag=='h1':self.h1=False
  if tag=='a' and self.anchor is not None:
   item=self.anchor;self.anchor=None;item['name']=item['name'].strip()
   if item['name'] and item['name'] not in {x['name'] for x in self.entries}:self.entries.append(item)
  if tag=='tr':self.row=False

def parse_public_x(raw):
 parser=PublicTrendTable();parser.feed(raw.decode('utf-8','replace'))
 if 'egypt' not in parser.country_title.lower():raise ProbeError('Egypt country heading was not verified')
 if not parser.entries:raise ProbeError('Public page structure changed or no trends returned')
 return [{'rank':i+1,'name':x['name'],'kind':'hashtag' if x['name'].startswith('#') else 'topic','url':x['url']} for i,x in enumerate(parser.entries[:50])]

def read_public_x():
 robots,_,_=fetch('https://getdaytrends.com/robots.txt')
 rules=urllib.robotparser.RobotFileParser();rules.parse(robots.decode('utf-8','replace').splitlines())
 if not rules.can_fetch(USER_AGENT,GETDAY):raise ProbeError('Public source robots rules disallow automated access')
 raw,status,_=fetch(GETDAY)
 return {'platform':'X','provider':'GetDayTrends','coverage':'third_party_country_list','country':'EG','url':GETDAY,'http_status':status,'collected_at':stamp(),'source_updated_at':None,'items':parse_public_x(raw)}

def parse_google(raw):
 root=ET.fromstring(raw);rows=[]
 for node in root.findall('./channel/item')[:20]:
  title=node.findtext('title')
  if not title:continue
  published=node.findtext('pubDate');traffic=next((n.text for n in node if n.tag.endswith('approx_traffic')),None)
  when=email.utils.parsedate_to_datetime(published).isoformat() if published else None
  rows.append({'name':title,'kind':'search_topic','published_at':when,'traffic_label':traffic,'url':'https://trends.google.com/trends/explore?geo=EG&q='+urllib.parse.quote(title)})
 if not rows:raise ProbeError('Google RSS contains no items')
 return rows

def facebook_sample(posts,signals=()):
 unique={}
 for p in posts:unique[(p['source_id'],p['id'])]=p
 rows=list(unique.values());since=now()-dt.timedelta(hours=24)
 recent=[p for p in rows if (parse_time(p.get('published_at')) or dt.datetime.min.replace(tzinfo=dt.timezone.utc))>=since]
 tags={};phrases={}
 for p in recent:
  text=p.get('text') or '';evidence={'source_id':p['source_id'],'source_name':p['source_name'],'url':p['url']}
  for tag in set(re.findall(r'(?<!\w)#[\w\u064b-\u065f]+',text)):
   item=tags.setdefault(norm(tag),{'name':tag,'evidence':[]});item['evidence'].append(evidence)
  per_post=set()
  for clause in re.split(r'[.!؟،\n]',norm(text)):
   words=re.findall(r'[a-z\u0621-\u064a]{2,}',clause)
   for size in [2,3]:
    for i in range(len(words)-size+1):
     phrase=words[i:i+size]
     if any(w in STOP for w in phrase):continue
     per_post.add(' '.join(phrase))
  for phrase in per_post:phrases.setdefault(phrase,[]).append(evidence)
 repeated=[]
 for phrase,evidence in phrases.items():
  sources={p['source_id'] for p in evidence}
  if len(sources)>=2:repeated.append({'name':phrase,'post_count':len(evidence),'source_count':len(sources),'evidence':evidence[:4]})
 repeated.sort(key=lambda x:(-x['source_count'],-x['post_count'],-len(x['name'].split()),x['name']))
 selected=[]
 for item in repeated:
  if not any(item['name'] in other['name'] or other['name'] in item['name'] for other in selected):selected.append(item)
  if len(selected)==8:break
 hashtags=[{'name':x['name'],'post_count':len(x['evidence']),'source_count':len({e['source_id'] for e in x['evidence']}),'evidence':x['evidence'][:4]} for x in tags.values()]
 publisher_tags={norm(p['source_name']).replace(' ','').lstrip('#') for p in rows}
 hashtags=[h for h in hashtags if norm(h['name']).replace(' ','').lstrip('#') not in publisher_tags]
 hashtags.sort(key=lambda x:(-x['source_count'],-x['post_count'],x['name']))
 from topic_links import link_topics,all_topics
 related=link_topics(recent,signals)
 return {'platform':'Facebook','coverage':'selected_sources_sample','country_inference':'source_selection_only','cached_posts':len(rows),'posts_last_24h':len(recent),'sources':len({p['source_id'] for p in recent}),'last_collected_at':max((p.get('collected_at') or '' for p in rows),default=None),'hashtags':hashtags[:10],'repeated_phrases':selected,'related_topics':related,'topics':all_topics(recent,related,signals),'growth_measured':False}

def enrich_report(report,posts):
 signals=[]
 for key in ['x','google']:
  source=report.get('sources',{}).get(key,{})
  signals.extend({**item,'platform':'X' if key=='x' else 'Google'} for item in source.get('items',[]))
 report['sources']['facebook']=facebook_sample(posts,signals)
 return report

def collect_once(cache_path=None,probe_access=False):
 result={'created_at':stamp(),'country':'EG','socialapis_requests':0,'paid_api_requests':0,'sources':{},'probes':{}}
 token=(os.environ.get('X_BEARER_TOKEN') or '').strip()
 if token and any(c.isspace() or not 33<=ord(c)<127 for c in token):raise ProbeError('Invalid X_BEARER_TOKEN format')
 if token:
  result['paid_api_requests']=1
  try:
   raw,status,_=fetch(X_URL,{'Authorization':'Bearer '+token});data=json.loads(raw);items=data.get('data')
   if not isinstance(items,list):raise ProbeError('Unexpected official X trends schema')
   result['sources']['x']={'platform':'X','provider':'X official API','coverage':'official_country_trends','country':'EG','http_status':status,'collected_at':stamp(),'items':[{'name':x['trend_name'],'kind':'hashtag' if x['trend_name'].startswith('#') else 'topic','tweet_count':x.get('tweet_count'),'url':'https://x.com/search?q='+urllib.parse.quote(x['trend_name'])} for x in items]};result['paid_api_requests']=1
  except (ProbeError,ValueError,KeyError) as exc:result['sources']['x']={'error':str(exc),'provider':'X official API'}
 else:
  try:result['sources']['x']=read_public_x()
  except ProbeError as exc:result['sources']['x']={'error':str(exc),'provider':'GetDayTrends','official_api':'X_BEARER_TOKEN not configured'}
 try:
  raw,status,_=fetch(GOOGLE_RSS);result['sources']['google']={'platform':'Google Search','provider':'Google Trends RSS','coverage':'country_search_interest','country':'EG','http_status':status,'url':GOOGLE_RSS,'items':parse_google(raw)}
 except (ProbeError,ET.ParseError,ValueError) as exc:result['sources']['google']={'error':str(exc)}
 if cache_path and pathlib.Path(cache_path).exists():enrich_report(result,read_json(cache_path))
 else:result['sources']['facebook']={'error':'No Facebook cache available; no new data requested'}
 # A token-less probe checks the access requirement; it cannot incur authenticated charges.
 if probe_access and not token:
  try:_,status,_=fetch(X_URL);result['probes']['official_x_unauthenticated']=status
  except ProbeError as exc:result['probes']['official_x_unauthenticated']=str(exc)
 return result

def render_messages(data):
 header='🇪🇬 <b>ترندات مصر</b>\n'+format_timestamp(data['created_at'])
 x=data['sources'].get('x',{});lines=[header,'','<b>هاشتاجات وموضوعات شائعة في مصر · X</b>']
 for number,item in enumerate(x.get('items',[])[:10],1):lines.append(str(number)+'. '+html.escape(item['name']))
 if not x.get('items'):lines.append('القائمة غير متاحة حاليًا.')
 source_url=x.get('url') or ('https://docs.x.com/x-api/trends/get-trends-by-woeid' if x.get('coverage')=='official_country_trends' else GETDAY)
 lines.append('<a href="'+html.escape(source_url,quote=True)+'">المصدر</a>');messages=['\n'.join(lines)]
 g=data['sources'].get('google',{});lines=['<b>عمليات البحث الرائجة في مصر · Google</b>']
 for number,item in enumerate(g.get('items',[]),1):lines.append(str(number)+'. '+html.escape(item['name']))
 if not g.get('items'):lines.append('القائمة غير متاحة حاليًا.')
 lines.append('<a href="https://trends.google.com/trending?geo=EG">المصدر</a>');messages.append('\n'.join(lines))
 fb=data['sources'].get('facebook',{});lines=[]
 if fb.get('hashtags'):
  lines.append('<b>هاشتاجات المنشورات</b>')
  for item in fb['hashtags']:lines.append('• '+html.escape(item['name'])+' — '+str(item['post_count'])+' منشورات')
  lines.append('')
 lines.append('<b>موضوعات المنشورات والروابط بينها</b>')
 topics=fb.get('topics',fb.get('related_topics',[]))
 for number,item in enumerate(topics,1):
  platforms=sorted({m['platform'] for m in item.get('matched_trends',[]) if m.get('platform')})
  lines.append(str(number)+'. <b>'+html.escape(item['title'])+'</b>'+(' — '+str(item['post_count'])+' منشورات مرتبطة' if item['post_count']>1 else '')+(' · '+html.escape(' / '.join(platforms)) if platforms else ''))
  evidence=[];seen_sources=set()
  for post in item['evidence']:
   if post['source_id'] in seen_sources:continue
   seen_sources.add(post['source_id']);label=post['source_name']+(': '+' '.join(post['headline'].split()[:7]) if item['post_count']>1 else '')
   evidence.append('<a href="'+html.escape(post['url'],quote=True)+'">'+html.escape(label)+'</a>')
   if len(evidence)==2:break
  if len(evidence)==1 and len(item['evidence'])>1:
   post=item['evidence'][1];evidence.append('<a href="'+html.escape(post['url'],quote=True)+'">منشور آخر</a>')
  lines.append('\n'.join(evidence))
 if not topics:lines.append('لا توجد منشورات متاحة للتحليل.')
 messages.append('\n'.join(lines));return messages

def digest_messages(data):
 parts=render_messages(data);combined='\n\n'.join(parts)
 if utf16_units(combined)<=3900:return [combined]
 result=[]
 for part in parts:
  chunk=[]
  for line in part.splitlines():
   if utf16_units(line)>3900:raise ProbeError('A trend item exceeds Telegram message limits')
   if chunk and utf16_units('\n'.join(chunk+[line]))>3900:result.append('\n'.join(chunk));chunk=[]
   chunk.append(line)
  if chunk:result.append('\n'.join(chunk))
 return result

def trial_enabled(value=None):
 # The product trial is bounded to seven future daily deliveries, not an indefinite job.
 from zoneinfo import ZoneInfo
 local=(value or now()).astimezone(ZoneInfo('Europe/Istanbul'))
 return dt.date(2026,11,7)<=local.date()<=dt.date(2026,11,13)

def main():
 p=argparse.ArgumentParser();p.add_argument('--cache',default=str(ROOT/'data/demo_media_samples.json'));p.add_argument('--send',action='store_true');p.add_argument('--probe-access',action='store_true');args=p.parse_args()
 report=collect_once(args.cache,args.probe_access);write_json(ROOT/'data/egypt_trends.json',report)
 brief=digest_messages(report);write_json(ROOT/'data/trend_messages.json',brief)
 status={'created_at':report['created_at'],'socialapis_requests':0,'paid_api_requests':report['paid_api_requests'],'sources':{key:({'items':len(value.get('items',[])),'provider':value.get('provider'),'error':value.get('error')} if key!='facebook' else {**{k:value.get(k) for k in ['cached_posts','posts_last_24h','sources','error']},'hashtag_count':len(value.get('hashtags',[])),'repeated_phrase_count':len(value.get('repeated_phrases',[]))}) for key,value in report['sources'].items()},'probes':report['probes'],'telegram_messages_sent':0}
 if args.send:
  client=Telegram(os.environ.get('TELEGRAM_BOT_TOKEN'),os.environ.get('TELEGRAM_CHAT_ID'))
  if client.verify().get('bot_username')!='test_kashida_bot':raise ProbeError('Unexpected bot')
  for text in brief:
   if utf16_units(text)>3900:raise ProbeError('Trend summary exceeds message limit')
   response=client.call('sendMessage',{'chat_id':client.chat,'text':text,'parse_mode':'HTML','link_preview_options':{'is_disabled':True}})
   if not response.get('message_id'):raise ProbeError('Telegram acknowledgement missing')
   status['telegram_messages_sent']+=1;time.sleep(1.3)
 write_json(ROOT/'data/trends_status.json',status);print(json.dumps(status,ensure_ascii=False,indent=2),flush=True)
 if not any(value.get('items') for value in report['sources'].values()) and not report['sources'].get('facebook',{}).get('posts_last_24h'):raise SystemExit(1)
if __name__=='__main__':
 try:main()
 except ProbeError as exc:print('Stopped: '+str(exc));raise SystemExit(1)

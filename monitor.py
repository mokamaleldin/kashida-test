"""Bounded Facebook monitoring experiment. Python 3.11+, standard library only."""
from __future__ import annotations
import argparse, datetime as dt, getpass, hashlib, json, os, pathlib, re, sqlite3, sys, time
import urllib.error, urllib.parse, urllib.request
ROOT=pathlib.Path(__file__).resolve().parent
UTC=dt.timezone.utc

class ProbeError(Exception):pass
class TransportError(ProbeError):
    def __init__(self,status=None):self.status=status;super().__init__('HTTP '+str(status) if status else 'Network error; delivery/billing outcome may be unknown')
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def now():return dt.datetime.now(UTC)
def stamp(value=None):return (value or now()).isoformat()
def read_json(path):return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))
def write_json(path,data):
    path=pathlib.Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

def request_json(url,headers=None,payload=None,timeout=40):
    body=None if payload is None else json.dumps(payload).encode()
    req=urllib.request.Request(url,data=body,headers={'User-Agent':'Kashida-Test/0.2',**({'Content-Type':'application/json'} if body else {}),**(headers or {})})
    try:
        with urllib.request.build_opener(NoRedirect).open(req,timeout=timeout) as response:
            raw=response.read(5_000_001)
            if len(raw)>5_000_000:raise ProbeError('Response exceeds 5 MB limit')
            data=json.loads(raw)
            if not isinstance(data,dict):raise ProbeError('Expected a JSON object')
            return data,dict(response.headers)
    except urllib.error.HTTPError as exc:raise TransportError(exc.code) from None
    except (urllib.error.URLError,TimeoutError):raise TransportError() from None

def safe_url(value,media=False):
    if not isinstance(value,str):return None
    try:
        u=urllib.parse.urlsplit(value);host=(u.hostname or '').lower()
        if u.scheme!='https' or u.username or u.password:return None
        roots=('fbcdn.net','fbsbx.com') if media else ('facebook.com','fb.watch')
        if any(host==r or host.endswith('.'+r) for r in roots):return value
    except ValueError:pass
    return None

def parse_time(value):
    if not isinstance(value,str):return None
    try:
        x=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
        return x.astimezone(UTC) if x.tzinfo else None
    except ValueError:return None

def number(value):
    if value is None or isinstance(value,bool):return None
    try:return int(str(value).replace(',',''))
    except (ValueError,TypeError):return None

def extract_media(post):
    found=[];seen=set()
    def walk(node,key='',depth=0):
        if depth>12:return
        if isinstance(node,dict):
            for k,v in node.items():walk(v,k,depth+1)
        elif isinstance(node,list):
            for v in node[:50]:walk(v,key,depth+1)
        elif isinstance(node,str):
            if node.startswith('{'):
                try:walk(json.loads(node),key,depth+1)
                except ValueError:pass
            url=safe_url(node,media=True)
            if url and url not in seen:
                seen.add(url)
                kind='video' if any(s in key.lower() for s in ['video','playable','browser_native','hd_src','sd_src']) or '.mp4' in urllib.parse.urlsplit(url).path.lower() else 'photo'
                found.append({'type':kind,'url':url})
    walk(post.get('attachments'))
    values=post.get('values') or {};walk(values.get('photo_image'),'photo_image')
    for key in ['video_url','playable_url','video_hd_url','video_sd_url']:walk(values.get(key),key)
    return found[:20]

def normalize(post,source,collected_at):
    details=post.get('details') or {};values=post.get('values') or {}
    ident=details.get('post_id') or values.get('post_id')
    url=safe_url(details.get('post_link'))
    if ident is None or not url:raise ProbeError('Post missing stable id or valid Facebook permalink')
    text=values.get('text');text=text if isinstance(text,str) else None
    media=extract_media(post);declared=str(values.get('is_media') or '').lower()
    if any(x['type']=='video' for x in media) or 'video' in declared or 'reel' in declared:kind='video'
    elif media or 'photo' in declared or 'image' in declared:kind='photo'
    elif 'link' in declared:kind='link'
    elif text:kind='text'
    else:kind='unknown'
    published=parse_time(values.get('publish_time'))
    reactions=post.get('reactions') or {}
    return {'source_id':source['id'],'source_name':source['name'],'id':str(ident),'url':url,'text':text,'published_at':stamp(published) if published else None,'time_origin':'provider.values.publish_time','time_semantics_verified':False,'collected_at':collected_at,'media_type':kind,'media':media,'media_url_available':any(m['type']==kind for m in media),'shared_post':bool(values.get('shared_post')),'reactions':number(reactions.get('total_reaction_count')),'comments':number(details.get('comments_count')),'shares':number(details.get('share_count')),'views':number(details.get('play_count'))}

def arabic(text):return re.sub(r'[\u064b-\u065f\u0670\u0640]','',text).replace('أ','ا').replace('إ','ا').replace('آ','ا').lower()
def filter_post(post,filters,since=None):
    reasons=[];t=arabic(post.get('text') or '')
    if post['media_type'] not in filters.get('media_types',['text','photo','video','link','unknown']):reasons.append('نوع محتوى مستبعد')
    include=filters.get('include_any',[]);exclude=filters.get('exclude_any',[])
    if include and not any(arabic(w) in t for w in include):reasons.append('لا توجد كلمة مطلوبة')
    if any(arabic(w) in t for w in exclude):reasons.append('كلمة مستبعدة')
    if filters.get('require_text') and not post.get('text'):reasons.append('بلا نص')
    minimum=filters.get('minimum_reactions',0)
    if minimum and (post.get('reactions') is None or post['reactions']<minimum):reasons.append('تفاعل أقل أوغير متاح')
    if since:
        published=parse_time(post.get('published_at'))
        if not published:reasons.append('تاريخ غير متاح')
        elif published<since:reasons.append('خارج الفترة المطلوبة')
    return reasons

def connect(path):
    path=pathlib.Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path);db.row_factory=sqlite3.Row
    db.executescript('''PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS posts(source_id TEXT,post_id TEXT,payload TEXT,first_seen TEXT,last_seen TEXT,PRIMARY KEY(source_id,post_id));
    CREATE TABLE IF NOT EXISTS calls(id INTEGER PRIMARY KEY,period TEXT,source_id TEXT,started_at TEXT,status TEXT,credits INTEGER DEFAULT 1,details TEXT);
    CREATE TABLE IF NOT EXISTS deliveries(source_id TEXT,post_id TEXT,chat_hash TEXT,status TEXT,message_id TEXT,updated_at TEXT,PRIMARY KEY(source_id,post_id,chat_hash));''')
    return db

def upsert(db,post):
    key=(post['source_id'],post['id']);existing=db.execute('SELECT 1 FROM posts WHERE source_id=? AND post_id=?',key).fetchone()
    db.execute('INSERT INTO posts VALUES(?,?,?,?,?) ON CONFLICT(source_id,post_id) DO UPDATE SET payload=excluded.payload,last_seen=excluded.last_seen',(*key,json.dumps(post,ensure_ascii=False),post['collected_at'],post['collected_at']));db.commit()
    return not bool(existing)

def load_sources(path):
    rows=read_json(path)
    if not isinstance(rows,list):raise ProbeError('Sources must be a list')
    enabled=[s for s in rows if s.get('enabled',True)];ids=set()
    for s in enabled:
        if not s.get('id') or s['id'] in ids or not safe_url(s.get('url')) or s.get('kind') not in ['page','group']:raise ProbeError('Invalid orduplicate source')
        ids.add(s['id'])
    return enabled

def get_usage(token):
    data,_=request_json('https://api.socialapis.io/usage',{'x-api-token':token})
    block=data.get('data') if isinstance(data.get('data'),dict) else data
    return {k:block.get(k) for k in ['creditsUsed','creditsRemaining','creditsLimit']}

def collect(db,sources,settings,token,request_cap=None):
    limit=int(settings.get('limit',3))
    if limit!=3:raise ProbeError('This bounded experiment fixes limit=3 to keep basic calls at one expected credit')
    cap=min(int(request_cap or settings.get('max_calls_per_run',5)),len(sources))
    if not 1<=cap<=10:raise ProbeError('Per-run request cap must be 1..10')
    since=now()-dt.timedelta(minutes=int(settings.get('lookback_minutes',60)));period=now().strftime('%Y-%m')
    usage_before=get_usage(token)
    summary={'started_at':stamp(),'requests':0,'credits_charged':0,'credits_uncertain':False,'remaining':None,'inserted':0,'updated':0,'sources':[],'since_requested':stamp(since),'limit':3,'bounded':True}
    for source in sources[:cap]:
        used=db.execute('SELECT COALESCE(SUM(credits),0) FROM calls WHERE period=?',(period,)).fetchone()[0]
        if used+1>settings.get('monthly_credit_cap',100):summary['stop_reason']='Local monthly experiment cap reached';break
        cursor=db.execute('INSERT INTO calls(period,source_id,started_at,status) VALUES(?,?,?,?)',(period,source['id'],stamp(),'attempted'));db.commit();call_id=cursor.lastrowid
        endpoint='/facebook/pages/posts' if source['kind']=='page' else '/facebook/groups/posts'
        query=urllib.parse.urlencode({'link':source['url'],'limit':3,'after_time':since.date().isoformat(),'timezone':'UTC'})
        item={'id':source['id'],'name':source['name'],'requested_kind':source['kind']};summary['requests']+=1;started=time.monotonic()
        try:
            data,headers=request_json('https://api.socialapis.io'+endpoint+'?'+query,{'x-api-token':token})
            meta=data.get('meta') or {};lower={k.lower():v for k,v in headers.items()}
            # Credits-Used can be cumulative. Prefer the explicit deduction.
            credits=number(meta.get('creditsCharged'))
            if credits is None:credits=number(lower.get('x-socialapis-credits-deducted'))
            if credits is None:credits=1;summary['credits_uncertain']=True
            summary['credits_charged']+=credits;summary['remaining']=meta.get('creditsRemaining',lower.get('x-socialapis-credits-remaining'))
            item['credits']=credits;item['remaining']=summary['remaining']
            block=data.get('data')
            if not isinstance(block,dict) or not isinstance(block.get('posts'),list):raise ProbeError('Provider response schema does not contain data.posts list')
            posts=block['posts'];item.update({'returned':len(posts),'has_next':bool((block.get('page_info') or {}).get('has_next')),'outside_window':0,'missing_text':0,'invalid':0,'media_types':{}})
            times=[]
            for raw in posts:
                try:post=normalize(raw,source,stamp())
                except (ProbeError,AttributeError,TypeError):item['invalid']+=1;continue
                reasons=filter_post(post,settings.get('filters',{}),since);post['filter_reasons']=reasons;post['eligible']=not reasons
                if 'خارج الفترة المطلوبة' in reasons:item['outside_window']+=1
                item['missing_text']+=int(not post['text']);item['media_types'][post['media_type']]=item['media_types'].get(post['media_type'],0)+1
                if post['published_at']:times.append(post['published_at'])
                summary['inserted' if upsert(db,post) else 'updated']+=1
            item['returned_times_descending']=times==sorted(times,reverse=True)
            item['possible_window_overflow']=len(posts)>=3 and item['has_next']
            db.execute('UPDATE calls SET status=?,credits=?,details=? WHERE id=?',('ok',credits,json.dumps(item,ensure_ascii=False),call_id));db.commit()
        except (ProbeError,ValueError,TypeError) as exc:
            status=getattr(exc,'status',None);item['error']=str(exc);item['http_status']=status
            known_free=isinstance(exc,TransportError) and status is not None and status>=400
            db.execute('UPDATE calls SET status=?,credits=?,details=? WHERE id=?',('error',0 if known_free else 1,json.dumps(item,ensure_ascii=False),call_id));db.commit()
            if not known_free:summary['credits_uncertain']=True
            if status in [401,403,429]:summary['stop_reason']='Account/auth/rate limit; stopped without retries'
        item['elapsed_seconds']=round(time.monotonic()-started,2);summary['sources'].append(item)
        if summary.get('stop_reason'):break
    try:
        usage_after=get_usage(token);summary['usage_verified_after']=usage_after;summary['remaining']=usage_after.get('creditsRemaining',summary['remaining'])
        if isinstance(usage_after.get('creditsUsed'),int) and isinstance(usage_before.get('creditsUsed'),int):summary['account_usage_delta']=usage_after['creditsUsed']-usage_before['creditsUsed']
    except ProbeError:summary['usage_verification_failed']=True
    summary['finished_at']=stamp();return summary

def all_posts(db):
    rows=[json.loads(r['payload']) for r in db.execute('SELECT payload FROM posts ORDER BY last_seen DESC')]
    for row in rows:
        if 'media_url_available' not in row:row['media_url_available']=row.pop('media_download_available',False)
    return rows

def message(post):
    body=post.get('text') or 'منشور بدون نص'
    return f"{post['source_name']}\nنوع المحتوى: {post['media_type']}\nوقت المصدر: {post.get('published_at') or 'غير متاح'}\n\n{body[:2800]}\n\n{post['url']}"

class Telegram:
    def __init__(self,token,chat):
        self.token=str(token).strip();self.chat=str(chat).strip()
        if not re.fullmatch(r'\d{6,15}:[A-Za-z0-9_-]{20,}',self.token):raise ProbeError('Invalid Telegram token format; use only the BotFather token')
        if not re.fullmatch(r'-?\d{1,20}',self.chat):raise ProbeError('Invalid Telegram chat id format; use only the numeric chat id')
    def call(self,method,payload=None):
        try:data,_=request_json('https://api.telegram.org/bot'+self.token+'/'+method,payload=payload or {})
        except TransportError:raise
        if not data.get('ok'):raise ProbeError('Telegram rejected request')
        return data.get('result')
    def verify(self):
        me=self.call('getMe');chat=self.call('getChat',{'chat_id':self.chat})
        if not me.get('is_bot') or str(chat.get('id'))!=self.chat:raise ProbeError('Telegram destination verification failed')
        return {'bot_username':me.get('username'),'chat_type':chat.get('type'),'chat_verified':True}
    def send(self,post):
        selected=next((m for m in post['media'] if m['type']==post['media_type']),None)
        if selected and post['media_type'] in ['photo','video']:
            field=post['media_type'];method='sendPhoto' if field=='photo' else 'sendVideo'
            try:return self.call(method,{'chat_id':self.chat,field:selected['url'],'caption':message(post)[:1000]})
            except TransportError as exc:
                if exc.status not in [400,413]:raise
                # Definitive media rejection only. Network timeouts are not retried.
        return self.call('sendMessage',{'chat_id':self.chat,'text':message(post),'link_preview_options':{'is_disabled':False}})

def send_pending(db,client,settings,max_messages=1):
    verified=client.verify();sent=0;chat_hash=hashlib.sha256(client.chat.encode()).hexdigest()
    since=now()-dt.timedelta(minutes=settings.get('lookback_minutes',60))
    rows=sorted(all_posts(db),key=lambda x:x.get('published_at') or '',reverse=True)
    for post in rows:
        if filter_post(post,settings.get('filters',{}),since):continue
        exists=db.execute('SELECT status FROM deliveries WHERE source_id=? AND post_id=? AND chat_hash=?',(post['source_id'],post['id'],chat_hash)).fetchone()
        if exists:continue
        db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?,?)',(post['source_id'],post['id'],chat_hash,'sending',None,stamp()));db.commit()
        try:
            result=client.send(post);status='sent';message_id=str(result.get('message_id'));sent+=1
        except (ProbeError,TypeError,AttributeError):status='unknown';message_id=None
        db.execute('UPDATE deliveries SET status=?,message_id=?,updated_at=? WHERE source_id=? AND post_id=? AND chat_hash=?',(status,message_id,stamp(),post['source_id'],post['id'],chat_hash));db.commit()
        if status=='unknown':break
        if sent>=max_messages:break
    return {**verified,'sent':sent,'limit':max_messages}

def costs(sources,minutes,credits_per_check=1):
    checks=sources*30*24*60//minutes;credits=checks*credits_per_check
    plans=[('Free',200,0),('Pro',1500,4.99),('Ultra',30000,49),('Mega',120000,179)]
    plan=next(({'name':n,'credits':c,'monthly_usd':p} for n,c,p in plans if c>=credits),None)
    return {'sources':sources,'interval_minutes':minutes,'days':30,'checks':checks,'credits':credits,'plan':plan,'extra_price_known':bool(plan),'hosting_included':False}

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['collect','serve','cost','send'])
    p.add_argument('--db',default=str(ROOT/'data/state.sqlite'));p.add_argument('--sources',default=str(ROOT/'sources.json'));p.add_argument('--settings',default=str(ROOT/'settings.json'));p.add_argument('--max-calls',type=int,default=5);p.add_argument('--lookback',type=int);p.add_argument('--send',action='store_true');p.add_argument('--max-messages',type=int,default=1);p.add_argument('--port',type=int,default=8765)
    args=p.parse_args();settings=read_json(args.settings)
    if args.lookback is not None:
        if not 1<=args.lookback<=1440:raise ProbeError('Lookback must be 1..1440 minutes')
        settings['lookback_minutes']=args.lookback
    if args.command=='cost':print(json.dumps([costs(n,m) for n in [50,60] for m in [15,30]],ensure_ascii=False,indent=2));return
    db=connect(args.db)
    if args.command=='serve':
        from app import serve
        db.close();serve(args.db,args.port);return
    report={}
    if args.command=='collect':
        token=os.environ.get('SOCIALAPIS_API_KEY') or getpass.getpass('SocialAPIs key (hidden): ').strip()
        if not token:raise ProbeError('SOCIALAPIS_API_KEY required')
        report=collect(db,load_sources(args.sources),settings,token,args.max_calls)
        write_json(ROOT/'data/last_run.json',report)
    if args.command=='send' or args.send:
        token=os.environ.get('TELEGRAM_BOT_TOKEN') or os.environ.get('BOT_TOKEN');chat=os.environ.get('TELEGRAM_CHAT_ID') or os.environ.get('CHAT_ID')
        if not token or not chat:report['telegram']={'sent':0,'blocked':'TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID required'}
        else:report['telegram']=send_pending(db,Telegram(token,chat),settings,max(1,min(args.max_messages,3)))
    print(json.dumps(report,ensure_ascii=False,indent=2));db.close()
if __name__=='__main__':
    try:main()
    except (ProbeError,OSError,ValueError) as exc:
        print('Stopped: '+(str(exc) if not isinstance(exc,OSError) else 'Local file or network error'),file=sys.stderr);raise SystemExit(1)

"""Bounded, user-initiated Telegram demo. Never calls SocialAPIs."""
import argparse,html,json,os,pathlib,sqlite3,time
from monitor import ROOT,Telegram,ProbeError,TransportError,now,stamp,format_timestamp,message,read_json,write_json,utf16_units,safe_url
import datetime as dt

COMMANDS=[{'command':c,'description':d} for c,d in [
 ('sources','المصادر المتاحة'),('demo','عرض كل المنشورات المحفوظة من جميع المصادر'),('trends','نشرة موضوعات وهاشتاجات مصر')]]

def ordered_posts(posts,sources):
 unique={}
 for post in posts:
  key=(post['source_id'],post['id'])
  if key not in unique or (post.get('collected_at') or '')>(unique[key].get('collected_at') or ''):unique[key]=post
 order={s['id']:i for i,s in enumerate(sources)}
 rows=sorted(unique.values(),key=lambda p:p.get('published_at') or '',reverse=True)
 return sorted(rows,key=lambda p:order.get(p['source_id'],len(order)))

class Demo:
 def __init__(self,client,sources,samples,db,expires_at,trend_report=None):
  self.client=client;self.sources=sources;self.samples=ordered_posts(samples,sources);self.db=db;self.expires_at=expires_at;self.sent=0;self.last_send=0
  self.trend_report=trend_report
  self.cache_path=None;self.media_groups_sent=0;self.delivery_calls=0
  db.executescript('CREATE TABLE IF NOT EXISTS handled(update_id INTEGER PRIMARY KEY); CREATE TABLE IF NOT EXISTS demo_requests(chat_id TEXT PRIMARY KEY,at REAL);')
 def deliver(self,method,payload):
  expected=len(payload.get('media',[])) if method=='sendMediaGroup' else 1
  if self.sent+expected>100:raise ProbeError('Demo message budget exhausted')
  pause=1.3-(time.monotonic()-self.last_send)
  if pause>0:time.sleep(pause)
  self.last_send=time.monotonic()
  self.delivery_calls+=1;result=self.client.call(method,payload)
  self.last_send=time.monotonic()
  messages=result if isinstance(result,list) else [result]
  if len(messages)!=expected or not all(isinstance(m,dict) and m.get('message_id') for m in messages):raise ProbeError('Telegram acknowledgement missing')
  self.sent+=len(messages)
  return result
 def album_item(self,post):
  caption=message(post,max_units=100_000_000)
  if utf16_units(caption)>1000:return None
  cached=post.get('telegram_media') or {}
  if cached.get('type')=='photo' and cached.get('file_id'):media=cached['file_id']
  else:
   available=[m for m in post.get('media',[]) if safe_url(m.get('url'),media=True)]
   if any(m.get('type')=='video' for m in available):return None
   photo=next((m for m in available if m.get('type')=='photo'),None)
   if photo is None:return None
   media=photo['url']
  return {'type':'photo','media':media,'caption':caption,'parse_mode':'HTML'}
 def save_cache(self):
  if self.cache_path:write_json(self.cache_path,self.samples)
 def send_posts(self,chat,posts):
  results=[];batch=[]
  def flush():
   if not batch:return
   if len(batch)==1:replies=[self.client.send(batch[0][0],chat_id=chat,send_call=self.deliver)]
   else:
    try:
     replies=self.deliver('sendMediaGroup',{'chat_id':str(chat),'media':[item for _,item in batch]});self.media_groups_sent+=1
    except TransportError as exc:
     if exc.status not in [400,413]:raise
     replies=[self.client.send(post,chat_id=chat,send_call=self.deliver) for post,_ in batch]
   for (post,_),reply in zip(batch,replies):
    if reply.get('photo'):post['telegram_media']={'type':'photo','file_id':reply['photo'][-1]['file_id']}
   results.extend(replies);batch.clear();self.save_cache()
  for post in posts:
   item=self.album_item(post)
   if item is not None:
    batch.append((post,item))
    if len(batch)==10:flush()
   else:
    flush();results.append(self.client.send(post,chat_id=chat,send_call=self.deliver));self.save_cache()
  flush();return results
 def send(self,chat,text):
  return self.deliver('sendMessage',{'chat_id':str(chat),'text':text,'parse_mode':'HTML','link_preview_options':{'is_disabled':True}})
 def help(self):
  return ('<b>كشيدة</b>\n\n/sources — المصادر\n/demo — كل المنشورات بالصور\n/trends — ترندات مصر\n\nجلسة التجربة حتى '+html.escape(format_timestamp(self.expires_at)))
 def handle(self,update):
  mid=update.get('update_id');m=update.get('message') or {};chat=m.get('chat') or {};text=m.get('text') or ''
  if isinstance(text,str):
   text=text.strip()
   if text.lower()=='start':text='/start'
  if not isinstance(mid,int) or chat.get('type')!='private' or (m.get('from') or {}).get('is_bot') or not isinstance(text,str) or not text.startswith('/'):return
  if not isinstance(chat.get('id'),int):return
  if self.db.execute('SELECT 1 FROM handled WHERE update_id=?',(mid,)).fetchone():return
  # Mark before sending: an ambiguous network failure must not trigger duplicate sends.
  self.db.execute('INSERT INTO handled VALUES(?)',(mid,));self.db.commit()
  args=text.strip().split();cmd=args[0].lower().split('@')[0];cid=str(chat['id'])
  if cmd in ['/start','/help']:return [self.send(cid,self.help())]
  if cmd=='/trends':
   if not self.trend_report:return [self.send(cid,'نشرة الترندات غير متاحة في هذه الجلسة بعد.')]
   from trends_probe import digest_messages
   return [self.send(cid,text) for text in digest_messages(self.trend_report)]
  if cmd in ['/sources','/source']:
   lines=['<b>المصادر المتاحة</b>']
   for source in self.sources:
    count=sum(p['source_id']==source['id'] for p in self.samples)
    lines.append('<a href="'+html.escape(source['url'],quote=True)+'">'+html.escape(source['name'])+'</a> — '+str(count)+' منشورات محفوظة')
   lines.append('\n/demo لعرض جميع المنشورات.')
   return [self.send(cid,'\n'.join(lines))]
  if cmd!='/demo':return [self.send(cid,'الأوامر المتاحة: /sources للمصادر و/demo للمنشورات و/trends لنشرة الترندات.')]
  chosen=self.samples
  if not chosen:return [self.send(cid,'لا توجد منشورات محفوظة بعد.')]
  last=self.db.execute('SELECT at FROM demo_requests WHERE chat_id=?',(cid,)).fetchone()
  if last and time.time()-last[0]<30:return [self.send(cid,'انتظر30 ثانية بين طلبات العينات، ثم أعد نفس الأمر.')]
  self.db.execute('INSERT INTO demo_requests VALUES(?,?) ON CONFLICT(chat_id) DO UPDATE SET at=excluded.at',(cid,time.time()));self.db.commit()
  return self.send_posts(cid,chosen)

def main():
 p=argparse.ArgumentParser();p.add_argument('--minutes',type=int,choices=[15,30,60],default=60);p.add_argument('--smoke',action='store_true');p.add_argument('--samples',default=str(ROOT/'data/demo_media_samples.json'));args=p.parse_args()
 token=os.environ.get('TELEGRAM_BOT_TOKEN');chat=os.environ.get('TELEGRAM_CHAT_ID')
 if not token or not chat:raise ProbeError('Telegram secrets missing')
 client=Telegram(token,chat);verified=client.verify()
 if verified.get('bot_username')!='test_kashida_bot':raise ProbeError('Unexpected bot')
 webhook=client.call('getWebhookInfo')
 if webhook.get('url'):raise ProbeError('Existing webhook found; no changes made')
 source_cache=pathlib.Path(args.samples).with_name('demo_sources.json')
 sources=read_json(source_cache) if source_cache.exists() else read_json(ROOT/'sources.json')
 samples=read_json(args.samples) if pathlib.Path(args.samples).exists() else read_json(ROOT/'demo_samples.json')
 expires=stamp(now()+dt.timedelta(minutes=args.minutes));db=sqlite3.connect(ROOT/'data/demo.sqlite')
 trend_path=ROOT/'data/egypt_trends.json';trend_report=read_json(trend_path) if trend_path.exists() else None
 if trend_report:
  from trends_probe import enrich_report
  enrich_report(trend_report,samples);write_json(trend_path,trend_report)
 demo=Demo(client,sources,samples,db,expires,trend_report)
 demo.cache_path=pathlib.Path(args.samples)
 if args.smoke:
  if client.call('setMyCommands',{'commands':COMMANDS}) is not True:raise ProbeError('Command registration failed')
  configured=client.call('getMyCommands')
  response=demo.handle({'update_id':-1,'message':{'chat':{'id':int(client.chat),'type':'private'},'text':'/trends' if trend_report else '/start'}})
  result={'ready':True,'bot_username':verified['bot_username'],'facebook_data_requests':0,'owner_check_messages_sent':demo.sent,'cached_posts':len(demo.samples),'source_names':[s['name'] for s in sources],'trend_command_verified':bool(trend_report),'registered_commands':[x['command'] for x in configured]}
  if os.environ.get('CHECK_DEMO')=='true':
   before=demo.sent;started=time.monotonic();replies=demo.handle({'update_id':-2,'message':{'chat':{'id':int(client.chat),'type':'private'},'text':'/demo'}})
   result['demo_test']={'posts_delivered':len(replies or []),'messages_sent':demo.sent-before,'media_groups_sent':demo.media_groups_sent,'elapsed_seconds':round(time.monotonic()-started,2)}
  if trend_report:result['topic_groups']=[{k:t[k] for k in ['title','post_count','source_count']} for t in trend_report['sources']['facebook'].get('related_topics',[])]
  write_json(pathlib.Path(args.samples),samples)
  write_json(ROOT/'data/demo_smoke.json',result);print(json.dumps(result,ensure_ascii=False),flush=True);return
 started=now().timestamp();deadline=time.monotonic()+args.minutes*60;offset=0;processed=0
 print(json.dumps({'listening':True,'started_at':stamp(),'expires_at':expires,'facebook_data_requests':0,'public_private_chat_demo':True}),flush=True)
 while time.monotonic()<deadline and demo.sent<100:
  try:updates=client.call('getUpdates',{'offset':offset,'timeout':20,'limit':20,'allowed_updates':['message']})
  except TransportError as exc:
   if exc.status in [401,403,409,429]:raise
   time.sleep(3);continue
  for update in updates:
   uid=update.get('update_id')
   if not isinstance(uid,int):continue
   offset=max(offset,uid+1)
   # Ignore historical commands left in Telegram's queue before this session.
   if (update.get('message') or {}).get('date',0)<started-30:continue
   replies=demo.handle(update)
   if replies:processed+=1;print(json.dumps({'commands_responded':processed,'messages_sent':demo.sent,'facebook_data_requests':0}),flush=True)
 print(json.dumps({'listening':False,'messages_sent':demo.sent,'facebook_data_requests':0,'reason':'message_budget_finished' if demo.sent>=100 else 'session_expired'}),flush=True);db.close()

if __name__=='__main__':
 (ROOT/'data').mkdir(exist_ok=True)
 try:main()
 except ProbeError as exc:print('Stopped: '+str(exc),flush=True);raise SystemExit(1)

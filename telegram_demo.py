"""Bounded, user-initiated Telegram demo. Never calls SocialAPIs."""
import argparse,html,json,os,pathlib,sqlite3,time
from monitor import ROOT,Telegram,ProbeError,TransportError,now,stamp,format_timestamp,message,read_json,write_json
import datetime as dt

COMMANDS=[{'command':c,'description':d} for c,d in [
 ('start','ابدأ هنا: التعليمات فقط'),('sources','المصادر المتاحة'),
 ('demo','عينة محفوظة واحدة من كل مصدر'),('sample','عينة مصدر واحد؛ مثال sample rassd'),
 ('cost','تكلفة التجربة والمتابعة')]]

class Demo:
 def __init__(self,client,sources,samples,db,expires_at):
  self.client=client;self.sources=sources;self.samples=samples;self.db=db;self.expires_at=expires_at;self.sent=0;self.last_send=0
  db.executescript('CREATE TABLE IF NOT EXISTS handled(update_id INTEGER PRIMARY KEY); CREATE TABLE IF NOT EXISTS demo_requests(chat_id TEXT PRIMARY KEY,at REAL);')
 def send(self,chat,text):
  if self.sent>=100:raise ProbeError('Demo message budget exhausted')
  pause=1.3-(time.monotonic()-self.last_send)
  if pause>0:time.sleep(pause)
  result=self.client.call('sendMessage',{'chat_id':str(chat),'text':text,'parse_mode':'HTML','link_preview_options':{'is_disabled':True}})
  self.last_send=time.monotonic()
  if not isinstance(result,dict) or not result.get('message_id'):raise ProbeError('Telegram acknowledgement missing')
  self.sent+=1
  return result
 def help(self):
  return ('<b>تجربة كشيدة لرصد Facebook</b>\n\n'
   '/sources — المصادر المتاحة\n/demo — عينة واحدة محفوظة من كل مصدر\n'
   '/sample rassd — رصد فقط\n/sample youm7 — اليوم السابع فقط\n/sample mazid — مزيد فقط\n'
   '/cost — حساب التكلفة\n\n'
   'الدخول و/start يعرضان التعليمات فقط. اكتب /demo مرة أخرى لإعادة العينات عند الحاجة.\n'
   'العينات محفوظة من اختبار سابق، وليست آخر الأخبار. هذه الأوامر لا تسحب Facebook ولا تستهلك رصيده. '
   'الصور وملفات الفيديو غير مضمنة في هذا العرض؛ رابط الأصل موجود.\n\n'
   'جلسة استقبال الأوامر الحالية حتى '+format_timestamp(self.expires_at)+'.')
 def handle(self,update):
  mid=update.get('update_id');m=update.get('message') or {};chat=m.get('chat') or {};text=m.get('text') or ''
  if not isinstance(mid,int) or chat.get('type')!='private' or (m.get('from') or {}).get('is_bot') or not isinstance(text,str) or not text.startswith('/'):return
  if not isinstance(chat.get('id'),int):return
  if self.db.execute('SELECT 1 FROM handled WHERE update_id=?',(mid,)).fetchone():return
  # Mark before sending: an ambiguous network failure must not trigger duplicate sends.
  self.db.execute('INSERT INTO handled VALUES(?)',(mid,));self.db.commit()
  args=text.strip().split();cmd=args[0].lower().split('@')[0];cid=str(chat['id'])
  if cmd in ['/start','/help']:return [self.send(cid,self.help())]
  if cmd=='/sources':
   lines=['<b>المصادر المحددة للتجربة</b>']
   for source in self.sources:
    lines.append(html.escape(source['name'])+' — <code>/sample '+html.escape(source['id'])+'</code>')
   lines.append('\nتعديل القائمة يتم من sources.json في المشروع؛ لا يوجد بحث شامل في Facebook.')
   return [self.send(cid,'\n'.join(lines))]
  if cmd=='/cost':return [self.send(cid,'<b>تكلفة واضحة</b>\n/start و/demo وإعادة العينات: صفر طلبات Facebook.\nسحب جديد من مصدر واحد بحد3: 1 Credit في الاختبار.\nسحب المصادر الخمسة: 5 Credits.\n60 مصدرًا كل30 دقيقة لشهر30 يومًا: 86,400 Credit؛ باقة Mega بسعر179 دولارًا للبيانات فقط.\nالفحص يُحسب حتى لو لم يوجد منشور جديد. الاستضافة والطلبات الإضافية خارج الحساب.\nالأسعار: 6 نوفمبر2026 — https://socialapis.io/pricing')]
  if cmd not in ['/demo','/sample']:return [self.send(cid,'اكتب /start للتعليمات. سحب منشورات جديدة يتم يدويًا من GitHub؛ هذه النسخة تعرض عينات محفوظة فقط.')]
  chosen=self.samples if cmd=='/demo' else [p for p in self.samples if len(args)>1 and p['source_id']==args[1].lower()]
  if not chosen:return [self.send(cid,'اختر مصدرًا من /sources؛ مثال: <code>/sample rassd</code>')]
  last=self.db.execute('SELECT at FROM demo_requests WHERE chat_id=?',(cid,)).fetchone()
  if last and time.time()-last[0]<30:return [self.send(cid,'انتظر30 ثانية بين طلبات العينات، ثم أعد نفس الأمر.')]
  self.db.execute('INSERT INTO demo_requests VALUES(?,?) ON CONFLICT(chat_id) DO UPDATE SET at=excluded.at',(cid,time.time()));self.db.commit()
  results=[]
  for p in chosen[:5]:results.append(self.send(cid,message({**p,'sample_note':'عينة محفوظة للاختبار؛ ليست تحديثًا مباشرًا'})))
  return results

def main():
 p=argparse.ArgumentParser();p.add_argument('--minutes',type=int,choices=[15,30,60],default=30);p.add_argument('--smoke',action='store_true');args=p.parse_args()
 token=os.environ.get('TELEGRAM_BOT_TOKEN');chat=os.environ.get('TELEGRAM_CHAT_ID')
 if not token or not chat:raise ProbeError('Telegram secrets missing')
 client=Telegram(token,chat);verified=client.verify()
 if verified.get('bot_username')!='test_kashida_bot':raise ProbeError('Unexpected bot')
 webhook=client.call('getWebhookInfo')
 if webhook.get('url'):raise ProbeError('Existing webhook found; no changes made')
 sources=read_json(ROOT/'sources.json');samples=read_json(ROOT/'demo_samples.json')
 expires=stamp(now()+dt.timedelta(minutes=args.minutes));db=sqlite3.connect(ROOT/'data/demo.sqlite')
 demo=Demo(client,sources,samples,db,expires)
 if args.smoke:
  if client.call('setMyCommands',{'commands':COMMANDS}) is not True:raise ProbeError('Command registration failed')
  configured=client.call('getMyCommands')
  response=demo.handle({'update_id':-1,'message':{'chat':{'id':int(client.chat),'type':'private'},'text':'/start'}})
  result={'ready':True,'bot_username':verified['bot_username'],'facebook_data_requests':0,'owner_help_messages_sent':len(response or []),'sample_messages_sent':0,'registered_commands':[x['command'] for x in configured]}
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
 print(json.dumps({'listening':False,'messages_sent':demo.sent,'facebook_data_requests':0,'reason':'session_or_message_budget_finished'}),flush=True);db.close()

if __name__=='__main__':
 (ROOT/'data').mkdir(exist_ok=True)
 try:main()
 except ProbeError as exc:print('Stopped: '+str(exc),flush=True);raise SystemExit(1)

"""Saved-demo webhook. No polling, session expiry, or Facebook collection."""
import hashlib,hmac,json,os,sqlite3,time
from monitor import Telegram,ProbeError
from telegram_demo import Demo

class Store:
 def __init__(self):
  import psycopg
  self.db=psycopg.connect(os.environ['DATABASE_URL'],connect_timeout=12,autocommit=True)
 def close(self):self.db.close()
 def snapshot(self):
  row=self.db.execute('SELECT payload FROM demo_snapshot WHERE id=1').fetchone()
  if not row:raise ProbeError('Saved demo unavailable')
  return row[0]
 def claim(self,ident,chat_hash,command):
  return self.db.execute("INSERT INTO telegram_updates(update_id,chat_hash,command,status) VALUES(%s,%s,%s,'started') ON CONFLICT DO NOTHING RETURNING update_id",(ident,chat_hash,command)).fetchone() is not None
 def cooldown(self,chat_hash):
  return self.db.execute("INSERT INTO telegram_cooldowns(chat_hash) VALUES(%s) ON CONFLICT(chat_hash) DO UPDATE SET requested_at=now() WHERE telegram_cooldowns.requested_at<=now()-interval '30 seconds' RETURNING chat_hash",(chat_hash,)).fetchone() is not None
 def finish(self,ident,count,status='sent'):
  self.db.execute('UPDATE telegram_updates SET status=%s,messages=%s WHERE update_id=%s',(status,count,ident))
 def recent_demo_messages(self):
  row=self.db.execute("SELECT coalesce(max(messages),0) FROM telegram_updates WHERE command='/demo' AND status='sent' AND created_at>now()-interval '30 minutes'").fetchone()
  return row[0]

def authorized(provided,expected):
 return isinstance(provided,str) and bool(expected) and hmac.compare_digest(provided.encode(),expected.encode())

def command_update(update):
 if not isinstance(update,dict):return None
 ident=update.get('update_id');message=update.get('message') or {};chat=message.get('chat') or {};text=message.get('text')
 if not isinstance(ident,int) or isinstance(ident,bool) or chat.get('type')!='private' or not isinstance(chat.get('id'),int) or (message.get('from') or {}).get('is_bot') or not isinstance(text,str):return None
 text=text.strip()
 if not text:return None
 if text.lower()=='start':text='/start'
 if not text.startswith('/'):return None
 return ident,chat['id'],text.split()[0].lower().split('@')[0]

def process(update,store,client):
 parsed=command_update(update)
 if parsed is None:return {'ok':True,'ignored':True}
 ident,chat,command=parsed
 fingerprint=hmac.new(client.token.encode(),str(chat).encode(),hashlib.sha256).hexdigest()
 # Claim globally before any send; Telegram retries cannot replay a delivery.
 snapshot=store.snapshot()
 if not store.claim(ident,fingerprint,command):return {'ok':True,'duplicate':True}
 db=sqlite3.connect(':memory:')
 demo=Demo(client,snapshot['sources'],snapshot['posts'],db,None,snapshot.get('trends'))
 try:
  if command=='/demo' and not store.cooldown(fingerprint):demo.send(str(chat),'انتظر30 ثانية بين طلبات العينات، ثم أعد نفس الأمر.')
  else:demo.handle(update)
  store.finish(ident,demo.sent)
  return {'ok':True,'messages_sent':demo.sent,'cached_posts':len(demo.samples),'facebook_data_requests':0}
 except Exception:
  # An ambiguous network send is not retried automatically. A new /demo can replay.
  store.finish(ident,demo.sent,'delivery_uncertain')
  print(json.dumps({'event':'telegram_delivery_uncertain','update_id':ident,'messages_sent':demo.sent}),flush=True)
  return {'ok':True,'delivery_uncertain':True,'messages_sent':demo.sent}
 finally:db.close()

def admin_update(command):
 if command not in ['/start','/sources','/demo','/trends']:raise ValueError('Unsupported smoke command')
 return {'update_id':-time.time_ns(),'message':{'chat':{'id':int(os.environ['TELEGRAM_CHAT_ID']),'type':'private'},'text':command,'from':{'is_bot':False}}}

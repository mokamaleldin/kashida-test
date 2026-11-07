"""Authenticated Telegram webhook on Vercel Python Functions."""
import json,os,pathlib,sys,urllib.parse
from http.server import BaseHTTPRequestHandler
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from webhook_service import Store,authorized,process,admin_update
from monitor import Telegram
from telegram_demo import COMMANDS

class handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def reply(self,status,payload):
  body=json.dumps(payload,ensure_ascii=False).encode()
  self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
 def do_GET(self):
  if urllib.parse.urlsplit(self.path).path!='/api/telegram':return self.reply(404,{'ok':False})
  store=None
  try:
   store=Store();snapshot=store.snapshot()
   self.reply(200,{'ok':True,'mode':'saved_demo_webhook','cached_posts':len(snapshot['posts']),'sources':len(snapshot['sources']),'session_expires_at':None,'facebook_data_requests':0})
  except Exception:self.reply(503,{'ok':False,'error':'saved_demo_unavailable'})
  finally:
   if store:store.close()
 def do_POST(self):
  if urllib.parse.urlsplit(self.path).path!='/api/telegram':return self.reply(404,{'ok':False})
  token=os.environ.get('TELEGRAM_BOT_TOKEN','').strip();secret=os.environ.get('WEBHOOK_SECRET','')
  if not token or not secret:return self.reply(503,{'ok':False,'error':'configuration_missing'})
  action=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get('admin',[''])[0]
  admin=action in ['smoke','configure','status']
  if admin:
   valid=authorized(self.headers.get('Authorization'), 'Bearer '+token)
  else:valid=authorized(self.headers.get('X-Telegram-Bot-Api-Secret-Token'),secret)
  if not valid:return self.reply(403,{'ok':False})
  try:
   size=int(self.headers.get('Content-Length','0'))
   if not 0<size<=131072:return self.reply(413,{'ok':False})
   update=json.loads(self.rfile.read(size))
   if action=='smoke':update=admin_update(update.get('command','/start'))
  except (ValueError,TypeError,AttributeError):return self.reply(400,{'ok':False})
  store=None
  try:
   if action=='configure':
    url=update.get('webhook_url','');parts=urllib.parse.urlsplit(url)
    hosts={os.environ.get('VERCEL_URL'),os.environ.get('VERCEL_PROJECT_PRODUCTION_URL')}
    if parts.scheme!='https' or parts.netloc not in hosts or parts.path!='/api/telegram' or parts.query or parts.fragment:return self.reply(400,{'ok':False,'error':'unexpected_webhook_target'})
    client=Telegram(token,os.environ.get('TELEGRAM_CHAT_ID','0'));verified=client.verify()
    if verified.get('bot_username')!='test_kashida_bot':return self.reply(409,{'ok':False,'error':'unexpected_bot'})
    configured=client.call('setWebhook',{'url':url,'secret_token':secret,'max_connections':1,'allowed_updates':['message'],'drop_pending_updates':False})
    client.call('setMyCommands',{'commands':COMMANDS});info=client.call('getWebhookInfo')
    return self.reply(200,{'ok':bool(configured) and info.get('url')==url,'webhook_url':info.get('url'),'pending_updates':info.get('pending_update_count'),'facebook_data_requests':0})
   store=Store();client=Telegram(token,os.environ.get('TELEGRAM_CHAT_ID','0'))
   if action=='status':return self.reply(200,{'ok':True,'recent_demo_messages':store.recent_demo_messages(),'facebook_data_requests':0})
   result=process(update,store,client)
   print(json.dumps({'event':'telegram_webhook','admin_smoke':admin,**result}),flush=True)
   self.reply(200,result)
  except Exception:
   print(json.dumps({'event':'telegram_webhook','error':'request_failed_before_delivery'}),flush=True)
   self.reply(503,{'ok':False,'error':'temporarily_unavailable'})
  finally:
   if store:store.close()

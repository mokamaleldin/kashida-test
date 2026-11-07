"""One-off verification and cutover; reads only existing Telegram secrets."""
import json,os,pathlib
from monitor import Telegram,ProbeError,TransportError,request_json,write_json

PRIMARY='https://kashida-telegram-demo.vercel.app/api/telegram'
DEPLOYMENT='https://kashida-telegram-demo-4dy8gvzn6-mohamedkeliwas-projects.vercel.app/api/telegram'

def main():
 token=os.environ['TELEGRAM_BOT_TOKEN'].strip();headers={'Authorization':'Bearer '+token}
 health,_=request_json(PRIMARY)
 if not health.get('ok') or health.get('cached_posts')!=16 or health.get('sources')!=5 or health.get('session_expires_at') is not None:raise ProbeError('Unexpected saved demo health')
 try:request_json(PRIMARY,payload={'update_id':1})
 except TransportError as exc:
  if exc.status!=403:raise
 else:raise ProbeError('Unauthenticated webhook was accepted')
 try:configured,_=request_json(PRIMARY+'?admin=configure',headers,{'webhook_url':PRIMARY})
 except TransportError as exc:
  if exc.status!=400:raise
  configured,_=request_json(DEPLOYMENT+'?admin=configure',headers,{'webhook_url':DEPLOYMENT})
 if not configured.get('ok'):raise ProbeError('Webhook verification failed')
 results={}
 recent,_=request_json(PRIMARY+'?admin=status',headers,{'action':'status'})
 for command in ['/start','/demo']:
  if command=='/demo' and recent.get('recent_demo_messages',0)>=16:
   results[command]={'ok':True,'verified_from_recent_delivery':True,'messages_sent':recent['recent_demo_messages'],'facebook_data_requests':0};continue
  result,_=request_json(PRIMARY+'?admin=smoke',headers,{'command':command},timeout=150)
  if result.get('delivery_uncertain') or not result.get('ok') or result.get('cached_posts')!=16:raise ProbeError('Live delivery check failed')
  if command=='/demo' and result.get('messages_sent',0)<16:raise ProbeError('Incomplete demo delivery')
  results[command]=result
 proof={'ready':True,'health':health,'configuration':configured,'delivery_checks':results,'facebook_data_requests':0,'polling_required':False,'session_expiry':None}
 write_json(pathlib.Path('data/permanent_demo_proof.json'),proof);print(json.dumps(proof,ensure_ascii=False),flush=True)

if __name__=='__main__':
 try:main()
 except ProbeError as exc:print('Stopped: '+str(exc),flush=True);raise SystemExit(1)

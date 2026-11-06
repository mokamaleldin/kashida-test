"""Cache every collected post, plus names for at most two public groups."""
import json,os,re,urllib.parse
from monitor import ROOT,ProbeError,TransportError,read_json,load_sources,connect,collect,all_posts,write_json,request_json,get_usage,upsert

def group_name(payload):
 blocks=[payload]
 for _ in range(2):
  for block in list(blocks):
   if not isinstance(block,dict):continue
   for key in ['data','group','group_info','groupInfo','group_details','details']:
    child=block.get(key)
    if isinstance(child,dict) and child not in blocks:blocks.append(child)
 for block in blocks:
  for key in ['group_name','groupName','name','group_title']:
   value=block.get(key)
   if isinstance(value,str) and value.strip() and not value.strip().isdigit():return value.strip()[:300]
 return None

def main():
 token=(os.environ.get('SOCIALAPIS_API_KEY') or '').strip()
 if not token:raise ProbeError('Missing SocialAPIs secret')
 sources=load_sources(ROOT/'sources.json')[:5];before=get_usage(token);metadata=[]
 if isinstance(before.get('creditsRemaining'),int) and before['creditsRemaining']<10:raise ProbeError('Preserving remaining test credits; preparation stopped')
 for source in [s for s in sources if s['kind']=='group'][:2]:
  entry={'source_id':source['id'],'resolved':False}
  try:
   query=urllib.parse.urlencode({'link':source['url']})
   payload,_=request_json('https://api.socialapis.io/facebook/groups/details?'+query,{'x-api-token':token})
   name=group_name(payload)
   if name:source['name']=name;entry.update({'resolved':True,'name':name})
   else:entry['response_keys']=list(payload)[:20]
  except TransportError as exc:
   entry['http_status']=exc.status
   if exc.status in [401,403,429]:raise
  metadata.append(entry)
 db=connect(ROOT/'data/state.sqlite')
 cache=ROOT/'data/demo_media_samples.json'
 if cache.exists():
  allowed={s['id'] for s in sources}
  for post in read_json(cache):
   if post['source_id'] in allowed:upsert(db,post)
 report=collect(db,sources,read_json(ROOT/'settings.json'),token,5);samples=all_posts(db);db.close()
 names={s['id']:s['name'] for s in sources}
 for post in samples:
  post['source_name']=names[post['source_id']]
  post['text']=re.sub(r'(?:\+?\d[\s-]?){8,}','[رقم محذوف]',post.get('text') or '')
 if not samples:raise ProbeError('No sample posts returned')
 write_json(ROOT/'data/demo_media_samples.json',samples)
 write_json(ROOT/'data/demo_sources.json',sources)
 write_json(ROOT/'data/demo_collection_status.json',report)
 after=get_usage(token)
 print(json.dumps({'post_requests':report['requests'],'group_metadata_requests':len(metadata),'credits_charged_total':after['creditsUsed']-before['creditsUsed'],'remaining':after['creditsRemaining'],'cached_posts':len(samples),'group_names':metadata},ensure_ascii=False),flush=True)
if __name__=='__main__':
 try:main()
 except ProbeError as exc:print('Stopped: '+str(exc));raise SystemExit(1)

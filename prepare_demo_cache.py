"""Prepare runtime-only full-text/media samples. At most five paid data requests."""
import json,os,re
from monitor import ROOT,ProbeError,read_json,load_sources,connect,collect,all_posts,write_json
from source_sample_check import latest_for_source

def main():
 token=(os.environ.get('SOCIALAPIS_API_KEY') or '').strip()
 if not token:raise ProbeError('Missing SocialAPIs secret')
 sources=load_sources(ROOT/'sources.json')[:5];db=connect(ROOT/'data/state.sqlite')
 report=collect(db,sources,read_json(ROOT/'settings.json'),token,5);posts=all_posts(db);db.close();samples=[]
 for source in sources:
  post=latest_for_source(posts,source['id'])
  if post is not None:
   post['text']=re.sub(r'(?:\+?\d[\s-]?){8,}','[رقم محذوف]',post.get('text') or '')
   samples.append(post)
 if not samples:raise ProbeError('No sample posts returned')
 write_json(ROOT/'data/demo_media_samples.json',samples)
 write_json(ROOT/'data/demo_collection_status.json',report)
 print(json.dumps({'requests':report['requests'],'credits_charged':report['credits_charged'],'remaining':report['remaining'],'samples':len(samples),'with_media':sum(bool(p.get('media')) for p in samples)},ensure_ascii=False),flush=True)
if __name__=='__main__':
 try:main()
 except ProbeError as exc:print('Stopped: '+str(exc));raise SystemExit(1)

"""Create a portable preview; no credentials, raw replies, group text or user profiles."""
import json,pathlib,re
from monitor import ROOT,connect,all_posts,costs

def export(db_path=None):
 db=connect(db_path or ROOT/'data/state.sqlite');posts=all_posts(db);db.close()
 for p in posts:
  p['text']='[نص الجروب لا يُنشر في المعاينة المحمولة. افتح المصدر الأصلي.]' if p['source_id'].startswith('group-') else ' '.join((p.get('text') or '').split()[:25])
  p['text']=re.sub(r'(?:\+?\d[\s-]?){8,}', '[رقم محذوف]',p['text']);p['media']=[]
 report=json.loads((ROOT/'data/last_run.json').read_text()) if (ROOT/'data/last_run.json').exists() else {}
 data={'posts':posts,'report':report,'costs':[costs(n,m) for n in [50,60] for m in [15,30]]}
 content=json.dumps(data,ensure_ascii=False).replace('<','\\u003c')
 html=(ROOT/'dashboard.html').read_text().replace("const r=await fetch('/api/data');if(!r.ok)throw Error();DATA=await r.json();",'DATA='+content+';')
 html=html.replace('بيانات المجموعة الأخيرة، وفلاتر محلية، ومعاينة رسالة Telegram','معاينة محمولة من تجربة فعلية. النصوص مقتطفات محدودة والوسائط تُفتح من المصدر.')
 out=ROOT/'data/preview.html';out.write_text(html,encoding='utf-8');return str(out)
if __name__=='__main__':print(export())

"""Complete three source samples using the prior preview artifact; zero Facebook calls."""
import json,os,pathlib,time
from monitor import Telegram,ProbeError,format_timestamp
from source_sample_check import latest_for_source

def main():
    preview=pathlib.Path('previous/preview.html').read_text()
    marker='DATA='
    start=preview.index(marker,preview.index('async function load()'))+len(marker)
    data,_=json.JSONDecoder().raw_decode(preview[start:])
    client=Telegram(os.environ.get('TELEGRAM_BOT_TOKEN'),os.environ.get('TELEGRAM_CHAT_ID'))
    if client.verify().get('bot_username')!='test_kashida_bot':raise ProbeError('Unexpected test bot')
    results=[]
    for index,source_id in enumerate(['mazid','group-783','group-230']):
        if index:time.sleep(2)
        post=latest_for_source(data['posts'],source_id)
        if post is None:raise ProbeError('Missing cached source sample')
        sample={**post,'media':[],'sample_note':'استكمال اختبار المصدر من السحبة السابقة؛ إرسال نص ورابط'}
        if source_id.startswith('group-'):sample['text']='عينة منشور من الجروب. النص والملف الأصلي غير مضمنين في المعاينة المحفوظة؛ افتح رابط المنشور.'
        item={'source_id':source_id,'source_name':post['source_name'],'post_id':post['id'],'display_published_at':format_timestamp(post.get('published_at'))}
        try:
            response=client.send(sample)
            if not response.get('message_id'):raise ProbeError('No Telegram message acknowledgement')
            entities=response.get('entities',[])
            item.update({'status':'sent','message_id':response['message_id'],'bold_entities':sum(e.get('type')=='bold' for e in entities),'original_link_rendered':any(e.get('type')=='text_link' for e in entities)})
        except ProbeError as exc:
            item.update({'status':'failed_or_unknown','http_status':getattr(exc,'status',None),'error':str(exc)});results.append(item);break
        results.append(item)
    report={'facebook_data_requests':0,'telegram_messages_sent':sum(r['status']=='sent' for r in results),'sources':results,'scheduled':False}
    pathlib.Path('data').mkdir(exist_ok=True);pathlib.Path('data/completion_status.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if report['telegram_messages_sent']!=3:raise SystemExit(1)

if __name__=='__main__':
    try:main()
    except ProbeError as exc:print('Stopped: '+str(exc));raise SystemExit(1)

"""Collect once, then send one clearly marked sample per source, maximum five."""
import html,json,os
from monitor import *

def latest_for_source(posts,source_id):
    rows=[p for p in posts if p['source_id']==source_id]
    return max(rows,key=lambda p:p.get('published_at') or '',default=None)

def deliver_samples(client,sources,posts,lookback_minutes=60):
    results=[];since=now()-dt.timedelta(minutes=lookback_minutes)
    for source in sources[:5]:
        post=latest_for_source(posts,source['id'])
        item={'source_id':source['id'],'source_name':source['name']}
        try:
            if post is None:
                result=client.call('sendMessage',{'chat_id':client.chat,'parse_mode':'HTML','text':'📰 <b>'+html.escape(source['name'])+'</b>\nالمنصة: Facebook\nلم يرجع منشور صالح في هذه السحبة. راجع ملخص التشغيل؛ لا يعني ذلك أن المصدر لم ينشر.'})
                item['status']='source_status_sent'
            else:
                published=parse_time(post.get('published_at'))
                old=published is None or published<since
                words=(post.get('text') or '').split()
                sample={**post,'text':' '.join(words[:25])+('…' if len(words)>25 else ''),'sample_note':'عينة أقدم من فترة المتابعة لاختبار المصدر' if old else 'عينة اختبار من هذه السحبة'}
                result=client.send(sample);item.update({'status':'sample_sent','post_id':post['id'],'old_sample':old,'delivered_type':'photo' if result.get('photo') else 'video' if result.get('video') else 'text'})
            if not result.get('message_id'):raise ProbeError('Telegram did not acknowledge a message id')
            item['message_id']=result['message_id']
            entities=result.get('caption_entities',result.get('entities',[]));item['bold_entities']=sum(x.get('type')=='bold' for x in entities)
            item['original_link_rendered']=any(x.get('type')=='text_link' for x in entities)
            if post is not None:item['display_published_at']=format_timestamp(post.get('published_at'))
        except ProbeError:
            item['status']='delivery_unknown_or_rejected';results.append(item);break
        results.append(item)
    return results

def main():
    api=(os.environ.get('SOCIALAPIS_API_KEY') or '').strip();token=os.environ.get('TELEGRAM_BOT_TOKEN');chat=os.environ.get('TELEGRAM_CHAT_ID')
    if not api or not token or not chat:raise ProbeError('Missing configured API orTelegram secrets')
    client=Telegram(token,chat);identity=client.verify()
    if identity.get('bot_username')!='test_kashida_bot':raise ProbeError('Unexpected bot; no collection orsend performed')
    settings=read_json(ROOT/'settings.json');sources=load_sources(ROOT/'sources.json')[:5];db=connect(ROOT/'data/state.sqlite')
    report=collect(db,sources,settings,api,5);write_json(ROOT/'data/last_run.json',report)
    report['telegram_samples']=deliver_samples(client,sources,all_posts(db),settings.get('lookback_minutes',60))
    report['telegram_messages_sent']=sum(x['status'] in ['sample_sent','source_status_sent'] for x in report['telegram_samples'])
    report['scheduled']=False;write_json(ROOT/'data/source_sample_status.json',report);db.close()
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':
    try:main()
    except ProbeError as exc:print('Stopped: '+str(exc));raise SystemExit(1)

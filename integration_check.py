"""One-off credentials integration check. No paid Facebook calls, at most one Telegram message."""
import json,os
from monitor import ROOT,Telegram,get_usage,write_json,ProbeError

def main():
    result={'facebook_data_requests':0,'telegram_messages_sent':0,'missing':[]}
    token=os.environ.get('SOCIALAPIS_API_KEY')
    if token:
        try:result['socialapis']=get_usage(token)
        except ProbeError:result['socialapis']={'error':'Credential ornetwork check failed'}
    else:result['missing'].append('SOCIALAPIS_API_KEY')
    bot=os.environ.get('TELEGRAM_BOT_TOKEN');chat=os.environ.get('TELEGRAM_CHAT_ID')
    if not bot:result['missing'].append('TELEGRAM_BOT_TOKEN')
    if not chat:result['missing'].append('TELEGRAM_CHAT_ID')
    if bot and chat:
        try:
            client=Telegram(bot,chat);result['telegram']=client.verify()
            if os.environ.get('SEND_TEST_MESSAGE')=='true':
                response=client.call('sendMessage',{'chat_id':chat,'text':'اختبار كشيدة ✅\nربط Telegram يعمل.\nهذه رسالة اختبار واحدة، ولا توجد متابعة دورية مفعّلة.'})
                result['telegram_messages_sent']=1 if response.get('message_id') else 0
        except ProbeError:result['telegram']={'error':'Verification orsend failed; no automatic retry'}
    write_json(ROOT/'data/integration_status.json',result);print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()

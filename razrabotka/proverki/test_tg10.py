import os, sys
if os.path.exists('/tmp/stavki.sqlite3'): os.remove('/tmp/stavki.sqlite3')
if os.path.exists('/tmp/config.json'): os.remove('/tmp/config.json')
sys.argv=['x']
exec(open('/home/claude/bet/test_direct.py',encoding='utf-8').read().split('# sims')[0])
sent=[]
cfg2=dict(S.DEFAULT_CONFIG)
tg=S.Telegram(cfg2)
def fake_api(method, params, timeout=20):
    sent.append((method, params))
    if method=='getMe': return {'result':{'username':'stavki_test_bot'}}
    if method=='getUpdates': return {'result':[{'update_id':5,'message':{'chat':{'id':777},'text':'старт'}}]}
    return {'ok':True}
tg.api=fake_api
tg.connect('123:ABC')
print('статус:',S.STATE.status.get('telegram'), 'чат', cfg2['telegram_chat_id'])
import json; print('config.json:', json.loads(open('/tmp/config.json',encoding='utf-8').read()))
assert cfg2['telegram_chat_id']==777 and tg.ready()
S.TG=tg
S.STRATEGIES=[(c_,d,(lambda v: v['ev']>=0.01 and v['odds']<=4.0),k) for c_,d,_x,k in S.STRATEGIES]
c.record_paper(); c.record_paper()
print('в очереди:', len(tg.q)); 
for t in tg.q: print('---\n'+t)
assert len(tg.q)==2      # два события с ценой сайта (Борнмут, Ман Сити), повтор не шлёт
print('ВСЁ ОК')

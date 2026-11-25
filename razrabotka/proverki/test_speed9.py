import os, sys
if os.path.exists('/tmp/stavki.sqlite3'): os.remove('/tmp/stavki.sqlite3')
sys.argv=['x']
exec(open('/home/claude/bet/test_direct.py',encoding='utf-8').read().split('# sims')[0])
S.time.sleep=lambda x: None
base=c.page
class Flaky:
    def __init__(s, mode): s.mode=mode; s.seen={}
    def evaluate(s, js, url):
        if isinstance(url,list): return [s.one(u) for u in url]
        return base.evaluate(js,url)
    def one(s,u):
        n=s.seen.get(u,0); s.seen[u]=n+1
        if s.mode=='once' and n==0 and 'match_winner' in u: return {'status':502,'text':'','ms':5}
        if s.mode=='always': return {'status':502,'text':'','ms':5}
        return dict(base.evaluate(None,u),ms=5)
ids=[3515898,3515890]
ms=[S.STATE.matches[i] for i in ids]
# 1) 502 на половине запросов, повтор проходит — ошибок нет, пакет не уменьшается
c.page=Flaky('once'); c.batch_cur=6
e,t=c.update_batch(ms); print('один 502 + повтор: ошибок',e,'из',t,'пакет',c.batch_cur,'занят за 10 мин',len(c.busy_log))
assert e==0 and c.batch_cur==6 and c.busy_log
# 2) сервер всё время занят — пакет уменьшается, матчи вернутся в очередь через ~15 с
c.page=Flaky('always')
for m in ms: m['last_update']=0
e,t=c.update_batch(ms); print('всегда 502: ошибок',e,'из',t,'пакет',c.batch_cur,'пауза',c.extra_pause)
assert e==t and c.batch_cur==3 and c.extra_pause==1.0
now=clock[0]
for m in ms:
    due=m['last_update']+c.interval_for(m,now)-now; print('матч',m['id'],'повтор через',round(due),'с'); assert 10<=due<=16
# 3) 10 чистых пакетов — пакет растёт обратно
c.page=Flaky('ok')
for k in range(30): c.update_batch(ms)
print('после 30 чистых пакетов: пакет',c.batch_cur,'пауза',c.extra_pause); assert c.batch_cur==6 and c.extra_pause==0
st=S.STATE.snapshot()['status']; print('свежесть ближайших:',st['near'],st['near_age'],st['near_max'])
print('ВСЁ ОК')

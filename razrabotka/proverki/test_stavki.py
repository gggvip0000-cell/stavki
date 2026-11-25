import json, glob, sys, time, threading, urllib.request, types
sys.path.insert(0, '/home/claude/stavki')
import stavki as S
R='/home/claude/bet/r1/'
def load(fn):
    t=open(fn,encoding='utf-8').read(); u,b=t.split('\n\n',1); return u,json.loads(b)
# map url-> json from captured files
store={}
for fn in glob.glob(R+'*_net_*.txt'):
    u,_=open(fn,encoding='utf-8').readline().strip(),None
    if 'next-api' in u:
        _,j=load(fn); store[u.replace('https://odds.ru','')]=j
class FakePage:
    def evaluate(self, js, url):
        if isinstance(url, list):
            return [dict(self.evaluate(js,u), ms=1200) for u in url]
        if url in store: return {'status':200,'text':json.dumps(store[url])}
        return {'status':404,'text':'nf'}
# 1) расчёт
d=store['/next-api/coefficients/rates/ru/?sport=football&matchId=3515898&metricId=full_time&periodId=full_time&marketId=total_points&source=default']['data']
vals,pr=S.values_from_rates(d); vals.sort(key=lambda v:-v['ev'])
print('pin rows',pr,'vals',len(vals)); print(vals[:3])
# 2) цикл с фейковым браузером, дата/время подставим
cfg=dict(S.DEFAULT_CONFIG, hours_ahead=36, pause_between_requests=0)
con=S.db_open.__wrapped__() if hasattr(S.db_open,'__wrapped__') else None
S.HERE=__import__('pathlib').Path('/tmp'); con=S.db_open()
c=S.Collector(cfg,con); c.page=FakePage()
# сдвинем "сейчас": events на 2026-11-21, начало 15:30 мск; подменим datetime.now через MSK-время  
import datetime
class FDT(datetime.datetime):
    @classmethod
    def now(cls, tz=None): return datetime.datetime(2026,11,21,9,30,tzinfo=S.MSK)
S.datetime.datetime=FDT
real_time=time.time
time_now=datetime.datetime(2026,11,21,9,30,tzinfo=S.MSK).timestamp()
S.time.time=lambda: time_now
c.refresh_events()
print('tracked',len(S.STATE.matches))
S.MY_BOOKMAKERS=['Фонбет','Винлайн','PARI']
print('batch:', c.update_batch([S.STATE.matches[3515898], S.STATE.matches[3515890], S.STATE.matches[next(iter(S.STATE.matches))]]))
snap=S.STATE.snapshot()
print('values',len(snap['values']))
for v in snap['values'][:6]: print(round(v['ev']*100,1),v['match'],v['market_name'],v['outcome'],v['bookmaker'],v['odds'],v['fair'],v['start'])
print(con.execute('select count(*) from pin').fetchone(), con.execute('select count(*) from value_seen').fetchone())
# 3) HTTP
S.time.time=real_time
srv=S.ThreadingHTTPServer(('127.0.0.1',8799),S.Handler); threading.Thread(target=srv.serve_forever,daemon=True).start()
print(urllib.request.urlopen('http://127.0.0.1:8799/').read()[:60])
st=json.loads(urllib.request.urlopen('http://127.0.0.1:8799/api/state').read()); print(st['status']); print(st['margins']); print(st['mine'])

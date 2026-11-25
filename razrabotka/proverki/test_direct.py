import json, glob, sys, time, re, datetime
sys.path.insert(0, '/home/claude/stavki')
import stavki as S
RK='/home/claude/bet/rk/'; R1='/home/claude/bet/r1/'
def load(fn):
    t=open(fn,encoding='utf-8',errors='ignore').read(); u,b=t.split('\n\n',1); return u.strip(),json.loads(b)
# odds.ru store
store={}
for fn in glob.glob(R1+'*_net_*.txt'):
    u=open(fn,encoding='utf-8').readline().strip()
    if 'next-api' in u: store[u.replace('https://odds.ru','')]=load(fn)[1]
# fonbet sequence: full = listLight, затем дельты по порядку
seq=[]
for fn in glob.glob(RK+'fonbet_net_*.txt'):
    u=open(fn,encoding='utf-8',errors='ignore').readline()
    if '/events/list?' in u: seq.append((int(re.search(r'_(\d+)\.txt',fn).group(1)),fn))
seq=[fn for n,fn in sorted(seq)]
full=[fn for fn in glob.glob(RK+'fonbet_net_*.txt') if 'listLight' in open(fn,encoding='utf-8',errors='ignore').readline()][0]
class _Resp:
    def __init__(self,d): self.status=d['status']; self._t=d['text']
    def text(self): return self._t
class _Req:
    def __init__(self,b): self.b=b
    def get(self,url,headers=None,timeout=None): return _Resp(self.b.evaluate(None,url))
class _Ctx:
    def __init__(self,b): self.request=_Req(b)
class FakeBook:
    def __init__(self): self.i=0; self.context=_Ctx(self)
    def evaluate(self, js, url):
        if 'geoCategories' in url: return {'status':200,'text':open('/home/claude/bet/rk/fonbet_net_045.txt',encoding='utf-8',errors='ignore').read().split('\n\n',1)[1]}
        if 'version=0' in url or 'version=' not in url: return {'status':200,'text':json.dumps(load(full)[1])}
        fn=seq[min(self.i,len(seq)-1)]; self.i+=1
        return {'status':200,'text':json.dumps(load(fn)[1])}
class FakeOdds:
    def evaluate(self, js, url):
        if isinstance(url,list): return [dict(self.evaluate(js,u),ms=900) for u in url]
        if url in store: return {'status':200,'text':json.dumps(store[url])}
        return {'status':404,'text':'nf'}
T0=datetime.datetime(2026,11,21,14,50,tzinfo=S.MSK).timestamp()
clock=[T0]
S.time.time=lambda: clock[0]
class FDT(datetime.datetime):
    @classmethod
    def now(cls, tz=None): return datetime.datetime.fromtimestamp(clock[0], tz or S.MSK)
S.datetime.datetime=FDT
S.HERE=__import__('pathlib').Path('/tmp')
S.MY_BOOKMAKERS=['Фонбет','Винлайн','PARI']
cfg=dict(S.DEFAULT_CONFIG, pause_between_requests=0)
c=S.Collector(cfg,S.db_open()); c.page=FakeOdds()
print('feeds',[f.name for f in c.feeds])
c.refresh_events()
# odds.ru: Pinnacle по Ман Сити (данные утренние — для проверки механики)
c.update_batch([S.STATE.matches[3515898], S.STATE.matches[3515890]])
fb=c.feeds[0]; fb.page=FakeBook()
for k in range(25):
    clock[0]+=6; c.poll_feeds()
assert S.STATE.status['feeds'].get('Фонбет',{}).get('last_ok'), 'нет статуса прямой линии Фонбета'
print('fonbet events',len(fb.events),'football',len(fb.football()),'status',S.STATE.status['feeds'].get('Фонбет'))
mc=[e for e in fb.events.values() if e.get('team1')=='Манчестер Сити' and e.get('level')==1]
print('ManCity fonbet', mc[0]['id'] if mc else None, fb.match_map.get(mc[0]['id']) if mc else None)
print('odds',fb.odds_of(mc[0]['id']) if mc else None)
snap=S.STATE.snapshot()
for v in snap['values'][:12]:
    print(v['source'],v['bookmaker'],v['match'],v['market_name'],v['outcome'],v['odds'],v['fair'],round(v['ev']*100,1),'age',v['age'],'pin',v['pin_age'])
# sims
print(S.team_sim('ФК Эйндховен','Эйндховен'), S.team_sim('Манчестер Сити','Манчестер Юнайтед'), S.team_sim('Норвич Сити','Норвич'))

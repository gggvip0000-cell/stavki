import json, glob, re, difflib, datetime, time, math, sys
sys.path.insert(0,'/home/claude/stavki')
import stavki as S
ns=dict(vars(S)); exec(open('/home/claude/bet/pin_code.py',encoding='utf-8').read(), ns)
MSK=S.MSK
def loadj(fn):
    t=open(fn,encoding='utf-8',errors='ignore').read(); return json.loads(t[t.find('{'):] if fn.endswith('.txt') and 'football_events' in fn else t.split('\n\n',1)[1])
matches={}
for fn in glob.glob('/home/claude/bet/rr/football_events_*.txt'):
    t=open(fn,encoding='utf-8').read(); d=json.loads(t[t.find('{'):])['data']
    for lg in d['leagues']:
        for ev in lg['events']:
            if ev['status']['name']!='upcoming': continue
            st=datetime.datetime.strptime(f"{ev['date']} {ev['time']}",'%Y-%m-%d %H:%M').replace(tzinfo=MSK).timestamp()
            h,a=ns['en_names_of'](ev)
            matches[ev['id']]={'id':ev['id'],'home':ev['home']['title'],'away':ev['away']['title'],'home_en':h,'away_en':a,'start':st,'league':lg['title']}
print('odds.ru матчей',len(matches),'с англ. названиями',sum(1 for m in matches.values() if m['home_en']))
def pl(sub):
    for fn in sorted(glob.glob('/home/claude/bet/rp/pin_net_*.txt')):
        t=open(fn,'rb').read(); u,b=t.split(b'\n\n',1)
        if sub in u.decode(): return json.loads(b)
f=ns['PinnacleFeed']()
ns['time'].time=lambda: datetime.datetime(2026,11,21,20,15,tzinfo=MSK).timestamp()
ch=f.ingest(1980, pl('leagues/1980/matchups'), pl('leagues/1980/markets/straight'), matches)
ch+=f.ingest(0, pl('sports/29/matchups/highlighted'), pl('sports/29/markets/highlighted/straight'), matches)
reg=[p for p in f.regular]; mapped=[p for p in reg if f.match_map.get(p)]
print('Pinnacle матчей',len(reg),'сопоставлено',len(mapped),'с честной ценой',len(set(ch)))
for p in reg[:60]:
    r=f.regular[p]; mm=f.match_map.get(p)
    m=matches[mm[0]] if mm else None
    print(('OK ' if mm else '-- ')+f"{r['home']} — {r['away']}", '=>', (m['home']+' — '+m['away']+(' [перевёрнуто]' if mm[1] else '')+' | '+m['home_en']+' / '+m['away_en']) if m else '')
mid=ch[0]; print(matches[mid]['home'],matches[mid]['away'], {k:[round(x,2) for x in v[1]] for k,v in list(f.fair[mid].items())[:5]})
lo=min(m['start'] for m in matches.values()); hi=max(m['start'] for m in matches.values())
inw=[p for p in reg if lo-600<=f.regular[p]['start']<=hi+600]
print('в окне odds.ru:',len(inw),'сопоставлено',sum(1 for p in inw if f.match_map.get(p)))
for p in inw:
    if not f.match_map.get(p):
        r=f.regular[p]; cands=[m for m in matches.values() if abs(m['start']-r['start'])<=20*60]
        best=max(cands,key=lambda m: ns['en_sim'](r['home'],m['home_en'])+ns['en_sim'](r['away'],m['away_en']),default=None)
        print('  нет:',r['home'],'—',r['away'], datetime.datetime.fromtimestamp(r['start'],MSK).strftime('%d %H:%M'),'| ближайший:',best and (best['home_en'],best['away_en']))

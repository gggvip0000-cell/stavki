import sys, json, glob, re, collections
exec(open('/home/claude/bet/test_pin11.py',encoding='utf-8').read().split("mids = [int(")[0])
src=open('/home/claude/bet/test_direct.py',encoding='utf-8').read()
pre=src.split('# fonbet sequence')[1].split('T0=')[0]
RK='/home/claude/bet/rk/'
def load(fn):
    t=open(fn,encoding='utf-8',errors='ignore').read(); u,b=t.split('\n\n',1); return u.strip(),json.loads(b)
exec('seq=[]'+pre.split('seq=[]',1)[1])
fb=S.DirectFeed(S.DIRECT_BOOKS[0]); fb.page=FakeBook()
for k in range(25):
    clock[0]+=6
    try: fb.poll()
    except Exception as e: print('poll',e)
print('Фонбет событий',len(fb.events),'футбол',len(fb.football()),'с подсобытиями',sum(1 for e in fb.football() if fb.kids.get(e['id'])))
fam=collections.Counter()
for e in fb.football():
    for k in fb.odds_of(e['id']): fam[k[0]]+=1
print('рынки Фонбета:',dict(sorted(fam.items())))
c.feeds=[fb]; c.direct_values_for(fb)
vals=list(S.STATE.direct_values.values())
print('совпало матчей Фонбет→odds.ru', S.STATE.status['feeds']['Фонбет']['matched'],'строк с перевесом',len(vals))
by=collections.defaultdict(list)
for v in vals: by[v['market']].append(v['ev'])
for k,l in sorted(by.items()): print(' ',k,len(l),'перевес макс %.1f%%'%(100*max(l)), 'медиана %.1f%%'%(100*sorted(l)[len(l)//2]))
for v in sorted(vals,key=lambda v:-v['ev'])[:6]: print('  ', v['market_name'], v['outcome'], v['odds'], 'честная', v['fair'], '%+.1f%%'%(100*v['ev']), S.STATE.matches[v['match_id']]['title'])

import sys, os, json, glob, datetime
sys.path.insert(0,'/home/claude/stavki'); import stavki as S
st=lambda *a: round(S.settle_one(*a),6)
assert st('ah','Ф1 (-0.5)',-0.5,1.9,1,0)==0.9 and st('ah','Ф1 (-0.5)',-0.5,1.9,1,1)==-1
assert st('ah','Ф1 (-1)',-1.0,1.9,1,0)==0.0 and abs(st('ah','Ф1 (-0.75)',-0.75,2.0,1,0)-0.5)<1e-9
assert abs(st('ah','Ф2 (+0.25)',-0.25,1.9,1,1)-0.45)<1e-9      # фора хозяев −0.25 → гости +0.25, ничья: половина выигрыш
assert st('ah','Ф2 (+1.5)',-1.5,1.5,2,1)==0.5 and st('tt1','Больше (1.5)',1.5,2.0,2,0)==1.0 and st('tt2','Меньше (0.5)',0.5,1.6,3,0)==0.6
print('расчёт форы и инд. тоталов: ок')
# Pinnacle: все рынки на записанных данных
exec(open('/home/claude/bet/test_pin11.py',encoding='utf-8').read().split("mids = [int(")[0])
fams={}
for mid,d in S.STATE.pin_fair.items():
    for k in d: fams[k[0]]=fams.get(k[0],0)+1
print('рынки Pinnacle по матчам:', dict(sorted(fams.items())))
assert fams.get('ah') and fams.get('tt1') and fams.get('h1_1x2')
mid=[m for m,v in S.STATE.matches.items() if 'Ньюкасл' in v['title'] and 'Арсенал' in v['title']][0]
d=S.STATE.pin_fair[mid]
p1x2=d[('1x2',None)][0]; ah=[(k[1],round(v[0][0],3)) for k,v in d.items() if k[0]=='ah']
print('Ньюкасл — Арсенал: П1', round(p1x2[0],3),'П2',round(p1x2[2],3),'| фора хозяев → шанс:',sorted(ah)[:6])
# ориентация: фора хозяев 0 (без ничьей) шанс ≈ П1/(П1+П2)
a0=[v for k,v in ah if k==0.0]
if a0: assert abs(a0[0]-p1x2[0]/(p1x2[0]+p1x2[2]))<0.05, (a0, p1x2)
c=[k for k in d if k[0].startswith('c_')]; print('угловые у матча:', c[:4])
print('ВСЁ ОК')

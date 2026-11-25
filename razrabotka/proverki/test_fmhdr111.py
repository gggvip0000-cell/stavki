"""-111: FotMob без событий матча (мелкие лиги) — счёт основного времени из шапки, если окончен в основное время."""
import sys, json, copy; sys.path.insert(0, '/home/claude/stavki'); import stavki as S
t = open('/home/claude/bet/rs3/fotmob_details2_1.txt').read(); j = json.loads(t[t.find('{'):])
h = j['header']; st = h['status']
start = 1795000000
m = {'id': 1, 'timeTS': start * 1000, 'home': {'name': h['teams'][0]['name']}, 'away': {'name': h['teams'][1]['name']}}
def run(jj, home=h['teams'][0]['name'], away=h['teams'][1]['name']):
    x = S.ExtStats.__new__(S.ExtStats)
    x.fm_list = lambda ts: [m]
    x.get = lambda key, url: jj
    pass
    return S.ExtStats.fotmob(x, home, away, start)
full = run(j); print('с событиями:', full.get('ft'), full.get('ht'))
noev = copy.deepcopy(j); noev['content']['matchFacts'] = {}
r = run(noev); print('без событий:', r.get('ft'), r.get('ht')); assert r['ft'] == (4, 2) and 'ht' not in r
rr = run(noev, h['teams'][1]['name'], h['teams'][0]['name']); print('хозяева наоборот:', rr.get('ft')); assert rr['ft'] == (2, 4)
aet = copy.deepcopy(noev); aet['header']['status']['reason'] = {'short': 'AET', 'shortKey': 'afterextra_short'}
assert 'ft' not in run(aet)
ex = copy.deepcopy(noev); ex['header']['status']['halfs']['firstExtraHalfStarted'] = '21.11.2026 18:30:00'
assert 'ft' not in run(ex)
print('ВСЁ ОК')

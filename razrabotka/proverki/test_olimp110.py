"""-110: Олимп — роспись «УГЛ»-события (инд. тоталы угловых, marketId 7/8); берётся, только пока свежая."""
import sys, json, time; sys.path.insert(0, '/home/claude/stavki'); import stavki as S
d = json.load(open('/home/claude/bet/r1631/report.json'))['olimp_recon']
comp, ugl = json.loads(d['sample_comp']), json.loads(d['sample_ugl_comp'])
evs = S.olimp_events(comp) + S.olimp_events(ugl)
now = time.time()
for e in evs:
    e['startDateTime'] = int(now + 3600)
bristol = {'id': '86343880', 'name': 'Бристоль Сити - Рексэм', 'team1Name': 'Бристоль Сити', 'team2Name': 'Рексэм',
           'names': {'2': 'Bristol City - Wrexham'}, 'startDateTime': int(now + 1800), 'competitionId': '1',
           'outcomes': [{'marketId': 1, 'shortName': s, 'probability': p} for s, p in (('П1', '2.1'), ('Х', '3.3'), ('П2', '3.5'))]}
uid = [k for k, e in ((str(e['id']), e) for e in evs) if e.get('parentId') == '86343880'][0]
det = dict([e for e in evs if str(e['id']) == uid][0])
det['outcomes'] = list(det.get('outcomes') or []) + [
    {'marketId': 7, 'param': '4.50', 'probability': '2.32', 'unprocessedName': 'УГЛ Бристоль Сити (4.5) мен', 'basketId': f'{uid}:2:7:4.5:1:NULL:NULL:1'},
    {'marketId': 7, 'param': '4.50', 'probability': '1.54', 'unprocessedName': 'УГЛ Бристоль Сити (4.5) бол', 'basketId': f'{uid}:3:7:4.5:1:NULL:NULL:1'},
    {'marketId': 8, 'param': '3.50', 'probability': '2.91', 'unprocessedName': 'УГЛ Рексэм (3.5) мен', 'basketId': f'{uid}:2:8:3.5:1:NULL:NULL:1'},
    {'marketId': 8, 'param': '3.50', 'probability': '1.36', 'unprocessedName': 'УГЛ Рексэм (3.5) бол', 'basketId': f'{uid}:3:8:3.5:1:NULL:NULL:1'}]
full = json.dumps([{'payload': {'competitionsWithEvents': [{'events': evs + [bristol]}]}}])
calls = []
class PG:
    url = 'x'
    def evaluate(s, js, u):
        calls.append(u)
        if 'sports-with' in u:
            return {'s': 200, 't': full}
        if 'main=false' in u:
            v = u.split('vids%5B%5D=')[1].split('%3A')[0]
            return {'s': 200, 't': json.dumps([{'payload': [det if v == uid else {'id': v, 'team1Name': 'a', 'outcomes': []}]}])}
        return {'s': 200, 't': json.dumps([{'payload': {'events': []}}])}
f = S.OlimpFeed(); f.page = PG()
f.poll()                                  # вся линия
o = f.odds_of('86343880'); assert ('c_tt1', 4.5) not in o
for _ in range(15):                       # чемпионаты и росписи по очереди
    f.poll()
det_calls = [u for u in calls if 'main=false' in u]
print('росписей угловых запрошено:', len(det_calls), '| первая —', det_calls[0][-40:])
assert any(uid in u for u in det_calls[:2]), 'ближайший матч (Бристоль, через 30 мин) — первым'
o = f.odds_of('86343880')
print({k: v for k, v in o.items() if k[0].startswith('c_tt')})
assert o[('c_tt1', 4.5)] == [1.54, 2.32] and o[('c_tt2', 3.5)] == [1.36, 2.91]   # [Б, М] как outcome_names
# через 3 мин без обновления — роспись устарела, инд. тоталы угловых не отдаются
f.cdet_ts[uid] -= 180
assert ('c_tt1', 4.5) not in f.odds_of('86343880')
print('ВСЁ ОК')

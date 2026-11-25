"""Проверка версии -42: Винлайн напрямую — кадры websocket из разведки 22.11 → WinlineFeed → ставки в окне."""
import os, sys, json, base64
DB = '/tmp/stavki.sqlite3'
if os.path.exists(DB):
    os.remove(DB)
sys.argv = ['x']
exec(open('/home/claude/bet/test_direct.py', encoding='utf-8').read().split('# sims')[0])
W = [w for w in json.load(open('/home/claude/bet/rw/ws_frames.json')) if 'data_ng' in w['url'] and w['dir'] == 'in']
f = S.WinlineFeed()


class P:
    def wait_for_timeout(self, ms): pass
f.page = P()
f.started = clock[0]
f.queue = [base64.b64decode(w['b64']) for w in W]
f.poll()
evs = f.football()
print('Винлайн: футбол до матча:', len(evs), '| с рынками:', sum(1 for e in evs if f.odds_of(e['id'])))
assert len(evs) > 500
e0 = next(e for e in evs if f.odds_of(e['id']).get(('1x2', None)))
print('пример:', e0['team1'], '—', e0['team2'], f.odds_of(e0['id']), f.event_url(e0), f.match_odds(e0))
fams = {k[0] for e in evs for k in f.odds_of(e['id'])}
print('рынки:', sorted(fams))
assert fams <= {'1x2', 'total', 'ah', 'h1_1x2', 'h1_total', 'h1_ah'}, fams     # только сверенные со страницей
for e in evs:                                                                    # тотал — [Больше, Меньше]: больше линия → Больше дороже
    tl = sorted((k[1], v) for k, v in f.odds_of(e['id']).items() if k[0] == 'total')
    for (l1, a), (l2, b) in zip(tl, tl[1:]):
        assert a[0] <= b[0] + 1e-9 and a[1] >= b[1] - 1e-9, (e['team1'], tl)
c.feeds.append(f)
c.direct_values_for(f)
st = S.STATE.status['feeds']['Винлайн']
print('сопоставлено с odds.ru:', st['matched'], 'из', st['events'])
assert st['matched'] >= 5          # записи odds.ru (21.11 14:50) и Винлайна (22.11 01:38) пересекаются только ночью — 5 матчей
vals = [v for v in S.STATE.direct_values.values() if v['bookmaker'] == 'Винлайн']
print('ставок Винлайна с перевесом:', len(vals), vals[:2] and [(v['market'], v['outcome'], v['odds'], round(v['ev'], 3), v['bk_url']) for v in vals[:3]])
assert all(v['bk_url'].startswith('https://winline.ru/stavki/event/') for v in vals)
# поток встал — страница открывается заново, ошибка понятная
f.queue = []
f.last_frame = clock[0] - 200; f.started = clock[0] - 200
reloaded = []
f.page.reload = lambda **k: reloaded.append(1)
try:
    f.poll(); assert False
except RuntimeError as ex:
    print('без данных:', ex)
assert reloaded
print('ВСЁ ОК')

"""Проверка -66: замер баскетбола (Фонбет против Pinnacle) — журнал bb_cand и CLV, в окне ничего."""
exec(open('/home/claude/bet/test_paper8.py', encoding='utf-8').read())
import datetime as _dt
clock[0] = T0
f = next(x for x in c.feeds if x.name == 'Фонбет')
bb = S.BasketMeasure(con)
def is_bb(sid):
    sp, h = f.sports.get(sid), 0
    while sp and h < 8:
        if sp.get('id') == 3: return True
        sp, h = f.sports.get(sp.get('parentId')), h + 1
    return False
evs = [e for e in f.events.values() if e.get('level') == 1 and e.get('place') == 'line' and is_bb(e.get('sportId'))
       and e.get('startTime', 0) > clock[0] + 60]
print('баскетбол у Фонбета в записи:', len(evs))
ev = next(e for e in evs if bb.fon_odds(f.factors.get(e['id'], {})))
fo = bb.fon_odds(f.factors.get(ev['id'], {}))
print(ev['team1'], '—', ev['team2'], 'рынков:', len(fo), list(fo)[:6])
tl = next(k for k in fo if k[0] == 'total')
o_over, o_under = fo[tl]
def am(d):  # десятичный → американский
    return round((d - 1) * 100) if d >= 2 else round(-100 / (d - 1))
start_iso = _dt.datetime.fromtimestamp(ev['startTime'], _dt.timezone.utc).isoformat().replace('+00:00', 'Z')
# Pinnacle: тот же матч (хозяева и гости наоборот), на «больше» цена ниже фонбетовской → перевес на «больше»
pin_over, pin_under = o_over * 0.9, None
p = 1 / pin_over; pin_under = 1 / max(0.02, 1.03 - p)
class P:
    headers = {'x': 1}
    def get(self, path):
        if path.startswith('/sports/4/leagues'):
            return [{'id': 77, 'name': 'Test League', 'matchupCount': 1}]
        if path == '/leagues/77/matchups':
            return [{'id': 501, 'type': 'matchup', 'startTime': start_iso, 'isLive': False,
                     'participants': [{'alignment': 'home', 'name': S.lat_key(ev['team2']).title()},
                                      {'alignment': 'away', 'name': S.lat_key(ev['team1']).title()}]}]
        if path == '/leagues/77/markets/straight':
            return [{'matchupId': 501, 'period': 0, 'type': 'total', 'status': 'open',
                     'prices': [{'designation': 'over', 'price': am(pin_over), 'points': tl[1]},
                                {'designation': 'under', 'price': am(pin_under), 'points': tl[1]}]}]
        raise AssertionError(path)
bb.step(f, P())
S.BasketMeasure.pin_req = 0; bb.last = 0; S.BasketMeasure.pin_req = 0; bb.step(f, P())
rows = con.execute('SELECT outcome, odds, ev, teams, pin_teams FROM bb_cand').fetchall()
print('журнал:', rows)
assert rows and rows[0][0].startswith('Больше') and rows[0][2] >= 0.03
assert bb.log and bb.log[-1]['swapped'] is True
clock[0] = ev['startTime'] + 10; bb.last = 0; S.BasketMeasure.pin_req = 0; bb.leagues_ts = clock[0]; bb.step(f, P())
r = bb.report()
print('CLV:', r['n'], r['n_closed'], r['clv_mean'])
assert r['n_closed'] == r['n'] and r['clv_mean'] is not None
import json; json.dumps(r, ensure_ascii=False)
print('сверка линий:', r['line_check'], 'рынки Pinnacle:', r['pin_markets'])
assert r['line_check'].get('total', {}).get('n', 0) >= 1
print('ВСЁ ОК')

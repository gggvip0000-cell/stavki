"""-113: угловые 1-го тайма — только журнал; калибровка Pinnacle на угловых в отчёте."""
import sys, json, time, sqlite3, tempfile
from pathlib import Path
sys.path.insert(0, '/home/claude/stavki'); import stavki as S
S.HERE = Path(tempfile.mkdtemp()); S.log = lambda *a: None
con = S.db_open()
now = time.time(); st = now - 5 * 3600
for mid in (1, 2, 3):
    con.execute('INSERT INTO matches (match_id, title, league, start_ts) VALUES (?,?,?,?)', (mid, f'M{mid}', 'L', st))
def pinrow(mid, market, lines):
    raw = [[S.outcome_names(market, l), po] for l, po in lines]
    con.execute('INSERT INTO pin VALUES (?,?,?,?)', (st - 60, mid, market, json.dumps(raw)))
pinrow(1, 'c_tt1', [(4.5, [1.9, 1.9]), (5.0, [1.6, 2.3])])
pinrow(1, 'c_total', [(9.5, [1.8, 2.0])])
pinrow(1, 'ch_total', [(4.5, [1.95, 1.85])])
pinrow(2, 'c_tt2', [(3.5, [2.2, 1.66])])
pinrow(3, 'c_total', [(10.5, [2.0, 1.8])])
con.execute('INSERT INTO ext_scores (match_id, done, c1, c2, ft1, ft2) VALUES (1, 1, 6, 4, 1, 0)')
con.execute('INSERT INTO results VALUES (2, 2, 1, ?)', (now,))
for part, a, b in (('ft', 2, 1), ('c', 3, 5)):
    con.execute('INSERT INTO bk_scores (match_id, part, s1, s2, comment, ts) VALUES (?,?,?,?,?,?)', (2, part, a, b, '(1-2)', st + 110 * 60))
con.commit()
r = S.corner_calib(con)
print(json.dumps({k: v for k, v in r.items() if k != 'rows'}, ensure_ascii=False))
for x in r['rows']: print(x)
assert r['matches'] == 3 and r['with_result'] == 2
m1 = [x for x in r['rows'] if x['match_id'] == 1][0]
assert ['c_tt1', 5.0] not in [l[:2] for l in m1['lines']] and any(l[0] == 'ch_total' for l in m1['lines'])
assert r['summary']['c_tt1']['0.5']['вышло'] == 1.0 and r['summary']['c_tt2']
# угловые 1-го тайма — не в окно и не на бумагу
v = {'bookmaker': 'Фонбет', 'market': 'ch_total', 'match_id': 1, 'src': 'сайт', 'ev': 0.08, 'odds': 2.0, 'rel': 0.1, 'p_win': 0.55}
assert S.pick_for_strategies([v]) == []
assert S.bet_kind('ch_total')[0].startswith('УГЛОВЫЕ 1-Й ТАЙМ') and S.split_fam('ch_tt1') == ('ch_', 'tt1')
S.STATE.direct_values = {('direct', 'Фонбет', 1, 'Угловые 1-й тайм: Тотал', 'Меньше (4.5)'): dict(v, line=4.5, market_name='x', outcome='Меньше (4.5)', fair=1.9, updated=now, first_seen=now, pin_ts=now, odds_ts=now, source='сайт')}
with S.STATE.lock:
    S.STATE.matches[1] = {'id': 1, 'start': now + 3600, 'title': 'M1'}
assert not S.STATE.snapshot()['values'] and S.STATE.snapshot(journal=True)['values']
print('ВСЁ ОК')

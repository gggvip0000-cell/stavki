"""-122: способы К (без фаворита), Л (за 5–15 мин до начала), Н (одна ставка на матч) — вживую и задним числом."""
exec(open('/home/claude/bet/test_live24.py', encoding='utf-8').read().split("# через 2 дня без данных")[0])
import json
d = json.load(open('/home/claude/bet/r2114/report.json'))
cols = [r[1] for r in con.execute('PRAGMA table_info(cand)')]
for r in d['cand']:
    con.execute(f"INSERT OR IGNORE INTO cand ({','.join(k for k in r if k in cols)}) VALUES ({','.join('?' for k in r if k in cols)})",
                [r[k] for k in r if k in cols])
con.execute("DELETE FROM paper2 WHERE strategy IN ('К','Н','Л')"); con.commit()
S.backfill_new_strategies(con)
g = dict((r[0], r[1:]) for r in con.execute("SELECT strategy, COUNT(*), COUNT(DISTINCT match_id), MIN(ev) FROM paper2"
                                            " WHERE strategy IN ('К','Н','Л') GROUP BY 1"))
print(g)
assert g['К'][0] > 20 and g['К'][2] >= 0.05 and 'Л' not in g
assert con.execute("SELECT MAX(c) FROM (SELECT COUNT(*) c FROM paper2 WHERE strategy='Н' GROUP BY match_id, src)").fetchone()[0] == 1
# К: шанс у всех ставок < 50%
for odds, fair, ev in con.execute("SELECT odds, fair, ev FROM paper2 WHERE strategy='К'"):
    ch, _ = S.chance_rel(odds, fair); assert ch < 0.5, (odds, fair)
# вживую: pick_for_strategies
now = S.time.time()
def v(mid, fam, out, odds, ev, chance, rel, left):
    return {'match_id': mid, 'market': fam, 'outcome': out, 'line': 2.5, 'src': 'сайт', 'odds': odds, 'ev': ev,
            'chance': chance, 'rel': rel, 'start_ts': now + left, 'bookmaker': 'PARI'}
rows = [v(1, 'total', 'Меньше (3.5)', 1.83, 0.061, 0.58, 0.07, 3600), v(1, 'tt2', 'Меньше (2.5)', 1.42, 0.058, 0.75, 0.09, 3600),
        v(2, 'total', 'Больше (2.5)', 2.6, 0.07, 0.41, 0.05, 600)]
p = S.pick_for_strategies(rows)
pk = {}
for c, x in p: pk.setdefault(c, []).append((x['match_id'], x['market']))
print(pk)
assert sorted(pk['Н']) == [(1, 'tt2'), (2, 'total')]                # по одной на матч, лучшая по надёжности
assert pk['К'] == [(2, 'total')]                                     # только шанс < 50%
assert pk['Л'] == [(2, 'total')]                                     # только за 5–15 мин до начала
assert len(pk['Б']) == 3
print('ВСЁ ОК')

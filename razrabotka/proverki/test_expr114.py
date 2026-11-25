"""-114: бумажные экспрессы из «Меньше» инд. тоталов угловых (4/5/6 ног), расчёт, отчёт."""
import sys, json, time, tempfile
from pathlib import Path
sys.path.insert(0, '/home/claude/stavki'); import stavki as S
S.HERE = Path(tempfile.mkdtemp()); S.log = lambda *a: None
c = S.Collector.__new__(S.Collector); c.con = S.db_open()
now = time.time()
dv = {}
with S.STATE.lock:
    S.STATE.matches = {}
    S.STATE.status['feeds'] = {}
for i in range(8):
    mid = 100 + i
    with S.STATE.lock:
        S.STATE.matches[mid] = {'id': mid, 'start': now + 3600 + i * 60, 'title': f'A{i} — B{i}', 'league': 'L', 'start_str': ''}
    fam = 'c_tt1' if i % 2 else 'c_tt2'
    for bk in ('Фонбет', 'PARI', 'Олимп'):
        dv[('direct', bk, mid, 'x', 'Меньше (4.5)')] = {'bookmaker': bk, 'match_id': mid, 'market': fam, 'line': 4.5,
            'market_name': 'Угловые: Инд. тотал', 'outcome': 'Меньше (4.5)', 'odds': 1.9, 'fair': 1.8,
            'p_win': 0.555, 'p_push': 0, 'ev': 0.03 + i * 0.005, 'source': 'сайт', 'updated': now, 'first_seen': now,
            'pin_ts': now, 'odds_ts': now}
# лишние: «Больше» и целая линия и низкий перевес — не берутся
dv[('direct', 'Фонбет', 100, 'y', 'Больше (4.5)')] = dict(dv[('direct', 'Фонбет', 100, 'x', 'Меньше (4.5)')], outcome='Больше (4.5)', ev=0.2)
dv[('direct', 'Фонбет', 101, 'z', 'Меньше (5)')] = dict(dv[('direct', 'Фонбет', 101, 'x', 'Меньше (4.5)')], outcome='Меньше (5)', line=5.0, ev=0.3)
S.STATE.direct_values = dv
c.expr_step()
ex = c.con.execute('SELECT size, bookmaker, legs, odds, ev_prod, legs_now FROM expr WHERE size>0 ORDER BY size').fetchall()
assert c.con.execute("SELECT legs_now FROM expr WHERE size=0").fetchone()[0] == 8
for e in ex: print(e[0], e[1], round(e[3], 2), e[4], e[5], [l['mid'] for l in json.loads(e[2])])
assert [e[0] for e in ex] == [4, 5, 6] and all(e[1] == 'PARI' for e in ex) and ex[0][5] == 8
l4 = json.loads(ex[0][2]); assert [l['mid'] for l in l4] == [107, 106, 105, 104] and all(l['outcome'].startswith('Меньше') and l['line'] == 4.5 for l in l4)
# через час — те же матчи не повторяются: из оставшихся 4 матчей — ещё одна четвёрка, на 5 и 6 не хватает
c.expr_ts = 0; c.expr_step()
assert [r[0] for r in c.con.execute('SELECT size FROM expr WHERE size>0 ORDER BY id')] == [4, 5, 6, 4]
# расчёт: матчи сыграны, угловые известны (FotMob). Нога матча 107 («Меньше 4.5» хозяев) проигрывает — 7:7
for eid, lg in c.con.execute('SELECT id, legs FROM expr WHERE size>0').fetchall():
    ll = json.loads(lg)
    for l in ll:
        l['start_ts'] = now - 3 * 3600
    c.con.execute('UPDATE expr SET legs=? WHERE id=?', (json.dumps(ll), eid))
for i in range(8):
    mid = 100 + i
    hc, ac = (7, 7) if mid == 107 else (2, 3)
    c.con.execute('INSERT INTO ext_scores (match_id, done, c1, c2, ft1, ft2) VALUES (?,1,?,?,0,0)', (mid, hc, ac))
c.con.commit()
c.expr_set_ts = 0; c.expr_step()
res = {r[0]: r[1:] for r in c.con.execute('SELECT size, status, mult FROM expr WHERE size>0 ORDER BY id DESC')}
print(res)
assert res[4][0] == 'проигрыш' and res[4][1] == 0          # 107 — в каждой (лучший перевес)
assert res[5][0] == 'проигрыш' and res[6][0] == 'проигрыш'
# все выигрышные: убрать проигрыш у 107
c.con.execute('UPDATE ext_scores SET c1=2, c2=3 WHERE match_id=107')
c.con.execute("UPDATE expr SET status='open', mult=NULL WHERE size>0"); c.con.commit()
c.expr_set_ts = 0; c.expr_step()
res = {r[0]: r[1:] for r in c.con.execute('SELECT size, status, mult FROM expr WHERE size>0 ORDER BY id DESC')}
print(res)
assert res[4][0] == 'выигрыш' and abs(res[4][1] - 1.9 ** 4) < 1e-3
import io, zipfile
rep = json.loads(zipfile.ZipFile(io.BytesIO(S.build_report(c.con))).read('report.json'))
print(rep['expr']['summary'])
assert rep['expr']['summary']['4']['roi'] > 10 and rep['expr']['summary']['4']['roi_tax'] < rep['expr']['summary']['4']['roi']
print('ВСЁ ОК')

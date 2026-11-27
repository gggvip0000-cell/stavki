"""-144: матч не состоялся — кнопка в окне → все ставки матча «возврат 0 ₽», нога экспресса с кф 1; FotMob «перенесён» —
пометка в окне и без «счёт 0:0»."""
import sys, json, tempfile, pathlib
sys.path.insert(0, '/home/user/stavki')
import stavki as S
S.HERE = pathlib.Path(tempfile.mkdtemp())
con = S.db_open()
T = [1795700000.0]
S.time.time = lambda: T[0]
C = S.Collector.__new__(S.Collector); C.con = con; C.close_ts = None
st = T[0] - 3 * 3600
ins = ("INSERT INTO paper2 (strategy, src, created, match_id, title, start_ts, bookmaker, fam, outcome, line, odds, ev, fair, status)"
       " VALUES ('П','сайт',?,?,?,?,'PARI',?,?,?,1.9,0.05,1.81,?)")
con.execute(ins, (st - 600, 1, 'Усти-над-Лабем — Кромержиж', st, 'total', 'Меньше (3)', 3.0, 'open'))
con.execute(ins, (st - 600, 1, 'Усти-над-Лабем — Кромержиж', st, 'c_tt1', 'Меньше (4.5)', 4.5, 'open'))
con.execute(ins, (st - 600, 2, 'Дордрехт — Витесс', st - 3 * 86400, '1x2', 'П1', None, 'нет данных'))
con.execute(ins, (st - 600, 3, 'Другой — Матч', st, 'total', 'Меньше (2.5)', 2.5, 'open'))
legs = [{'mid': 1, 'fam': 'total', 'outcome': 'Меньше (3.5)', 'line': 3.5, 'odds': 2.0, 'fair': 1.9, 'ev': 0.06, 'start_ts': st, 'title': 'Усти — Кромержиж'},
        {'mid': 4, 'fam': 'total', 'outcome': 'Больше (1.5)', 'line': 1.5, 'odds': 1.8, 'fair': 1.7, 'ev': 0.06, 'start_ts': st, 'title': 'К4 — С4'}]
con.execute("INSERT INTO expr (created, size, bookmaker, legs, odds, ev_prod, status, kind) VALUES (?,2,'Олимп',?,3.6,0.12,'open','ЭБ')",
            (st - 600, json.dumps(legs, ensure_ascii=False)))
con.execute("INSERT INTO ext_scores (match_id, src, ext_id, ft1, ft2, done, tries, last_try) VALUES (4,'fotmob','z',2,1,1,1,0)")
con.commit()
# владелец нажал «Матч не состоялся» у матча 1 и 2 (как делает окно)
for mid in (1, 2):
    con.execute('INSERT OR REPLACE INTO manual_scores (match_id, part, h, a, ts) VALUES (?,?,?,?,?)', (mid, 'x', 0, 0, T[0]))
con.commit(); C.settle_paper()
rows = con.execute('SELECT match_id, fam, status, profit, void FROM paper2 ORDER BY id').fetchall(); print(rows)
assert rows[0][2:] == ('возврат', 0, 1) and rows[1][2:] == ('возврат', 0, 1) and rows[2][2:] == ('возврат', 0, 1)
assert rows[3][2] == 'open'
C.expr_set_ts = 0; C.expr_ts = T[0]; C.expr_step()
s_, mult, lg = con.execute('SELECT status, mult, legs FROM expr').fetchone(); lg = json.loads(lg); print(s_, mult, lg[0].get('void'))
assert s_ == 'выигрыш' and abs(mult - 1.8) < 1e-9 and lg[0]['void']       # нога 1 — кф 1, купон = 1.8
r0 = S.leg_row(1, 0, lg[0]); assert r0['status'] == 'возврат' and r0['void']
ps = S.paper_stats(con, 100)['views']['П']
b = [x for x in ps['bets'] if x['mid'] == 1][0]; assert b['void'] and b['status'] == 'возврат' and b['profit_rub'] == 0
print('итог П:', {k: ps['simple_total'][k] for k in ('n', 'w', 'l', 'push', 'done')})
# FotMob: перенесён — пометка, без 0:0
class Ext:
    def page(self, br, k, u): return object()
    def get(self, k, u):
        return {'header': {'teams': [{'name': 'Dordrecht', 'score': 0}, {'name': 'Vitesse', 'score': 0}],
                           'status': {'started': False, 'finished': False, 'cancelled': False,
                                      'reason': {'short': 'PP', 'shortKey': 'postponed_short', 'long': 'Postponed', 'longKey': 'postponed'}}}}
    def pair(self, *a): return True
C.ext = Ext(); C.browser = object()
con.execute("INSERT INTO matches (match_id, title, league, start_ts, url, home_en, away_en) VALUES (5,'Дордрехт — Витесс','Нидерланды',?, '', 'dordrecht', 'vitesse')", (T[0] - 1800,))
con.execute(ins, (st - 600, 5, 'Дордрехт — Витесс', T[0] - 1800, '1x2', 'П1', None, 'open'))
con.execute("INSERT INTO sofa_link (match_id, url, tries, last_try) VALUES (5,'https://www.fotmob.com/match/123',1,0)")
con.commit(); C.fml_last = 0; C.fotmob_live_step()
print('ext_live:', con.execute('SELECT ft1, ft2, note FROM ext_live WHERE match_id=5').fetchone(), C.fml_stat.get('not_started'))
assert con.execute('SELECT ft1, ft2, note FROM ext_live WHERE match_id=5').fetchone() == (None, None, 'перенесён')
b5 = [x for x in S.paper_stats(con, 100)['views']['П']['bets'] if x['mid'] == 5][0]
print('в окне:', b5['live']); assert b5['live'] == {'note': 'перенесён'}
# обычный лайв FotMob у идущего матча — как раньше (счёт, угловые, «окончен»)
con.execute("INSERT OR REPLACE INTO ext_live (match_id, ft1, ft2, c1, c2, ts, fin, note) VALUES (3,1,0,2,3,?,1,'')", (T[0] - 10,))
con.commit()
b3 = [x for x in S.paper_stats(con, 100)['views']['П']['bets'] if x['mid'] == 3][0]
print('лайв матча 3:', b3['live']); assert b3['live'] == {'fin': 1, 'c': [2, 3], 'ft': [1, 0]}, b3['live']
print('ВСЁ ОК')

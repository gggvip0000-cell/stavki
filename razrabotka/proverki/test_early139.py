"""-139: у досрочно закрытой ставки и ноги экспресса — минута и счёт закрытия; после итога они остаются, счёт — итоговый."""
import sys, json, tempfile, pathlib
sys.path.insert(0, '/home/user/stavki'); sys.path.insert(0, '/home/claude/stavki')
import stavki as S
S.HERE = pathlib.Path(tempfile.mkdtemp())
con = S.db_open()
T = [1795700000.0]
S.time.time = lambda: T[0]
C = S.Collector.__new__(S.Collector); C.con = con; C.close_ts = None
st = T[0] - 3600
# таймер PARI: 2-й тайм, 57:20 — tsec 3440 снят 20 с назад (часы идут); перерыв был — в comment счёт тайма
con.execute("INSERT INTO bk_scores (match_id, part, s1, s2, comment, ts, tsec, tdir, tupd) VALUES (1,'ft',2,1,'(1-0)',?,?,?,?)",
            (T[0] - 5, 3420, 1, (T[0] - 20) * 1000))
assert C.clock_at(1, st, T[0]) == '2-й тайм · 57-я минута', C.clock_at(1, st, T[0])
assert C.clock_at(2, T[0] - 30 * 60, T[0]) == '1-й тайм · ≈30-я минута'          # нет таймера — примерно
assert C.clock_at(2, T[0] - 80 * 60, T[0]) == '2-й тайм · ≈63-я минута'
# одиночная: М 2.5 при 2:1 — закрыта досрочно на 57-й минуте
cols = [c[1] for c in con.execute('PRAGMA table_info(paper2)')]
con.execute("INSERT INTO paper2 (strategy, src, created, match_id, title, start_ts, bookmaker, fam, outcome, line, odds, ev, status)"
            " VALUES ('У','сайт',?,1,'Ювентус — Омония',?,'Олимп','total','Меньше (2.5)',2.5,3.04,0.115,'open')", (st - 600, st))
con.commit(); C.settle_early()
r = con.execute('SELECT status, early, res_h, res_a, early_at, early_h, early_a FROM paper2').fetchone(); print(r)
assert r == ('проигрыш', 1, 2, 1, '2-й тайм · 57-я минута', 2, 1)
b = [x for x in S.paper_stats(con, 100)['views']['У']['bets']][0]
assert b['early'] and b['early_at'] == '2-й тайм · 57-я минута' and b['early_sc'] == [2, 1]
# итог 3:1 — счёт итоговый, минута и счёт закрытия остаются
con.execute("INSERT INTO ext_scores (match_id, src, ext_id, ft1, ft2, done, tries, last_try) VALUES (1,'fotmob','z',3,1,1,1,0)")
con.commit(); C.settle_early()
r = con.execute('SELECT status, early, res_h, res_a, early_at, early_h, early_a FROM paper2').fetchone(); print(r)
assert r == ('проигрыш', 0, 3, 1, '2-й тайм · 57-я минута', 2, 1)
b = S.paper_stats(con, 100)['views']['У']['bets'][0]
assert not b['early'] and b['res'] == [3, 1] and b['early_sc'] == [2, 1]
# нога экспресса: минута и счёт закрытия пишутся один раз, после итога остаются
legs = [{'mid': 1, 'fam': 'total', 'outcome': 'Меньше (2.5)', 'line': 2.5, 'odds': 3.04, 'fair': 2.7, 'ev': 0.115,
         'start_ts': st, 'title': 'Ювентус — Омония'},
        {'mid': 5, 'fam': 'total', 'outcome': 'Меньше (3.5)', 'line': 3.5, 'odds': 1.83, 'fair': 1.7, 'ev': 0.05,
         'start_ts': st, 'title': 'Лион — Лиллестрём'}]
con.execute("DELETE FROM ext_scores")
con.execute("INSERT INTO expr (created, size, bookmaker, legs, odds, ev_prod, status, kind) VALUES (?,2,'Олимп',?,5.5,0.17,'open','ЭБ')",
            (st - 600, json.dumps(legs, ensure_ascii=False)))
con.commit(); C.expr_set_ts = 0; C.expr_ts = T[0]; C.expr_step()
st_, lg = con.execute('SELECT status, legs FROM expr').fetchone(); lg = json.loads(lg); print(st_, lg[0])
assert st_ == 'проигрыш' and lg[0]['early_at'] == '2-й тайм · 57-я минута' and lg[0]['early_sc'] == [2, 1]
row = S.leg_row(1, 0, lg[0]); assert row['early'] and row['early_at'] and row['early_sc'] == [2, 1]
T[0] += 3600
con.execute("INSERT INTO ext_scores (match_id, src, ext_id, ft1, ft2, done, tries, last_try) VALUES (1,'fotmob','z',3,1,1,1,0)")
con.commit(); C.expr_set_ts = 0; C.expr_step()
lg = json.loads(con.execute('SELECT legs FROM expr').fetchone()[0]); print(lg[0])
assert lg[0]['res'] == [3, 1] and not lg[0].get('early') and lg[0]['early_at'] == '2-й тайм · 57-я минута' and lg[0]['early_sc'] == [2, 1]
print('ВСЁ ОК')

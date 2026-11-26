"""-138: экспресс считается досрочно — нога, исход которой уже не изменится по счёту лайва; итог поправляет досрочный расчёт."""
import sys, json, tempfile, pathlib
sys.path.insert(0, '/home/user/stavki'); sys.path.insert(0, '/home/claude/stavki')
import stavki as S
S.HERE = pathlib.Path(tempfile.mkdtemp())
con = S.db_open()
T = [1795700000.0]
S.time.time = lambda: T[0]
C = S.Collector.__new__(S.Collector)
C.con = con
C.close_ts = None
def leg(mid, fam, oc, line, odds=1.9, start=-3000):
    return {'mid': mid, 'fam': fam, 'outcome': oc, 'line': line, 'odds': odds, 'fair': 1.8, 'ev': 0.06,
            'start_ts': T[0] + start, 'title': f'Матч {mid}'}
def coupon(legs, kind='ЭА'):
    con.execute("INSERT INTO expr (created, size, bookmaker, legs, odds, ev_prod, status, kind) VALUES (?,?,?,?,?,?,'open',?)",
                (T[0] - 7200, len(legs), 'Олимп', json.dumps(legs, ensure_ascii=False), 7.0, 0.19, kind))
    return con.execute('SELECT max(id) FROM expr').fetchone()[0]
def live(mid, part, h, a, age=10):
    con.execute('INSERT OR REPLACE INTO bk_scores (match_id, part, s1, s2, comment, ts) VALUES (?,?,?,?,?,?)', (mid, part, h, a, None, T[0] - age))
def run():
    C.expr_set_ts = 0; C.expr_ts = T[0]; C.expr_step()
def get(eid):
    st, legs = con.execute('SELECT status, legs FROM expr WHERE id=?', (eid,)).fetchone()
    return st, json.loads(legs)
# 1) Ювентус — Омония М 2.5 при 2:1 — уже проиграна → купон проигран сразу, остальные ноги ещё идут
A = coupon([leg(1, 'total', 'Меньше (2.5)', 2.5), leg(2, '1x2', 'П2', None), leg(3, 'total', 'Меньше (3.5)', 3.5)])
live(1, 'ft', 2, 1); live(2, 'ft', 1, 0); live(3, 'ft', 0, 0); con.commit()
run(); st, legs = get(A); print(1, st, [l.get('res') for l in legs], [l.get('early') for l in legs])
assert st == 'проигрыш' and legs[0]['res'] == [2, 1] and legs[0].get('early') and 'res' not in legs[1] and 'res' not in legs[2]
# 2) ещё не решено (М 3.5 при 1:1) — купон открыт; старый счёт лайва (>3 мин) не берётся
B = coupon([leg(4, 'total', 'Меньше (3.5)', 3.5), leg(5, 'c_tt2', 'Меньше (4.5)', 4.5)])
live(4, 'ft', 1, 1); live(5, 'c', 1, 9, age=600); con.commit()
run(); assert get(B)[0] == 'open', get(B)
# 3) угловые: М 4.5 гостей при 2:5 по свежему лайву — проиграна
live(5, 'c', 2, 5); con.commit()
run(); st, legs = get(B); print(3, st, [l.get('res') for l in legs]); assert st == 'проигрыш' and legs[1]['res'] == [2, 5]
# 4) все ноги выиграны досрочно (Б 1.5 при 2:0) — купон выигран
D = coupon([leg(6, 'total', 'Больше (1.5)', 1.5), leg(7, 'total', 'Больше (0.5)', 0.5)])
live(6, 'ft', 2, 0); live(7, 'ft', 0, 1); con.commit()
run(); st, legs = get(D); print(4, st); assert st == 'выигрыш' and all(l.get('early') for l in legs)
# 5) итог пришёл и совпал — флаг досрочного снят, купон тот же
con.execute("INSERT INTO ext_scores (match_id, src, ext_id, ft1, ft2, done, tries, last_try) VALUES (1, 'fotmob', 'z', 3, 1, 1, 1, 0)")
con.commit(); run(); st, legs = get(A); print(5, st, legs[0]); assert st == 'проигрыш' and legs[0]['res'] == [3, 1] and not legs[0].get('early')
# 6) итог спорит с лайвом (лайв ошибся: на деле 1:0 по матчу 6, Б 1.5 не сыграла) — купон пересчитан
con.execute("INSERT INTO ext_scores (match_id, src, ext_id, ft1, ft2, done, tries, last_try) VALUES (6, 'fotmob', 'z', 1, 0, 1, 1, 0)")
con.commit(); run(); print(6, get(D)[0]); run(); st, legs = get(D); print(6, st, [l.get('res') for l in legs]); assert st == 'проигрыш'
# 7) 1-й тайм досрочно не считается (только в перерыв по итогу тайма)
E = coupon([leg(8, 'h1_total', 'Больше (0.5)', 0.5)])
live(8, 'ft', 1, 0); con.commit(); run(); assert get(E)[0] == 'open'
# 8) нога в окне — с пометкой «досрочно»
row = S.leg_row(B, 1, get(B)[1][1]); assert row['early'] is True and row['status'] == 'проигрыш'
print('ВСЁ ОК')

"""-130: способ «У» (одиночные с налоговым порогом), экспрессы Олимпа ЭА/ЭБ, проверка цены через 60/90/120 с, окно."""
import sys, json, tempfile, pathlib
sys.path.insert(0, '/home/claude/stavki')
import stavki as S
S.HERE = pathlib.Path(tempfile.mkdtemp())
con = S.db_open()
T = [1795700000.0]
S.time.time = lambda: T[0]
cond = {c: f for c, _d, f, _k in S.STRATEGIES}['У']
base = dict(bookmaker='Олимп', odds=2.2, odds_age=5, outcome='Меньше (2.5)', line=2.5, market='total', market_name='Тотал')
# порог зависит от шанса: при 0.5 — 15%·0.5+4% = 11.5%; при 0.85 — 6.25%; не меньше 5%
assert not cond(dict(base, ev=0.11, chance=0.5)) and cond(dict(base, ev=0.12, chance=0.5))
assert not cond(dict(base, ev=0.06, chance=0.85)) and cond(dict(base, ev=0.065, chance=0.85))
assert not cond(dict(base, ev=0.2, chance=0.5, odds_age=16))          # цена старше 15 с
assert not cond(dict(base, ev=0.2, chance=0.5, bookmaker='PARI'))
assert not cond(dict(base, ev=0.2, chance=0.5, line=2.0, outcome='Меньше (2)'))   # линия с возвратом
assert cond(dict(base, ev=0.2, chance=0.5, line=None, market='1x2', outcome='П1', market_name='1Х2'))
# снимок цен Олимпа
def val(mid, ev, odds=2.1, fam='total', oc='Меньше (2.5)', line=2.5, age=3, start=3600, bk='Олимп'):
    return {'match_id': mid, 'bookmaker': bk, 'source': 'сайт', 'market': fam, 'market_name': 'Тотал', 'outcome': oc,
            'line': line, 'odds': odds, 'fair': odds / (1 + ev), 'ev': ev, 'start_ts': T[0] + start, 'match': f'Матч {mid}',
            'odds_ts': T[0] - age, 'bk_url': f'https://olimp.bet/m{mid}'}
VALS = []
S.STATE.snapshot = lambda journal=False: {'values': list(VALS)}
C = S.Collector.__new__(S.Collector)
C.con = con
class F:
    name = 'Олимп'
    last_ok = property(lambda self: T[0])
C.feeds = [F()]
# Олимп ещё ни разу не ответил (last_ok None) — проверка цены не падает
class F0:
    name = 'Олимп'
    last_ok = None
VALS[:] = [val(1, 0.09), val(1, 0.06, oc='Больше (2.5)'), val(2, 0.085), val(3, 0.06), val(4, 0.055),
           val(5, 0.20, age=30),                     # старая цена — не нога
           val(6, 0.07, line=2.0, oc='Меньше (2)'),  # возврат — не нога
           val(7, 0.07, start=300),                  # до матча меньше 10 мин
           val(8, 0.07, bk='PARI'),
           val(9, 0.07, fam='ch_total')]             # угловые 1-го тайма не рассчитываются
C.olimp_expr_step()
ex = con.execute('SELECT kind, size, legs, odds FROM expr ORDER BY id').fetchall()
got = {(k, n): sorted(l['mid'] for l in json.loads(lg)) for k, n, lg, o in ex}
print(got)
assert got == {('ЭА', 3): [1, 2, 3], ('ЭБ', 2): [1, 2]}, got         # 4-я нога ЭА одна — купона нет; в ЭБ только ≥8%
assert abs(ex[0][3] - 2.1 ** 3) < 0.01
assert con.execute('SELECT COUNT(*) FROM leg_check').fetchone()[0] == 5
# через 20 с те же матчи не повторяются, новый матч 10 (≥8%) + 4 (5.5%) + 11 → ЭА [4,10,11], ЭБ — одна нога (10) → нет
T[0] += 21
VALS[:] = [val(m, e) for m, e in ((1, 0.09), (2, 0.085), (3, 0.06), (4, 0.055), (10, 0.09), (11, 0.05))]
C.olimp_expr_step()
ex = con.execute('SELECT kind, legs FROM expr ORDER BY id').fetchall()
assert len(ex) == 3 and sorted(l['mid'] for l in json.loads(ex[2][1])) == [4, 10, 11], ex
# проверка цены: t0 купонов 1/2 = T-21. Через 60 с у матча 1 цена хуже (2.0), у 2 та же, у 3 исчезла
T[0] += 45; VALS[:] = [val(1, 0.04, odds=2.0, age=1), val(2, 0.085, age=1), val(4, 0.055, age=1), val(10, 0.09, age=1), val(11, 0.05, age=1)]
C.lchk_ts = 0; C.oexpr_ts = T[0]; C.olimp_expr_step()
r = {(k, m): (o60, o90) for k, m, o60, o90 in con.execute('SELECT kind, match_id, o60, o90 FROM leg_check WHERE ref<=2')}
print(r)
assert r[('ЭА', 1)][0] == 2.0 and r[('ЭА', 2)][0] == 2.1 and r[('ЭА', 3)][0] is None   # исчезнувшую ждём ещё 30 с
T[0] += 31; C.lchk_ts = 0; C.oexpr_ts = T[0]; C.olimp_expr_step()
r = {(k, m): (o60, o90) for k, m, o60, o90 in con.execute('SELECT kind, match_id, o60, o90 FROM leg_check WHERE ref<=2')}
assert r[('ЭА', 3)] == (0, None) and r[('ЭА', 1)][1] == 2.0, r          # исхода нет — 0; через 90 с цена 2.0
# цена не обновлялась (odds_ts старый) — через 120 с после срока «-1»
T[0] += 200; VALS[:] = [val(2, 0.085, age=500)]; C.lchk_ts = 0; C.oexpr_ts = T[0]; C.olimp_expr_step()
assert con.execute("SELECT o120 FROM leg_check WHERE kind='ЭБ' AND match_id=2").fetchone()[0] == -1
assert con.execute("SELECT o90, o120 FROM leg_check WHERE kind='ЭА' AND match_id=3 AND ref=1").fetchone() == (0, 0)
C.feeds = [F0()]; T[0] += 1; C.lchk_ts = 0; C.oexpr_ts = T[0]; C.olimp_expr_step(); C.feeds = [F()]
hs = S.hold_stats(con, 'ЭА')
print('удержание ЭА', hs)
assert hs['o90']['n'] >= 3 and hs['o90']['ok'] < hs['o90']['n']
# расчёт купона: все ноги матча сыграны, ЭБ [1,2]: обе выиграли → выигрыш, CLV у ног
C.score_for = lambda fam, mid, st: (1, 0)
C.closing_fair = lambda *a, **k: (2.0, 0.05)
T[0] += 4 * 3600
C.expr_ts = T[0]; C.expr_set_ts = 0
C.expr_step()
st = dict(con.execute('SELECT kind || id, status FROM expr').fetchall())
print(st)
assert all(v == 'выигрыш' for v in st.values())
v = S.expr_view(con, 'ЭБ', 100)
print({k: v[k] for k in ('n', 'w', 'l', 'profit_rub', 'profit_tax_rub', 'hold', 'clv')})
assert v['n'] == 1 and v['w'] == 1 and v['profit_rub'] == round((2.1 * 2.1 - 1) * 100)
assert v['profit_tax_rub'] == round((2.1 * 2.1 - 1) * 100 * 0.87) and v['clv'] == {'mean': 5.0, 'n': 2}
assert v['hold']['n'] == 1 and v['coupons'][0]['held'] is False and v['coupons'][0]['legs'][0]['kind'][0].startswith('МАТЧ')
ps = S.paper_stats(con, 100)
assert set(ps['expr_views']) == {'ЭА', 'ЭБ'} and 'У' in ps['views']
json.dump(ps, open('/tmp/claude-0/ps130.json', 'w'), ensure_ascii=False)
# запись способа «У» через record_paper + строка проверки цены
S.MY_BOOKMAKERS[:] = ['Олимп', 'PARI']
S.TG = None
def sv(mid, ev, chance, age=3):
    v = val(mid, ev, age=age, start=7200)
    v.update(chance=chance, rel=0.1, league='Лига', pin_age=5)
    return v
VALS[:] = [sv(20, 0.13, 0.5), sv(21, 0.10, 0.5), sv(22, 0.13, 0.5, age=20)]
C.record_paper()
u = con.execute("SELECT match_id FROM paper2 WHERE strategy='У'").fetchall()
lc = con.execute("SELECT ref, match_id, odds0 FROM leg_check WHERE kind='У'").fetchall()
print('У:', u, lc)
assert u == [(20,)] and len(lc) == 1 and lc[0][1] == 20
ps = S.paper_stats(con, 100)
assert ps['views']['У']['simple_total']['n'] == 1 and 'hold' in ps['views']['У']
print('ВСЁ ОК')
S.COLLECTOR = C; C.feeds = []
rep = S.build_report(con)
import zipfile, io
if isinstance(rep, bytes):
    z = zipfile.ZipFile(io.BytesIO(rep)); rep = json.loads(z.read(z.namelist()[0]))
assert 'ЭА' in rep['leg_check']['summary'] and 'ЭБ3' in rep['expr']['summary'] or 'ЭБ2' in rep['expr']['summary'], rep['expr'].get('summary')
print('отчёт:', list(rep['expr']['summary']), rep['leg_check']['summary']['ЭА']['o90'])
print('ВСЁ ОК 2')

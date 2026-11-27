"""-147: скрытые испытательные экспрессы PARI (ЭП) и Винлайна (ЭВ) — 2 ноги от 8%, поток конторы жив ≤60 с; Олимп как был."""
import sys, json, tempfile, pathlib
sys.path.insert(0, '/home/user/stavki')
import stavki as S
S.HERE = pathlib.Path(tempfile.mkdtemp())
con = S.db_open()
T = [1795700000.0]
S.time.time = lambda: T[0]
def val(mid, ev, bk, odds=2.1, line=2.5, oc='Меньше (2.5)', age=3, start=3600, fam='total'):
    return {'match_id': mid, 'bookmaker': bk, 'source': 'сайт', 'market': fam, 'market_name': 'Тотал', 'outcome': oc,
            'line': line, 'odds': odds, 'fair': odds / (1 + ev), 'ev': ev, 'start_ts': T[0] + start, 'match': f'Матч {mid}',
            'odds_ts': T[0] - age, 'bk_url': ''}
VALS = []
S.STATE.snapshot = lambda journal=False: {'values': list(VALS)}
S.STATE.status['feeds'] = {'PARI': {'last_ok': T[0] - 5}, 'Винлайн': {'last_ok': T[0] - 200}}   # Винлайн молчит
C = S.Collector.__new__(S.Collector); C.con = con
class F:
    name = 'Олимп'; last_ok = None
C.feeds = [F()]
VALS[:] = [val(1, 0.09, 'PARI', age=5000),          # у PARI возраст цены — время изменения, не мешает
           val(2, 0.085, 'PARI'), val(3, 0.07, 'PARI'),        # 7% — не нога ЭП
           val(4, 0.20, 'PARI', line=2.0, oc='Меньше (2)'),    # возврат — не нога
           val(5, 0.10, 'Винлайн'), val(6, 0.12, 'Винлайн'),   # поток Винлайна молчит — купона нет
           val(7, 0.09, 'Олимп'), val(8, 0.09, 'Олимп')]
C.olimp_expr_step()
ex = con.execute('SELECT kind, bookmaker, legs FROM expr ORDER BY id').fetchall()
got = {(k, b): sorted(l['mid'] for l in json.loads(lg)) for k, b, lg in ex}
print(got)
assert got == {('ЭБ', 'Олимп'): [7, 8], ('ЭП', 'PARI'): [1, 2]}, got
assert {k for (k,) in con.execute('SELECT DISTINCT kind FROM leg_check')} == {'ЭБ'}   # цены через 60/90/120 с — только Олимп
# Винлайн ожил — купон ЭВ; матчи ЭП не повторяются
T[0] += 21; S.STATE.status['feeds']['Винлайн']['last_ok'] = T[0] - 2
VALS[:] = [val(1, 0.09, 'PARI'), val(2, 0.085, 'PARI'), val(5, 0.10, 'Винлайн'), val(6, 0.12, 'Винлайн')]
C.olimp_expr_step()
got = {(k, b): sorted(l['mid'] for l in json.loads(lg)) for k, b, lg in con.execute('SELECT kind, bookmaker, legs FROM expr')}
print(got)
assert got[('ЭВ', 'Винлайн')] == [5, 6] and len([1 for k in got if k[0] == 'ЭП']) == 1
# графики: ЭП/ЭВ — скрытые, с новыми названиями; окно их не показывает
cd = {x['code']: x for x in S.charts_data(con, 100)}
assert cd['ЭП']['title'] == 'Экспресс 2 ноги · PARI · перевес от 8%' and not cd['ЭП']['visible'] and cd['ЭП']['open'] == 1
assert cd['ЭВ']['title'] == 'Экспресс 2 ноги · Винлайн · перевес от 8%' and not cd['ЭВ']['visible']
ps = S.paper_stats(con, 100)
assert set(ps['expr_views']) == {'ЭА', 'ЭБ'}, set(ps['expr_views'])
print('ВСЁ ОК')

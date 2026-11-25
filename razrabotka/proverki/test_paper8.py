"""Проверка версии -8: пересчёт старой бумаги, одна ставка на событие по способам, журнал CLV, статистика."""
import os, sqlite3, sys, json
DB = '/tmp/stavki.sqlite3'
if os.path.exists(DB):
    os.remove(DB)
# старая бумага, как у владельца: Алавес — 4 линии тотала × 2 конторы + П1 и контрольная строка
con = sqlite3.connect(DB)
con.execute('CREATE TABLE paper (id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL, match_id INT, title TEXT, league TEXT,'
            ' start_ts REAL, bookmaker TEXT, source TEXT, grp TEXT, market TEXT, market_name TEXT, outcome TEXT, line REAL,'
            ' odds REAL, fair REAL, ev REAL, stake REAL, status TEXT DEFAULT "open", profit REAL, closing_fair REAL,'
            ' clv REAL, settled REAL, UNIQUE (match_id, bookmaker, market_name, outcome, grp))')
START = 1795250000
rows = []
for bk in ('Фонбет', 'PARI'):
    for ln, odds, fair in [(1.5, 3.6, 3.0), (2, 2.45, 2.136), (2.5, 1.75, 1.62), (3, 1.40, 1.30)]:
        rows.append((1, 900, 'Алавес — Депортиво', 'Испания', START, bk, 'сайт', 'основная', 'total', 'Тотал',
                     f'Меньше ({ln:g})', ln, odds, fair, odds / fair - 1, 1.0))
rows.append((1, 900, 'Алавес — Депортиво', 'Испания', START, 'Винлайн', 'odds.ru', 'основная', '1x2', '1Х2', 'П1', None,
             2.3, 2.1, 2.3 / 2.1 - 1, 1.0))
rows.append((1, 901, 'Кайсериспор — X', 'Турция', START, 'Фонбет', 'сайт', 'контрольная', '1x2', '1Х2', 'П1', None,
             1.62, 1.58, 1.62 / 1.58 - 1, 1.0))
con.executemany('INSERT INTO paper (created, match_id, title, league, start_ts, bookmaker, source, grp, market,'
                ' market_name, outcome, line, odds, fair, ev, stake) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', rows)
con.commit(); con.close()

sys.argv = ['x']
exec(open('/home/claude/bet/test_direct.py', encoding='utf-8').read().split('# sims')[0])
con = c.con
names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
assert 'paper_old' in names and 'paper' not in names, names
mig = con.execute('SELECT match_id, strategy, src, bookmaker, market_name, outcome, odds FROM paper2 ORDER BY match_id, event, src, strategy').fetchall()
for r in mig: print('пересчёт:', r)
# Алавес, тотал, сайт: Б — по надёжности, А — по перевесу (оба с перевесом ≥5%), В — шанс ≥55% и перевес ≥3%
al = {(r[1], r[2]): r for r in mig if r[0] == 900}
assert al[('А', 'сайт')][5] == 'Меньше (1.5)', al      # наибольший перевес 20%
assert al[('Б', 'сайт')][5] in ('Меньше (2)', 'Меньше (1.5)', 'Меньше (2.5)', 'Меньше (3)')
assert al[('В', 'сайт')][5] in ('Меньше (2.5)', 'Меньше (3)')
assert sum(1 for r in mig if r[0] == 900 and r[2] == 'сайт') >= 3       # 8 строк → по одной на способ
assert not [r for r in mig if r[0] == 901]   # контрольная 2.5% — ниже всех порогов, не попадает
print('Б выбрал:', al[('Б', 'сайт')][5], '| В выбрал:', al[('В', 'сайт')][5])
# повторный запуск — ничего не ломает
con2 = S.db_open()
assert con2.execute('SELECT COUNT(*) FROM paper2').fetchone()[0] == len(mig)
print('повторный запуск ок')

# живые ставки из прямой линии Фонбета (в данных теста)
# в записанных данных нет ставок моих контор с перевесом ≥3% — для проверки механики пороги снижаю до 1%
S.STRATEGIES = [(code, d, (lambda v: v['ev'] >= 0.01 and v['odds'] <= 4.0), k) for code, d, _c, k in S.STRATEGIES]
S.CAND_MIN_EV = 0.01
n0 = con.execute('SELECT COUNT(*) FROM paper2').fetchone()[0]
c.record_paper(); c.record_paper()
live = con.execute('SELECT match_id, event, strategy, src, bookmaker, outcome, odds, round(ev,3), round(rel,3), pin_age FROM paper2 WHERE id>?', (n0,)).fetchall()
for r in live: print('живая:', r)
dup = con.execute('SELECT match_id, event, strategy, src, COUNT(*) FROM paper2 GROUP BY 1,2,3,4 HAVING COUNT(*)>1').fetchall()
assert not dup, dup
nc = con.execute('SELECT COUNT(*) FROM cand').fetchone()[0]; print('кандидатов в журнале CLV:', nc)
assert live and nc >= len({(r[0], r[4], r[5]) for r in live})
assert all(r[9] is not None for r in live if r[3] == 'сайт'), 'нет возраста Pinnacle'

# расчёт: результат матча + время после начала
for mid in {r[0] for r in live} | {900, 901}:
    con.execute('INSERT OR REPLACE INTO results VALUES (?,?,?,?)', (mid, 1, 0, 0))
con.commit()
clock[0] += 3 * 86400
c.settle_paper()
print(con.execute('SELECT strategy, src, outcome, odds, status, round(profit,2), round(clv,3) FROM paper2 WHERE match_id=900').fetchall())
st = con.execute('SELECT status FROM paper2 WHERE match_id=900 AND outcome="Меньше (1.5)"').fetchone()[0]
assert st == 'выигрыш', st                      # 1:0 — меньше 1.5 сыграло
print('журнал CLV рассчитан:', con.execute('SELECT COUNT(*), COUNT(clv), ROUND(AVG(clv),4) FROM cand WHERE done=1').fetchone())
S.MY_BOOKMAKERS = ['Фонбет', 'Винлайн', 'PARI']
ps = S.paper_stats(con, 100)
for g in ps['strategies']:
    if g['n']: print('способ', g['code'], g['src'], {k: g[k] for k in ('n', 'done', 'w', 'l', 'winpct', 'profit_rub', 'roi', 'clv')})
print('журнал:', ps['cand'])
print('последние:', ps['last'][:3])
print('ВСЁ ОК')

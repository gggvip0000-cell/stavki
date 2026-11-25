"""-108: цена Олимпа в журнал — только не старше 2 мин; у всех строк журнала пишется возраст цены (odds_age)."""
import os, sys, time
DB = '/tmp/stavki.sqlite3'
if os.path.exists(DB):
    os.remove(DB)
sys.argv = ['x']
exec(open('/home/claude/bet/test_direct.py', encoding='utf-8').read().split('# sims')[0])
con = c.con
now = time.time()
mid = next(iter(S.STATE.matches))
st = now + 3600
with S.STATE.lock:
    S.STATE.matches[mid]['start'] = st
base = {'match_id': mid, 'market': 'total', 'line': 2.5, 'market_name': 'Тотал', 'p_win': 0.55, 'p_push': 0,
        'pin_odds': 1.85, 'pin_ts': now, 'source': 'сайт', 'updated': now, 'first_seen': now, 'fair': 1.8, 'ev': 0.06, 'odds': 1.9}
S.STATE.direct_values = {
    ('direct', 'Олимп', mid, 'Тотал', 'Больше (2.5)'): dict(base, bookmaker='Олимп', outcome='Больше (2.5)', odds_ts=now - 300),
    ('direct', 'Олимп', mid, 'Тотал', 'Меньше (2.5)'): dict(base, bookmaker='Олимп', outcome='Меньше (2.5)', odds_ts=now - 30),
    ('direct', 'PARI', mid, 'Тотал', 'Больше (2.5)'): dict(base, bookmaker='PARI', outcome='Больше (2.5)', odds_ts=now - 400),
}
S.MY_BOOKMAKERS = ['Фонбет', 'PARI', 'Винлайн', 'Олимп']
c.record_paper()
rows = con.execute("SELECT bookmaker, outcome, round(odds_age) FROM cand WHERE match_id=? ORDER BY 1,2", (mid,)).fetchall()
print(rows)
ol = [r for r in rows if r[0] == 'Олимп']
assert [r[1] for r in ol] == ['Меньше (2.5)'], ol          # 5 мин — не пишется, 30 с — пишется
assert 25 <= ol[0][2] <= 40
pa = [r for r in rows if r[0] == 'PARI']
assert pa and pa[0][2] >= 395                               # у остальных контор — пишется как есть, с возрастом
assert not con.execute("SELECT COUNT(*) FROM paper2 WHERE bookmaker='Олимп' AND outcome='Больше (2.5)'").fetchone()[0]  # старая цена — и не на бумагу
print('ВСЁ ОК')

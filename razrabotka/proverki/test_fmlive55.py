"""Проверка версии -55: счёт и угловые идущего матча с FotMob, если у конторы в лайве угловых нет."""
import sys
exec(open('/home/claude/bet/test_ext25.py', encoding='utf-8').read().split("x = S.ExtStats()")[0])
c.browser = Browser()
S.VIEW_CODES, S.MAIN_CODE = (('Б', 'x'),), 'Б'   # -123: проверка по ставкам способа Б этого теста
MID = 888200
START = 1795275000
con.execute('INSERT OR REPLACE INTO matches (match_id, title, url, home_en, away_en) VALUES (?,?,?,?,?)',
            (MID, 'Чили U17 — Алжир U17', 'https://odds.ru/x/', 'chile-u17', 'algeria-u17'))
con.execute("INSERT INTO sofa_link VALUES (?, 'https://www.fotmob.com/match/6139566', 1, 0)", (MID,))
con.execute("INSERT INTO paper2 (created, match_id, title, start_ts, strategy, event, src, bookmaker, outcome, line, odds, ev, fair, fam)"
            " VALUES (0, ?, 'Чили U17 — Алжир U17', ?, 'Б', 'c_tt2', 'сайт', 'Фонбет', 'Меньше (4.5)', 4.5, 2.2, 0.06, 2.0, 'c_tt2')", (MID, START))
con.commit()
clock[0] = START + 70 * 60
c.fml_last = 0
c.fotmob_live_step()
r = con.execute('SELECT ft1, ft2, c1, c2 FROM ext_live WHERE match_id=?', (MID,)).fetchone()
print('с FotMob:', r)
assert r == (4, 2, 8, 4), r
b = [x for x in S.paper_stats(con, 100)['bets'] if x['title'] == 'Чили U17 — Алжир U17'][0]
print('в окне:', b['live'])
assert b['live']['c'] == [8, 4] and b['live']['ft'] == [4, 2]
# у конторы угловые есть — берутся они, FotMob не перебивает
con.execute("INSERT INTO bk_scores (match_id, part, s1, s2, comment, ts) VALUES (?, 'c', 5, 3, NULL, ?)", (MID, clock[0]))
con.commit()
b = [x for x in S.paper_stats(con, 100)['bets'] if x['title'] == 'Чили U17 — Алжир U17'][0]
assert b['live']['c'] == [5, 3]
# не чаще раза в 90 с на матч
n0 = len(asked); c.fml_last = 0; clock[0] += 30; c.fotmob_live_step()
assert not [a for a in asked[n0:] if 'matchDetails' in a]
# -63: FotMob считает матч оконченным — в окне «матч окончен», итог запрашивается сразу
fin = con.execute('SELECT fin FROM ext_live WHERE match_id=?', (MID,)).fetchone()[0]
print('окончен по FotMob:', fin)
assert fin == 1
assert [x for x in S.paper_stats(con, 100)['bets'] if x['title'] == 'Чили U17 — Алжир U17'][0]['live'].get('fin') == 1
con.execute('INSERT OR REPLACE INTO ext_scores (match_id, done, tries, last_try) VALUES (?, 0, 3, ?)', (MID, clock[0]))
con.commit()
clock[0] += 100; c.fml_last = 0; c.fotmob_live_step()
assert con.execute('SELECT last_try FROM ext_scores WHERE match_id=?', (MID,)).fetchone()[0] == 0 and c.ext_last == 0
print('ВСЁ ОК')

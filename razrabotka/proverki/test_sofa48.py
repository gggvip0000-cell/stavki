"""Проверка версии -48: ссылка на страницу матча на Sofascore для окна ставок."""
import sys
exec(open('/home/claude/bet/test_ext25.py', encoding='utf-8').read().split("x = S.ExtStats()")[0])
c.browser = Browser()
MID = 888100
con.execute('INSERT OR REPLACE INTO matches (match_id, title, url, home_en, away_en) VALUES (?,?,?,?,?)',
            (MID, 'Манчестер Сити — Фулхэм', 'https://odds.ru/football/match/x/1-2/', 'manchester-city', 'fulham'))
con.execute("INSERT INTO paper2 (created, match_id, title, start_ts, strategy, event, src, bookmaker, outcome, line, odds, ev, fam)"
            " VALUES (0, ?, 'Манчестер Сити — Фулхэм', ?, 'Б', 'total', 'сайт', 'Фонбет', 'Больше (2.5)', 2.5, 2.0, 0.06, 'total')",
            (MID, ev0['startTimestamp']))
con.commit()
clock[0] = ev0['startTimestamp'] - 3600
c.sofa_last = 0
c.sofa_link_step()
url = con.execute('SELECT url FROM sofa_link WHERE match_id=?', (MID,)).fetchone()[0]
print('ссылка:', url)
assert url == 'https://www.fotmob.com/match/5795522', url             # FotMob — первым (весь день одним запросом)
# матч, которого нет в записанном дне FotMob, — ищется на Sofascore
MID3 = 888102
con.execute('INSERT OR REPLACE INTO matches (match_id, title, url, home_en, away_en) VALUES (?,?,?,?,?)',
            (MID3, 'Копенгаген U19 — Вайле U19', 'https://odds.ru/football/match/z/5-6/', 'fc-kobenhavn-u19', 'vejle-u19'))
con.execute("INSERT INTO paper2 (created, match_id, title, start_ts, strategy, event, src, bookmaker, outcome, line, odds, ev, fam)"
            " VALUES (0, ?, 'Копенгаген U19 — Вайле U19', ?, 'Б', 'total', 'сайт', 'Фонбет', 'Больше (2.5)', 2.5, 2.0, 0.06, 'total')",
            (MID3, ev2['startTimestamp']))
con.commit()
saved = clock[0]; clock[0] = ev2['startTimestamp'] - 60; c.sofa_last = 0; c.sofa_link_step(); clock[0] = saved
u3 = con.execute('SELECT url FROM sofa_link WHERE match_id=?', (MID3,)).fetchone()[0]
print('ссылка Sofascore:', u3)
assert u3 == f"https://www.sofascore.com/ru/football/match/{ev2['slug']}/{ev2['customId']}", u3
ps = S.paper_stats(con, 100)
b = [x for x in ps['bets'] if x['title'] == 'Манчестер Сити — Фулхэм'][0]
assert b['url'] == url and b['sofa']
# матч, которого на Sofascore нет — ссылка остаётся на odds.ru, попыток не больше 3 раз в час
MID2 = 888101
con.execute('INSERT OR REPLACE INTO matches (match_id, title, url, home_en, away_en) VALUES (?,?,?,?,?)',
            (MID2, 'Никто — Нигде', 'https://odds.ru/football/match/y/3-4/', 'nobody-fc', 'none-utd'))
con.execute("INSERT INTO paper2 (created, match_id, title, start_ts, strategy, event, src, bookmaker, outcome, line, odds, ev, fam)"
            " VALUES (0, ?, 'Никто — Нигде', ?, 'Б', 'total', 'сайт', 'Фонбет', 'Больше (2.5)', 2.5, 2.0, 0.06, 'total')",
            (MID2, clock[0] + 7200))
con.commit()
for k in range(6):
    clock[0] += 3601; c.sofa_last = 0; c.sofa_link_step()
assert con.execute('SELECT url, tries FROM sofa_link WHERE match_id=?', (MID2,)).fetchone() == ('', 3)
b = [x for x in S.paper_stats(con, 100)['bets'] if x['title'] == 'Никто — Нигде'][0]
assert b['url'].startswith('https://odds.ru/') and not b['sofa']
print('ВСЁ ОК')

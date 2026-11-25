"""Проверка -56: все матчи — за один шаг; одна команда почти точно + единственный матч в это время — тоже находится."""
import json
exec(open('/home/claude/bet/test_ext25.py', encoding='utf-8').read().split("x = S.ExtStats()")[0])
c.browser = Browser()
t = open('/home/claude/bet/rs3/fotmob_day.txt', encoding='utf-8').read()
day = [m for lg in json.loads(t[t.find('{'):])['leagues'] for m in lg['matches']]
# 30 матчей дня с уникальным временем начала
picked = day[:30]
for k, m in enumerate(picked):
    mid = 777000 + k
    he = m['home']['name'].lower().replace(' ', '-'); ae = m['away']['name'].lower().replace(' ', '-')
    con.execute('INSERT OR REPLACE INTO matches (match_id, title, url, home_en, away_en) VALUES (?,?,?,?,?)',
                (mid, f't{k}', f'https://odds.ru/football/match/x/{k}-{k+1}/', he, ae))
    con.execute("INSERT INTO paper2 (created, match_id, title, start_ts, strategy, event, src, bookmaker, outcome, line, odds, ev, fam)"
                " VALUES (0, ?, ?, ?, 'Б', 'total', 'сайт', 'Фонбет', 'Больше (2.5)', 2.5, 2.0, 0.06, 'total')",
                (mid, f't{k}', m['timeTS'] / 1000))
# Ман Сити против «чужого» названия гостей: одна команда точно, время то же
ms = [m for m in day if m['home']['name'] == 'Manchester City'][0]
con.execute('INSERT OR REPLACE INTO matches (match_id, title, url, home_en, away_en) VALUES (?,?,?,?,?)',
            (778000, 'loose', 'https://odds.ru/football/match/x/9-10/', 'manchester-city', 'craven-cottagers'))
con.execute("INSERT INTO paper2 (created, match_id, title, start_ts, strategy, event, src, bookmaker, outcome, line, odds, ev, fam)"
            " VALUES (0, 778000, 'loose', ?, 'Б', 'total', 'сайт', 'Фонбет', 'Больше (2.5)', 2.5, 2.0, 0.06, 'total')",
            (ms['timeTS'] / 1000,))
con.commit()
clock[0] = picked[0]['timeTS'] / 1000 - 3600
c.sofa_last = 0
c.sofa_link_step()
got = dict(con.execute("SELECT match_id, url FROM sofa_link"))
ok = sum(1 for k, m in enumerate(picked) if got.get(777000 + k) == f"https://www.fotmob.com/match/{m['id']}")
print('за один шаг найдено:', ok, 'из', len(picked))
assert ok >= 28, got
print('по одной команде:', got.get(778000))
assert got.get(778000) == f"https://www.fotmob.com/match/{ms['id']}"
print('ВСЁ ОК')
# -58: матч без английских названий (записан до -11) — ищется по адресу odds.ru, порядок частей любой
m2 = day[40]
he = m2['away']['name'].lower().replace(' ', '-'); ae = m2['home']['name'].lower().replace(' ', '-')
con.execute('INSERT OR REPLACE INTO matches (match_id, title, url, home_en, away_en) VALUES (?,?,?,NULL,NULL)',
            (779000, 'old', f'https://odds.ru/football/match/{he}-vs-{ae}/5-7/'))
con.execute("INSERT INTO paper2 (created, match_id, title, start_ts, strategy, event, src, bookmaker, outcome, line, odds, ev, fam)"
            " VALUES (0, 779000, 'old', ?, 'Б', 'total', 'сайт', 'Фонбет', 'Больше (2.5)', 2.5, 2.0, 0.06, 'total')",
            (m2['timeTS'] / 1000,))
# матч без строки в matches вовсе — считается «без английских названий»
con.execute("INSERT INTO paper2 (created, match_id, title, start_ts, strategy, event, src, bookmaker, outcome, line, odds, ev, fam)"
            " VALUES (0, 779001, 'nomatch', ?, 'Б', 'total', 'сайт', 'Фонбет', 'Больше (2.5)', 2.5, 2.0, 0.06, 'total')",
            (m2['timeTS'] / 1000,))
con.commit()
c.sofa_last = 0; c.sofa_link_step()
u = con.execute('SELECT url FROM sofa_link WHERE match_id=779000').fetchone()
print('по адресу odds.ru:', u)
assert u and u[0] == f"https://www.fotmob.com/match/{m2['id']}"
sf = S.paper_stats(con, 100)['sofa']; print(sf)
assert sf['noname'] == 1
print('ВСЁ ОК 58')
# -59: женская лига — в адресе odds.ru пометки нет, на FotMob «(W)»
w = [m for m in day if '(W)' in m['home']['name']]
if w:
    mw = w[0]
    he = mw['home']['name'].replace(' (W)', '').lower().replace(' ', '-'); ae = mw['away']['name'].replace(' (W)', '').lower().replace(' ', '-')
    con.execute('INSERT OR REPLACE INTO matches (match_id, title, url, home_en, away_en) VALUES (?,?,?,?,?)',
                (779500, 'wom', 'https://odds.ru/football/match/x/11-12/', he, ae))
    con.execute("INSERT INTO paper2 (created, match_id, title, league, start_ts, strategy, event, src, bookmaker, outcome, line, odds, ev, fam)"
                " VALUES (0, 779500, 'wom', 'Австралия: Женская W-лига', ?, 'Б', 'total', 'сайт', 'Фонбет', 'Больше (2.5)', 2.5, 2.0, 0.06, 'total')",
                (mw['timeTS'] / 1000,))
    con.commit(); c.sofa_last = 0; c.sofa_link_step()
    u = con.execute('SELECT url FROM sofa_link WHERE match_id=779500').fetchone()
    print('женский:', mw['home']['name'], u); assert u and u[0] == f"https://www.fotmob.com/match/{mw['id']}"
else:
    print('в записанном дне нет женских матчей (W)')
print('ВСЁ ОК 59')

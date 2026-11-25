"""Проверка версии -25: Sofascore и FotMob (записанные ответы разведки 21.11) — счёт основного времени, тайм,
угловые; перевёрнутые хозяева; FotMob как запасной; расчёт бумаги по ним."""
import os, sys, json, glob, urllib.parse
DB = '/tmp/stavki.sqlite3'
if os.path.exists(DB):
    os.remove(DB)
sys.argv = ['x']
exec(open('/home/claude/bet/test_direct.py', encoding='utf-8').read().split('# sims')[0])
con = c.con

REC = {}
for fn in glob.glob('/home/claude/bet/rs3/*.txt'):
    parts = open(fn, encoding='utf-8', errors='ignore').read().split('\n\n', 2)
    if len(parts) == 3 and parts[0].startswith('http'):
        REC[parts[0]] = {'s': int(parts[1]) if parts[1].isdigit() else 0, 't': parts[2]}
ev0 = json.loads(REC[f'{S.SOFA_API}/event/16363661']['t'])['event']          # Ман Сити — Фулхэм
ev2 = json.loads(REC[f'{S.SOFA_API}/event/12391568']['t'])['event']          # Копенгаген U19 — Вайле U19
SEARCH = {'manchester city fulham': [ev0], 'fulham manchester city': [ev0],
          'fc kobenhavn u19 vejle u19': [ev2]}
asked = []


class Page:
    def __init__(self):
        self.url = ''

    def goto(self, url, **k):
        self.url = url

    def wait_for_timeout(self, ms):
        pass

    def close(self):
        pass

    def evaluate(self, js, url):
        asked.append(url)
        if '/search/events?q=' in url:
            q = urllib.parse.unquote(url.split('q=')[1].split('&')[0]).lower()
            return {'s': 200, 't': json.dumps({'results': [{'type': 'event', 'entity': e} for e in SEARCH.get(q, [])]})}
        return REC.get(url, {'s': 404, 't': '{"error":{"code":404}}'})


class Browser:
    def new_page(self, **k):
        return Page()


x = S.ExtStats()
B = Browser()
d = x.lookup(B, 'manchester-city', 'fulham', ev0['startTimestamp'])
print('Ман Сити — Фулхэм:', d)
assert d['src'] == 'sofascore' and d['ft'] == (1, 1) and d['ht'] == (0, 1) and d['c'] == (8, 6)
assert not [u for u in asked if 'fotmob' in u], 'всё нашлось на Sofascore — FotMob не нужен'
d = x.lookup(B, 'fulham', 'manchester-city', ev0['startTimestamp'])
print('перевёрнуто:', d)
assert d['ft'] == (1, 1) and d['ht'] == (1, 0) and d['c'] == (6, 8)
d = x.lookup(B, 'fc-kobenhavn-u19', 'vejle-u19', ev2['startTimestamp'])
print('Копенгаген U19 (угловых на Sofascore нет):', d)
assert d['ft'] == (4, 0) and d['ht'] == (1, 0) and 'c' not in d
d = x.lookup(B, 'chile-u17', 'algeria-u17', 1795275000)
print('Чили U17 (нет на Sofascore → FotMob):', d)
assert d['src'] == 'fotmob' and d['ft'] == (4, 2) and d['ht'] == (3, 2) and d['c'] == (8, 4)
assert x.lookup(B, 'chile-u17', 'algeria-u17', 1795275000 + 3 * 3600) == {}, 'не то время — не тот матч'

# расчёт бумаги: матч, которого нет ни в football-data, ни в лайве конторы
MID = 888001
START = 1795275000
con.execute('INSERT OR REPLACE INTO matches (match_id, home_en, away_en) VALUES (?,?,?)', (MID, 'chile-u17', 'algeria-u17'))
con.execute('INSERT INTO results VALUES (?,?,?,?)', (MID, 5, 4, 0))     # «итог» odds.ru с доп. временем: по нему фора −1.5 проиграла бы
for fam, line, side in (('c_total', 11.5, 0), ('h1_total', 4.5, 1), ('ah', -1.5, 0)):
    names = S.outcome_names(fam, line)
    con.execute('INSERT INTO paper2 (created, match_id, title, league, start_ts, strategy, event, src, bookmaker,'
                ' market_name, outcome, line, odds, fair, ev, rel, pin_age, fam) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (START - 3600, MID, 'Чили — Алжир', 'ЧМ U17', START, 'Б', fam, 'сайт', 'Фонбет', S.market_label(fam),
                 names[side], line, 2.0, 1.9, 0.06, 0.1, 30, fam))
con.commit()
clock[0] = START + 160 * 60
c.browser = B
c.ext_last = 0
c.ext_step()
r = con.execute('SELECT src, ft1, ft2, ht1, ht2, c1, c2, done, tries FROM ext_scores WHERE match_id=?', (MID,)).fetchone()
print('ext_scores:', r)
assert r == ('fotmob', 4, 2, 3, 2, 8, 4, 1, 1)
clock[0] = START + 3.5 * 3600
c.settle_paper()
st = dict(con.execute('SELECT fam, status FROM paper2 WHERE match_id=?', (MID,)).fetchall())
print('расчёт:', st)
assert st == {'c_total': 'выигрыш', 'h1_total': 'проигрыш', 'ah': 'выигрыш'}, st   # 12 угл.; тайм 3:2 = 5; 4:2
# матч не найден нигде: с -61 — до 40 попыток раз в 5 мин, потом не трогаем
MID2 = 888002
con.execute('INSERT OR REPLACE INTO matches (match_id, home_en, away_en) VALUES (?,?,?)', (MID2, 'nobody-fc', 'none-utd'))
con.execute('INSERT INTO paper2 (created, match_id, start_ts, strategy, event, src, bookmaker, outcome, line, odds, fam)'
            " VALUES (0, ?, ?, 'Б', 'total', 'сайт', 'Фонбет', 'Больше (2.5)', 2.5, 2.0, 'total')", (MID2, START))
con.commit()
c.ext_last = 0; c.ext_step(); c.ext_last = 0; c.ext_step()     # раньше 5 мин — повтора нет
assert con.execute('SELECT tries FROM ext_scores WHERE match_id=?', (MID2,)).fetchone()[0] == 1
for k in range(45):
    clock[0] += 301
    c.ext_last = 0
    c.ext_step()
assert con.execute('SELECT tries, done FROM ext_scores WHERE match_id=?', (MID2,)).fetchone() == (40, 0)
# основной рынок без внешнего счёта: по odds.ru, но только через 6 ч после начала
con.execute('INSERT INTO results VALUES (?,?,?,?)', (MID2, 2, 1, 0))
c.settle_paper()
assert con.execute('SELECT status FROM paper2 WHERE match_id=?', (MID2,)).fetchone()[0] == 'выигрыш'
print('ВСЁ ОК')

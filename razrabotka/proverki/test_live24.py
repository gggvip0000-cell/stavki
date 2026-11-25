"""Проверка версии -24: счёт из лайва Фонбета/PARI → расчёт первого тайма и угловых в любой лиге; «нет данных»;
простая таблица для владельца."""
import os, sys, json
DB = '/tmp/stavki.sqlite3'
if os.path.exists(DB):
    os.remove(DB)
sys.argv = ['x']
exec(open('/home/claude/bet/test_direct.py', encoding='utf-8').read().split('# sims')[0])
con = c.con

t = open('/home/claude/bet/rk/fonbet_net_037.txt', encoding='utf-8', errors='ignore').read()
j = json.loads(t.split('\n\n', 1)[1])
f = S.DirectFeed(c.feeds[0].book)
f.merge(j)
EID, MID = 69559401, 777001                       # Оренбург — Балтика: 0:2, перерыв (0-1), угловые 4:7
START = f.events[EID]['startTime']
assert f.miscs[EID]['score2'] == 2
f.match_map[EID] = MID
f.match_map[EID + 1] = None
clock[0] = START + 112 * 60
c.save_scores(f)
sc = {r[0]: r[1:] for r in con.execute('SELECT part, s1, s2 FROM bk_scores WHERE match_id=?', (MID,))}
print('счёт из лайва:', sc)
assert sc == {'ft': (0, 2), 'h1': (0, 1), 'c': (4, 7)}, sc
assert con.execute('SELECT match_id FROM bk_events WHERE event_id=?', (EID,)).fetchone() == (MID,)
# после перезапуска программы соответствие помнится
c2 = S.Collector(c.cfg, con)
assert c2.bk_known.get(EID) == MID

# второй матч: голы в лайве не совпадут с итогом — угловые не рассчитываются; третий — видели только до 60-й минуты
for mid in (777002, 777003):
    con.execute('INSERT INTO bk_scores (match_id, part, s1, s2, comment, ts) VALUES (?,?,?,?,?,?)', (mid, 'ft', 1, 0, None, START + 112 * 60 if mid == 777002 else START + 75 * 60))
    con.execute('INSERT INTO bk_scores (match_id, part, s1, s2, comment, ts) VALUES (?,?,?,?,?,?)', (mid, 'c', 6, 6, None, START + 112 * 60 if mid == 777002 else START + 75 * 60))
    con.execute('INSERT INTO results VALUES (?,?,?,?)', (mid, 1, 1 if mid == 777002 else 0, 0))
con.execute('INSERT INTO results VALUES (?,?,?,?)', (MID, 0, 2, 0))


def bet(mid, fam, line, side, odds=1.9):
    names = S.outcome_names(fam, line)
    con.execute('INSERT INTO paper2 (created, match_id, title, league, start_ts, strategy, event, src, bookmaker,'
                ' market_name, outcome, line, odds, fair, ev, rel, pin_age, fam) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (START - 3600, mid, 'матч', 'лига', START, 'Б', S.event_group(fam) if False else fam, 'сайт', 'Фонбет',
                 S.market_label(fam), names[side], line, odds, odds / 1.06, 0.06, 0.1, 30, fam))
    return names[side]


o1 = bet(MID, 'c_total', 10.5, 0)                 # угловых 11 — больше 10.5 выигрыш
o2 = bet(MID, 'h1_1x2', None, 2)                  # тайм 0:1 — П2 выигрыш
o3 = bet(MID, 'total', 2.5, 1)                    # голов 2 — меньше 2.5 выигрыш
o4 = bet(MID, 'c_tt1', 4.5, 1)                    # у хозяев 4 угловых — меньше 4.5 выигрыш
bet(777002, 'c_total', 11.5, 0)                   # голы 1:0 в лайве, итог 1:1 — не рассчитывать
bet(777003, 'c_total', 11.5, 1)                   # видели только до ~60-й минуты — не рассчитывать
con.commit()
clock[0] = START + 2 * 3600          # с -49 тайм и угловые не ждут 3 ч
c.settle_paper()
st = dict(con.execute('SELECT outcome || " " || fam || " " || match_id, status FROM paper2').fetchall())
for k, v in st.items():
    print(' ', k, '→', v)
assert st[f'{o1} c_total {MID}'] == 'выигрыш'
assert st[f'{o2} h1_1x2 {MID}'] == 'выигрыш'
assert st[f'{o3} total {MID}'] == 'open'          # основное время: ждём Sofascore/FotMob до 6 ч после начала
assert st[f'{o4} c_tt1 {MID}'] == 'выигрыш'
assert [v for k, v in st.items() if k.endswith('777002')] == ['open']
assert [v for k, v in st.items() if k.endswith('777003')] == ['open']

# через 2 дня без данных — «нет данных», в итоги не входят
clock[0] = START + 2 * 86400 + 60
c.settle_paper()
st = dict(con.execute('SELECT match_id, status FROM paper2 WHERE match_id IN (777002, 777003)').fetchall())
assert con.execute("SELECT status FROM paper2 WHERE fam='total' AND match_id=?", (MID,)).fetchone()[0] == 'выигрыш'
assert set(st.values()) == {'нет данных'}, st
S.VIEW_CODES, S.MAIN_CODE = (('Б', 'x'),), 'Б'   # -123: проверка по ставкам способа Б этого теста
ps = S.paper_stats(con, 100)
print('для владельца:', [(r['val'], r['n'], r['w'], r['l'], r['push'], r['n'] - r['done'], r['profit_rub']) for r in ps['simple']])
print('всего:', ps['simple_total']['n'], ps['simple_total']['profit_rub'], '| не рассчитать:', ps['nodata'])
assert ps['simple_total']['n'] == 4 and ps['simple_total']['w'] == 4 and ps['nodata'] == 2
assert round(ps['simple_total']['profit_rub']) == 360
assert {r['val'] for r in ps['simple']} == {'Угловые: Тотал', '1-й тайм: 1Х2', 'Тотал', 'Угловые: Инд. тотал хозяев'}
assert any(cut['title'] == 'Контора' for cut in ps['cuts']) and any(cut['title'] == 'День недели' for cut in ps['cuts'])

# первый тайм и угловые идут на бумагу в любой лиге (без статистики football-data)
v = {'match_id': 1, 'market': 'c_total', 'line': 9.5, 'market_name': 'Угловые: Тотал', 'outcome': 'Больше (9.5)',
     'src': 'сайт', 'ev': 0.07, 'odds': 1.9, 'rel': 0.1, 'chance': 0.6, 'bookmaker': 'Фонбет'}
assert S.pick_for_strategies([v]), 'угловые не пошли на бумагу'
print('ВСЁ ОК')

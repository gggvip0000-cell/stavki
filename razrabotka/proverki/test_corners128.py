"""-128: угловые идущих матчей — подсобытие «угловые», табло потока (liveEventInfos), запрос табло матча (events/event);
матч без угловых нигде — повтор через 5 мин и цель для разведки страницы. Без сохранённых записей владельца."""
import sys, json, tempfile, pathlib, time
sys.path.insert(0, '/home/claude/stavki')
import stavki as S
S.HERE = pathlib.Path(tempfile.mkdtemp())
con = S.db_open()
now = time.time()
# 4 идущих матча, у всех наша открытая ставка на угловые (у 4-го — только Олимп, ставки PARI нет)
for mid, bk in ((1, 'PARI'), (2, 'PARI'), (3, 'PARI'), (4, 'Олимп')):
    con.execute("INSERT INTO paper2 (created, match_id, title, start_ts, strategy, event, src, bookmaker, outcome, line, odds, ev, fam)"
                " VALUES (0, ?, 'м', ?, 'С', 'c_tt1', 'сайт', ?, 'Меньше (9.5)', 9.5, 1.9, 0.06, 'c_tt1')", (mid, now - 50 * 60, bk))
con.commit()
f = S.DirectFeed(S.DIRECT_BOOKS[1])
f.page = object()
calls = []
DETAIL = {
    # 30: табло матча с угловыми (как ЕНППИ — Серамика 25.11 22:03)
    30: {'events': [{'id': 30, 'level': 1}], 'eventMiscs': [],
         'liveEventInfos': [{'eventId': 30, 'subscores': [
             {'kindId': '100201', 'kindName': '1-й тайм', 'c1': '1', 'c2': '0'},
             {'kindId': '10100201', 'kindName': '1-й тайм угловые', 'c1': '9', 'c2': '9'},
             {'kindId': '400100', 'kindName': 'угловые', 'alias': 'Score.Corners', 'c1': '4', 'c2': '2', 'comment': '(1-1)'}]}]},
    # 40: угловых нет нигде
    40: {'events': [{'id': 40, 'level': 1}], 'eventMiscs': [],
         'liveEventInfos': [{'eventId': 40, 'subscores': [{'kindId': '100201', 'kindName': '1-й тайм', 'c1': '0', 'c2': '0'}]}]},
}
def fetch(path):
    calls.append(path)
    eid = int(path.split('eventId=')[1].split('&')[0])
    assert path.startswith('/events/event?lang=ru&version=0&eventId=') and 'scopeMarket=2300' in path, path
    return json.loads(json.dumps(DETAIL[eid]))
f.fetch = fetch
f.geo = {'197': 'egypt'}
f.merge({
    'sports': [{'id': 23989, 'parentId': 1, 'geoCategoryId': 197}],
    'events': [{'id': i, 'level': 1, 'place': 'live', 'sportId': 23989, 'team1': f'Х{i}', 'team2': f'Г{i}', 'startTime': now - 3000}
               for i in (10, 20, 30, 40)] + [{'id': 11, 'parentId': 10, 'level': 2, 'name': 'угловые', 'place': 'live'}],
    'eventMiscs': [{'id': i, 'score1': 1, 'score2': 0, 'comment': '', 'timerSeconds': 3000, 'timerDirection': 1} for i in (10, 20, 30, 40)]
                  + [{'id': 11, 'score1': 5, 'score2': 3, 'comment': '(2-1)'}],
    # 20: угловые только в табло потока
    'liveEventInfos': [{'eventId': 20, 'subscores': [{'kindId': '400100', 'alias': 'Score.Corners', 'c1': '6', 'c2': '1'}]}],
    'packetVersion': 5})
f.match_map = {10: 1, 20: 2, 30: 3, 40: 4}
C = S.Collector.__new__(S.Collector)
C.con, C.bk_known, C.cdet, C.csrc, C.feeds = con, {}, {}, {}, [f]
C.save_scores(f)
sc = {(m, p): (a, b) for m, p, a, b in con.execute('SELECT match_id, part, s1, s2 FROM bk_scores')}
print(sc); print({k: v.get('src') for k, v in C.csrc.items()})
assert sc[(1, 'c')] == (5, 3) and C.csrc[1]['src'] == 'подсобытие'
assert sc[(2, 'c')] == (6, 1) and C.csrc[2]['src'] == 'табло потока'
assert sc[(3, 'c')] == (4, 2) and C.csrc[3]['src'] == 'табло матча'          # не «1-й тайм угловые» 9:9
assert (4, 'c') not in sc and C.csrc[4]['src'] is None                      # Олимп-ставка тоже учитывается
assert C.cdet[4]['kinds'] == ['1-й тайм'] and C.cdet[4]['c'] is None
assert len(calls) == 2, calls                                               # запрос табло — только для 30 и 40
# разведка страницы — только матч без угловых нигде, адрес pari.ru
t = C.corner_recon_target()
print('цель разведки:', t)
assert t and t[2] == 4 and t[0] == 'https://pari.ru/sports/football/country/egypt/23989/40', t
# через 15 с: матч 30 спрашивается снова (угловые изменились), матч 40 — нет (повтор через 5 мин)
DETAIL[30]['liveEventInfos'][0]['subscores'][2].update(c1='5', c2='2')
f.scores_ts -= 16
for k in C.cdet: C.cdet[k]['ts'] -= 16
C.cdet[3]['ok_ts'] -= 16
C.save_scores(f)
assert len(calls) == 3 and 'eventId=30' in calls[-1], calls
assert con.execute("SELECT s1, s2 FROM bk_scores WHERE match_id=3 AND part='c'").fetchone() == (5, 2)
# старое табло матча (>90 с) — не берётся в save_scores
C.cdet[3].update(ok_ts=now - 200, ts=now)   # не пора спрашивать снова
con.execute("UPDATE bk_scores SET s1=0, s2=0 WHERE match_id=3 AND part='c'"); con.commit()
f.scores_ts -= 16
C.save_scores(f)
assert con.execute("SELECT s1, s2 FROM bk_scores WHERE match_id=3 AND part='c'").fetchone() == (0, 0)
# ошибка запроса не роняет счёт
def bad(path): raise RuntimeError('ответ 500')
f.fetch = bad; C.cdet[4]['ts'] -= 400; f.scores_ts -= 16
C.save_scores(f)
assert 'ответ 500' in C.cdet[4]['err'] and C.corner_recon_target() is None
# полная перезагрузка линии сбрасывает табло потока
f.fetch = lambda p: {'events': [], 'packetVersion': 6}
f.version = None; f.poll()
assert f.lei == {}
# lei_corners: мусор не роняет
assert S.lei_corners(None) is None and S.lei_corners({'subscores': [{'alias': 'Score.Corners', 'c1': 'x', 'c2': '1'}]}) is None
print('ВСЁ ОК')

"""-121: итог чужого матча FotMob (Аль-Сиб — Аль-Шорта: 1:5 вместо 2:0) — сопоставление, отказ, перепроверка, пересчёт."""
exec(open('/home/claude/bet/test_live24.py', encoding='utf-8').read().split("# через 2 дня без данных")[0])
M = 777121
print('sim', S.en_sim('al-seeb', 'Al Sailiya'), S.en_sim('al-shorta', 'Al Shamal'), S.en_sim('al-seeb', 'Al-Seeb'))
assert S.en_sim('al-seeb', 'Al Sailiya') < 0.6 and S.en_sim('al-shorta', 'Al Shamal') < 0.6
con.execute('INSERT OR REPLACE INTO matches (match_id, title, league, start_ts, url, home_en, away_en) VALUES (?,?,?,?,?,?,?)',
            (M, 'Аль-Сиб — Аль-Шорта', 'Мир: Кубок АФК', START, '', 'al-seeb', 'al-shorta'))
p1 = bet(M, '1x2', None, 0, 2.7)
m15 = bet(M, 'tt2', 1.5, 1, 1.62)
con.execute("INSERT INTO bk_scores (match_id, part, s1, s2, comment, ts) VALUES (?,?,?,?,?,?)", (M, 'ft', 1, 0, None, START + 50 * 60))
con.execute("INSERT INTO bk_scores (match_id, part, s1, s2, comment, ts) VALUES (?,?,?,?,?,?)", (M, 'h1', 1, 0, None, START + 50 * 60))
con.execute("INSERT INTO ext_scores (match_id, src, ext_id, ft1, ft2, ht1, ht2, c1, c2, done, tries, last_try) VALUES"
            " (?,?,?,?,?,?,?,?,?,1,3,0)", (M, 'fotmob', '6050102', 1, 5, 0, 2, 13, 4))
con.execute("INSERT INTO sofa_link VALUES (?,?,1,0)", (M, 'https://www.fotmob.com/match/6054517'))
con.commit()
c.settle_paper()
st = dict(con.execute('SELECT outcome, status FROM paper2 WHERE match_id=?', (M,)).fetchall()); print('до:', st)
assert st[p1] == 'проигрыш' and st[m15] == 'проигрыш'

ts = START * 1000
WRONG = {'id': 6050102, 'timeTS': ts, 'home': {'name': 'Al Sailiya'}, 'away': {'name': 'Al Shamal'}}
RIGHT = {'id': 6054517, 'timeTS': ts + 300000, 'home': {'name': 'Al-Seeb'}, 'away': {'name': 'Al Shorta'}}
def det(fid, ft, ht, c):
    return {'header': {'status': {'finished': True}, 'teams': [{'name': 'x', 'score': ft[0]}, {'name': 'y', 'score': ft[1]}]},
            'content': {'matchFacts': {'events': {'events': [
                {'type': 'Half', 'halfStrShort': 'HT', 'homeScore': ht[0], 'awayScore': ht[1]},
                {'type': 'Half', 'halfStrShort': 'FT', 'homeScore': ft[0], 'awayScore': ft[1]}]}},
                'stats': {'Periods': {'All': {'stats': [{'stats': [{'key': 'corners', 'stats': list(c)}]}]}}}}}
DET = {'6050102': det(6050102, (1, 5), (0, 2), (13, 4)), '6054517': det(6054517, (2, 0), (1, 0), (6, 3))}
x = c.ext
x.fm_list = lambda st_: [WRONG, RIGHT]
x.get = lambda key, url: DET.get(url.split('matchId=')[-1]) if 'matchDetails' in url else None
x.page = lambda b, key, url: (None if key == 'sofascore' else object())
c.browser = object()
# без ссылки новый поиск тоже берёт верный матч
d = x.fotmob('al-seeb', 'al-shorta', START)
print('поиск без ссылки:', d.get('ext_id'), d.get('ft')); assert d['ext_id'] == '6054517' and d['ft'] == (2, 0)
# перепроверка: итог исправлен, ставки пересчитаны
clock[0] = START + 3 * 3600
c.ext_recheck()
r = con.execute('SELECT ext_id, ft1, ft2, ht1, ht2, ver FROM ext_scores WHERE match_id=?', (M,)).fetchone(); print(r)
assert r[:5] == ('6054517', 2, 0, 1, 0) and r[5] == S.EXT_VER
st = dict(con.execute('SELECT outcome, status FROM paper2 WHERE match_id=?', (M,)).fetchall()); print('после:', st)
assert st[p1] == 'выигрыш' and st[m15] == 'выигрыш'
rs = con.execute('SELECT DISTINCT res_h, res_a FROM paper2 WHERE match_id=?', (M,)).fetchall(); assert rs == [(2, 0)], rs
print(c.ext_checks[-1]['what'])
# новый итог, спорящий с лайвом, не принимается
assert c.ext_conflict(M, {'ft': (1, 5), 'ht': (0, 2)})
assert c.ext_conflict(M, {'ft': (2, 0), 'ht': (1, 0)}) is None
# второй раз не перепроверяет
n0 = len(c.ext_checks); c.ext_rc_last = 0; c.ext_recheck(); assert len(c.ext_checks) == n0
print('ВСЁ ОК')

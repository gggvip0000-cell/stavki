"""-82: угловые из лайва конторы засчитываются, когда итог матча дал FotMob, а odds.ru — нет (Чоннам — Ансан 22.11)."""
exec(open('/home/claude/bet/test_live24.py', encoding='utf-8').read().split("# через 2 дня без данных")[0])
M4, M5 = 777004, 777005
for mid, ft in ((M4, (1, 2)), (M5, (1, 2))):
    con.execute('INSERT INTO bk_scores (match_id, part, s1, s2, comment, ts) VALUES (?,?,?,?,?,?)', (mid, 'ft', 1, 2, None, START + 110 * 60))
    con.execute('INSERT INTO bk_scores (match_id, part, s1, s2, comment, ts) VALUES (?,?,?,?,?,?)', (mid, 'c', 5, 3, None, START + 110 * 60))
# M4: odds.ru итога нет, FotMob 1:2 — совпало; M5: FotMob 2:2 — не совпало
con.execute("INSERT INTO ext_scores (match_id, src, ext_id, ft1, ft2, done, tries, last_try) VALUES (?, 'fotmob', 'x', 1, 2, 1, 1, 0)", (M4,))
con.execute("INSERT INTO ext_scores (match_id, src, ext_id, ft1, ft2, done, tries, last_try) VALUES (?, 'fotmob', 'y', 2, 2, 1, 1, 0)", (M5,))
o5 = bet(M4, 'c_tt2', 3.5, 1)          # у гостей 3 угловых — меньше 3.5 выигрыш
bet(M5, 'c_tt2', 3.5, 1)
con.commit(); c.settle_paper()
r4 = con.execute('SELECT status, res_h, res_a FROM paper2 WHERE match_id=?', (M4,)).fetchone()
r5 = con.execute('SELECT status FROM paper2 WHERE match_id=?', (M5,)).fetchone()
print('FotMob совпал:', r4, '| не совпал:', r5)
assert r4 == ('выигрыш', 5, 3) and r5 == ('open',)
print('ВСЁ ОК')

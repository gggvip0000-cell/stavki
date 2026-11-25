"""-101: досрочный расчёт тотала/инд. тотала, когда исход уже не изменится; сверка с итогом."""
exec(open('/home/claude/bet/test_live24.py', encoding='utf-8').read().split("# через 2 дня без данных")[0])
import time as _t
now = _t.time()
M1, M2, M3 = 778001, 778002, 778003
bet(M1, 'c_tt2', 4.5, 1)          # М 4.5 угловых гостей — при 2:5 уже проиграна
bet(M2, 'c_total', 6.5, 0)        # Б 6.5 угловых — при 3:3 ещё не решена
bet(M3, 'total', 2.25, 0)         # Б 2.25 голов — при 2:1 (3 > 2.5) уже выиграна
con.execute('UPDATE paper2 SET start_ts=? WHERE match_id IN (?,?,?)', (now - 3600, M1, M2, M3))
for mid, part, s1, s2 in ((M1, 'c', 2, 5), (M2, 'c', 3, 3), (M3, 'ft', 2, 1)):
    con.execute('INSERT OR REPLACE INTO bk_scores (match_id, part, s1, s2, comment, ts) VALUES (?,?,?,?,?,?)', (mid, part, s1, s2, None, now))
con.commit()
c.settle_early()
st = {m: con.execute('SELECT status, early, res_h, res_a FROM paper2 WHERE match_id=?', (m,)).fetchone() for m in (M1, M2, M3)}
print(st)
assert st[M1][:2] == ('проигрыш', 1) and st[M2][0] == 'open' and st[M3][:2] == ('выигрыш', 1)
# итог: голы 3:1 → счёт обновлён, флаг снят
con.execute("INSERT INTO ext_scores (match_id, src, ext_id, ft1, ft2, done, tries, last_try) VALUES (?, 'fotmob', 'z', 3, 1, 1, 1, 0)", (M3,))
con.commit(); c.settle_early()
r = con.execute('SELECT status, early, res_h, res_a FROM paper2 WHERE match_id=?', (M3,)).fetchone(); print(r)
assert r == ('выигрыш', 0, 3, 1)
# старый счёт (>3 мин) не берётся
con.execute('UPDATE bk_scores SET ts=? WHERE match_id=?', (now - 600, M2)); con.execute("UPDATE bk_scores SET s1=9 WHERE match_id=?", (M2,)); con.commit()
c.settle_early(); assert con.execute('SELECT status FROM paper2 WHERE match_id=?', (M2,)).fetchone()[0] == 'open'
print('ВСЁ ОК')

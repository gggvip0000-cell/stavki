"""-92: счёт угловых, введённый вручную, рассчитывает ставку (Чоннам — Ансан 22.11)."""
exec(open('/home/claude/bet/test_live24.py', encoding='utf-8').read().split("# через 2 дня без данных")[0])
M = 777092
bet(M, 'c_tt2', 3.5, 1)                 # М 3.5 угловых гостей
con.commit(); c.settle_paper()
assert con.execute('SELECT status FROM paper2 WHERE match_id=?', (M,)).fetchone() == ('open',)
S.STATE.manual_q.append((M, 'c', 6, 2))
mq, S.STATE.manual_q = S.STATE.manual_q, []
for mid_, part_, h_, a_ in mq:
    con.execute('INSERT OR REPLACE INTO manual_scores (match_id, part, h, a, ts) VALUES (?,?,?,?,?)', (mid_, part_, h_, a_, 0))
c.settle_paper()
r = con.execute('SELECT status, res_h, res_a FROM paper2 WHERE match_id=?', (M,)).fetchone()
print(r); assert r == ('выигрыш', 6, 2)
print('ВСЁ ОК')

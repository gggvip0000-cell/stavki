"""-99: счёт матча вручную рассчитывает ставки на основные рынки (Монтана — Добруджа 0:0)."""
exec(open('/home/claude/bet/test_live24.py', encoding='utf-8').read().split("# через 2 дня без данных")[0])
M = 777099
o = bet(M, 'tt1', 1.5, 1)              # М 1.5 хозяев
con.commit(); c.settle_paper()
assert con.execute('SELECT status FROM paper2 WHERE match_id=?', (M,)).fetchone() == ('open',)
con.execute('INSERT INTO manual_scores (match_id, part, h, a, ts) VALUES (?,?,?,?,?)', (M, 'ft', 0, 0, 0)); con.commit()
c.settle_paper()
r = con.execute('SELECT status, res_h, res_a FROM paper2 WHERE match_id=?', (M,)).fetchone(); print(r)
assert r[0] in ('выигрыш', 'проигрыш') and r[1:] == (0, 0)
print('ВСЁ ОК')

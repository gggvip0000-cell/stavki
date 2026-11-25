"""-84: изменение цены Pinnacle внутри минуты после записи больше не теряется — пишется, когда минута прошла."""
src = open('/home/claude/bet/test_pin11.py', encoding='utf-8').read().split('# Pinnacle перестал отвечать')[0]
exec(src)
mid = next(m for m in S.STATE.pin_fair if ('1x2', None) in c.pin.fair.get(m, {}))
key = ('1x2', None)
now = clock[0]; c.pin.pin_written[mid] = now          # только что записали
p, po, ts = c.pin.fair[mid][key]
new_po = [round(x * 1.3, 3) if i == 0 else x for i, x in enumerate(po)]   # П1 подорожал на 30%
with c.pin.lock: c.pin.fair[mid][key] = (S.fair_power(new_po), new_po, now + 5)
clock[0] = now + 5; c.pin_apply([mid])
n1 = c.con.execute('SELECT COUNT(*) FROM pin WHERE match_id=? AND ts>?', (mid, now)).fetchone()[0]
clock[0] = now + 70; c.pin_apply([])                  # новых изменений нет, минута прошла
rows = c.con.execute("SELECT ts, raw FROM pin WHERE match_id=? AND market='match_winner' AND ts>? ORDER BY ts", (mid, now)).fetchall()
print('внутри минуты записано:', n1, '| после минуты:', [(r[0] - now, r[1][:80]) for r in rows])
assert n1 == 0 and rows and abs(rows[-1][0] - (now + 5)) < 1e-6
import json
got = [x for x in json.loads(rows[-1][1]) if 'П1' in x[0]][0][1]
assert abs(float(got[0]) - new_po[0]) < 1e-9, got
cf = c.closing_fair(mid, '1x2', 'П1', None, S.STATE.matches[mid]['start'])
print('цена закрытия П1 теперь', cf); 
print('ВСЁ ОК')

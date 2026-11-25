"""-85: сводка CLV без повторов на настоящем журнале отчёта 22.11 10:00 — сходится с ручным разбором (42 ставки, −2.38%, угловые +2.97%)."""
import sys, json, sqlite3
sys.path.insert(0, '/home/claude/stavki'); import stavki as S
d = json.load(open('/home/claude/bet/r1000/report.json'))
con = sqlite3.connect(':memory:')
cols = list(d['cand'][0].keys())
con.execute('CREATE TABLE cand (%s, close_ts REAL)' % ', '.join(cols))
for r in d['cand']:
    con.execute('INSERT INTO cand (%s) VALUES (%s)' % (', '.join(cols), ', '.join('?' * len(cols))), [r[c] for c in cols])
r = S.clv_dedup(con)
print('всё:', r['all']); print('по частям:', r['by_part']); print('половины:', r['halves'])
assert r['all']['n'] == 42 and abs(r['all']['clv'] - (-2.38)) < 0.01
assert abs(r['by_part']['УГЛОВЫЕ']['clv'] - 2.97) < 0.01 and r['by_part']['МАТЧ']['n'] == 23
assert r['reliable_close']['n'] == 0          # в старых строках времени цены закрытия нет
print('ВСЁ ОК')

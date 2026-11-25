"""-103: способы Г (перевес 8%+) и Д (только угловые от 3%) — вживую и задним числом по журналу cand."""
exec(open('/home/claude/bet/test_live24.py', encoding='utf-8').read().split("# через 2 дня без данных")[0])
import json, time as _t
d = json.load(open('/home/claude/bet/r1653/report.json'))
con.execute("DELETE FROM paper2 WHERE strategy IN ('Г','Д')")
cols = [r[1] for r in con.execute('PRAGMA table_info(cand)')]
for r in d['cand']:
    con.execute(f"INSERT OR IGNORE INTO cand ({','.join(k for k in r if k in cols)}) VALUES ({','.join('?' for k in r if k in cols)})",
                [r[k] for k in r if k in cols])
con.commit()
S.backfill_new_strategies(con)
g = con.execute("SELECT strategy, COUNT(*), MIN(ev), SUM(fam LIKE 'c!_%' ESCAPE '!') FROM paper2 WHERE strategy IN ('Г','Д') GROUP BY 1").fetchall()
print(g)
gd = dict((x[0], x) for x in g)
assert gd['Г'][2] >= 0.08 and gd['Д'][3] == gd['Д'][1] and gd['Д'][1] > 10
n = con.execute("SELECT COUNT(*) FROM paper2").fetchone()[0]; S.backfill_new_strategies(con)
assert con.execute("SELECT COUNT(*) FROM paper2").fetchone()[0] == n            # второй раз не пишет
print('ВСЁ ОК')

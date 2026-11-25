"""-126: С/Т начинаются со ставок П/Р на угловые и 1-й тайм (без МАТЧА), один раз."""
exec(open('/home/claude/bet/test_live24.py', encoding='utf-8').read().split("# через 2 дня без данных")[0])
con.execute("DELETE FROM paper2")
def ins(code, mid, fam, st='выигрыш'):
    con.execute("INSERT INTO paper2 (created, match_id, title, start_ts, strategy, event, src, bookmaker, market_name, outcome,"
                " line, odds, fair, ev, rel, status, profit, fam) VALUES (1,?,?,1,?,?,'сайт','PARI','x','Меньше (4.5)',4.5,2,1.8,.06,.1,?,1,?)",
                (mid, 't', code, fam + '|x', st, fam))
for i, f in enumerate(['total', 'c_tt1', 'c_tt2', 'h1_1x2', 'tt2']): ins('П', 100 + i, f)
for i, f in enumerate(['total', 'c_tt1']): ins('Р', 200 + i, f, 'open')
con.commit()
S.copy_view_rows(con)
g = dict(con.execute("SELECT strategy, group_concat(fam) FROM paper2 WHERE strategy IN ('С','Т') GROUP BY 1").fetchall())
print(g)
assert sorted(g['С'].split(',')) == ['c_tt1', 'c_tt2', 'h1_1x2'] and g['Т'] == 'c_tt1'
assert con.execute("SELECT COUNT(*) FROM paper2 WHERE strategy='П'").fetchone()[0] == 5      # П не тронут
ins('П', 300, 'c_tt1'); con.commit(); S.copy_view_rows(con)                                    # второй раз не переносит
assert con.execute("SELECT COUNT(*) FROM paper2 WHERE strategy='С'").fetchone()[0] == 3
ps = S.paper_stats(con, 100)
print({k: v['simple_total']['n'] for k, v in ps['views'].items()})
assert ps['views']['С']['simple_total']['n'] == 3 and ps['views']['Т']['simple_total']['n'] == 1
print('ВСЁ ОК')

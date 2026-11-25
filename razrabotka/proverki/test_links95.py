exec(open('/home/claude/bet/test_live24.py', encoding='utf-8').read().split("# через 2 дня без данных")[0])
M = 777095
bet(M, 'c_tt2', 2.5, 1)
con.execute("UPDATE paper2 SET bk_url=NULL, bookmaker='Фонбет' WHERE match_id=?", (M,)); con.commit()
class F:
    name = 'Фонбет'; match_map = {55: M, 56: M}
    events = {55: {'id': 55, 'sportId': 1}, 56: {'id': 56, 'parentId': 55}}
    def event_url(s, ev): return 'https://fon.bet/x/%s' % ev['id']
c.fill_links(F())
r = con.execute('SELECT bk_url FROM paper2 WHERE match_id=?', (M,)).fetchall()
print(r); assert r and all(x[0] == 'https://fon.bet/x/55' for x in r)
print('ВСЁ ОК')

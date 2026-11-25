"""-115: «1-й тайм угловые» (подсобытие «угловых», level 3) относится к матчу; ссылка Олимпа; Олимп в окне, Фонбет — нет."""
import sys, json, re, glob; sys.path.insert(0, '/home/claude/stavki'); import stavki as S
f = S.DirectFeed.__new__(S.DirectFeed)
f.events, f.factors, f.miscs, f.touched, f.kids, f.version, f.sports = {}, {}, {}, {}, {}, 0, {}
f.merge({'events': [{'id': 1, 'level': 1, 'name': '', 'team1': 'A', 'team2': 'B'},
                    {'id': 2, 'parentId': 1, 'level': 2, 'name': 'угловые'},
                    {'id': 3, 'parentId': 2, 'level': 3, 'name': '1-й тайм угловые'},
                    {'id': 4, 'parentId': 1, 'level': 2, 'name': '1-й тайм'}], 'customFactors': []})
print(f.kids)
assert sorted(f.kids[1]) == [(2, 'c_'), (3, 'ch_'), (4, 'h1_')] and 2 not in f.kids
# на настоящей записи Фонбета 21.11: у матчей есть «1-й тайм угловые»
t = open('/home/claude/bet/rk/fonbet_net_037.txt').read()
j = json.loads(t[t.find('{'):])
g = S.DirectFeed.__new__(S.DirectFeed); g.events, g.factors, g.miscs, g.touched, g.kids, g.version, g.sports = {}, {}, {}, {}, {}, 0, {}
g.merge(j)
n = sum(1 for k in g.kids.values() if any(p == 'ch_' for _, p in k))
print('матчей с угловыми 1-го тайма:', n); assert n > 0
# ссылка Олимпа
o = S.OlimpFeed()
url = o.event_url({'_ol': {'id': '86242415', 'competitionId': '8337793', 'competitionName': 'Лига Чемпионов UEFA. Общий этап',
                           'team1Name': 'Галатасарай', 'team2Name': 'Астон Вилла', 'startDateTime': int(S.datetime.datetime(2026, 11, 24, 20, 45, tzinfo=S.MSK).timestamp())}})
print(url); assert url.endswith('/line/futbol-1/liga-chempionov-uefa-obschiy-etap-8337793/galatasaray-aston-villa-24-11-2026-86242415')
assert 'Фонбет' in S.JOURNAL_ONLY and 'Олимп' not in S.JOURNAL_ONLY and any(s[0] == 'И' for s in S.STRATEGIES)
print('ВСЁ ОК')

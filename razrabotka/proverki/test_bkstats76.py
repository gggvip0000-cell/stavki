"""Проверка -76: разведка статистики идущего матча у Фонбета/PARI — в отчёт."""
exec(open('/home/claude/bet/test_paper8.py', encoding='utf-8').read())
con.execute("INSERT INTO paper2 (created, match_id, title, start_ts, strategy, event, src, bookmaker, outcome, line, odds, ev, fam, bk_url)"
            " VALUES (0, 555, 'Чоннам — Ансан', ?, 'Б', 'c_tt2', 'сайт', 'PARI', 'Меньше (3.5)', 3.5, 1.8, 0.054, 'c_tt2', 'https://www.pari.ru/sports/football/x')",
            (clock[0] - 46 * 60,))
con.commit()
class R:
    def __init__(s, u, b): s.url, s.body, s.headers = u, b, {'content-type': 'application/json'}
    def text(s): return s.body
class PG:
    def on(s, ev, cb): setattr(s, ev, cb)
    def goto(s, url, **k):
        s.response(R('https://x/events/list', '{"a":1}'))
        s.response(R('https://stats.example/match/1', '{"stats":{"corners":[0,0],"yellowCards":[2,1]}}'))
    def wait_for_timeout(s, ms): pass
    def inner_text(s, sel): return 'Статистика Угловые 0 0'
    def close(s): pass
class B:
    def new_page(s, **k): return PG()
r = S.bk_stats_recon(B(), con)
print(r['match'], r['responses'], [h['url'] for h in r['hits']])
assert r['hits'] and 'corners' in r['hits'][0]['part']
print('ВСЁ ОК')

import sys; sys.path.insert(0, '/home/claude/stavki'); import stavki as S
class R:
    def __init__(s, u, b): s.url, s.status, s.headers, s.b = u, 200, {'content-type': 'application/json'}, b
    def text(s): return s.b
class PG:
    def __init__(s): s.url = ''; s.h = {}
    def on(s, ev, cb): s.h[ev] = cb
    def goto(s, u, **k):
        s.url = u
        if 'response' in s.h and '/1/2' in u: s.h['response'](R('https://www.olimp.bet/api/v4/0/line/events/2', '{"markets":[{"name":"Угловые. Тотал","c":1.85}]}'))
    def wait_for_timeout(s, ms): pass
    def eval_on_selector_all(s, sel, js): return ['https://www.olimp.bet/line/futbol-1/1', 'https://www.olimp.bet/line/futbol-1/1/2', 'https://www.olimp.bet/live/futbol-1/9/9']
    def inner_text(s, sel): return 'Матч ... Угловые: Тотал больше 9.5 — 1.85'
    def close(s): pass
class B:
    def new_page(s, **k): return PG()
r = S.bk_event_recon(B(), 'Олимп', 'https://www.olimp.bet/line/futbol-1', '/line/futbol-1/', wait_ms=0)
print(r['event_url'], r['corner_mentions'], r['responses'][0].get('corner_snips'))
assert r['event_url'].endswith('/1/2') and r['corner_mentions'] == 1 and r['responses'][0]['corner_snips']
print('ВСЁ ОК')

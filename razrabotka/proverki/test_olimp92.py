import sys, json; sys.path.insert(0, '/home/claude/stavki'); import stavki as S
LIST = json.dumps([{"operationId":"L","payload":{"id":"1","categoriesWithCompetitions":[{"competitions":[
    {"id":"11664","name":"Англия. Премьер-лига","eventCount":23},
    {"id":"777","name":"Англия. Премьер-лига. Статистика","eventCount":9},
    {"id":"778","name":"Дания. Суперлига. Статистика","eventCount":3}]}]}}])
COMP = lambda cid: json.dumps([{"operationId":"C","payload":{"competitionsWithEvents":[{"events":[
    {"id":"500" if cid=='777' else "100","name":("УГЛ А - УГЛ Б" if cid=='777' else "А - Б"),"competitionId":cid,
     "parentId":"100" if cid=='777' else None,"team1Name":"А","outcomes":[{"groupName":"Тотал","tableType":"TOTAL",
     "marketId":3,"shortName":"ТотБ","param":"9.5","probability":"1.9"}]}]}]}}])
EV = lambda i: json.dumps([{"operationId":"E","payload":{"id":i,"name":"x","team1Name":"А","outcomes":[
    {"groupName":"Исход","tableType":"RESULT","marketId":1,"shortName":"П1","probability":"2.1"}]}}])
class R:
    def __init__(s, u, b): s.url, s.status, s.b = u, 200, b
    def text(s): return s.b
class PG:
    def __init__(s): s.url = ''; s.h = {}; s.f = []
    def on(s, ev, cb): s.h[ev] = cb
    def goto(s, u, **k):
        s.url = u
        s.h['response'](R('https://www.olimp.bet/api/v4/0/line/sports-with-categories-with-competitions?vids%5B%5D=', LIST))
        if '11664' in u:
            s.h['response'](R('https://www.olimp.bet/api/v4/0/line/competitions-with-events?vids%5B%5D=11664%3A', COMP('11664')))
    def wait_for_timeout(s, ms): pass
    def inner_text(s, sel): return 'Футбол'
    def eval_on_selector_all(s, sel, js): return [
        ['https://www.olimp.bet/line/futbol-1/angliya-premer-liga-11664/a-b-22-11-2026-100', 'А - Б'],
        ['https://www.olimp.bet/line/futbol-1/liga-chempionov-8337793/c-d-200', 'В - Г']]
    def evaluate(s, js, u):
        s.f.append(u)
        if 'competitions-with-events' in u: return {'s': 200, 't': COMP(u.split('=')[1].split('%')[0])}
        if 'line/events' in u: return {'s': 200, 't': EV(u.split('=')[1].split('%')[0])}
        return {'s': 404, 't': ''}
    def close(s): pass
pg = PG()
class B:
    def new_page(s, **k): return pg
r = S.olimp_recon(B(), wait_ms=0)
print(r['comp_url'], r['comp_id'], r['stat_comps']['n'], r['comp_queries'])
for f in r['fetches']: print(f['why'], f['url'][-60:], (f.get('summ') or {}).get('n_events'), [g['group'] for g in (f.get('summ') or {}).get('groups', [])])
assert r['comp_id'] == '11664' and r['stat_comps']['n'] == 2 and r['stat_comps']['top'][0][1] == '777'
assert any('vids%5B%5D=777' in u for u in pg.f) and any('vids%5B%5D=500' in u for u in pg.f) and any('vids%5B%5D=100' in u for u in pg.f)
# заблокирована — дальше не идёт
class PG2(PG):
    def inner_text(s, sel): return 'Подтвердите, что вы не робот'
pg = PG2(); r = S.olimp_recon(B(), wait_ms=0); assert len(r['pages']) == 1 and not pg.f
print('ВСЁ ОК')

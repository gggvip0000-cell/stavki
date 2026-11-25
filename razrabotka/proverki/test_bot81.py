"""Проверка -78: сообщения «жив/тревога» в Telegram и разведка новых контор."""
exec(open('/home/claude/bet/test_paper8.py', encoding='utf-8').read())
class T:
    connecting = False
    def __init__(s): s.out = []; s.upd = []
    def send(s, t): s.out.append(t)
    def ready(s): return True
    cmds = None
    def api(s, m, p, timeout=20):
        if m == 'setMyCommands': s.cmds = p['commands']; return {'ok': True}
        if m == 'getUpdates':
            if p.get('offset') == -1: return {'result': [{'update_id': 10}]}
            r = [u for u in s.upd if u['update_id'] >= p['offset']]; return {'result': r}
        return {}
t = T()
w = S.Watchdog(t, con)
print('запуск:', t.out[-1]); assert 'запущена' in t.out[-1]
now = clock[0]
S.STATE.status['feeds'] = {'Pinnacle': {'last_ok': now}, 'PARI': {'last_ok': now}, 'Винлайн': {'last_ok': now}}
w.started = now - 2000; w.last_check = 0; w.step(); n0 = len(t.out)
clock[0] += 1000; w.last_tick = clock[0] - 10; w.last_check = 0; w.step()    # Pinnacle молчит 16 мин, PARI тоже
print('тревоги:', t.out[n0:]); assert any('VPN' in x for x in t.out[n0:]) and any('PARI' in x for x in t.out[n0:])
n1 = len(t.out); w.last_check = 0; w.last_tick = clock[0]; w.step(); assert len(t.out) == n1, 'повтор раньше часа'
S.STATE.status['feeds']['Pinnacle']['last_ok'] = clock[0]; w.last_check = 0; w.last_tick = clock[0]; w.step()
print('починилось:', t.out[n1:]); assert any('Починилось' in x and 'Pinnacle' in x for x in t.out[n1:])
n2 = len(t.out); w.last_tick = clock[0] - 1200; w.last_check = clock[0]; w.step()
print('сон:', t.out[n2:]); assert any('стояла' in x for x in t.out[n2:])
w.last_poll = 0; w.step()                         # первый опрос — запомнить номер
t.upd = [{'update_id': 11, 'message': {'text': 'Статус'}}]
w.last_poll = 0; n3 = len(t.out); w.step()
print('статус:', t.out[n3:]); assert t.out[n3:] and 'Работаю' in t.out[n3]
print('меню команд:', t.cmds); assert [c['command'] for c in t.cmds] == ['status', 'site']
for i, (txt, need) in enumerate([('/status', 'Работаю'), ('/site', 'Сайт'), ('/start', '/site —'), ('сайт', 'Сайт')]):
    t.upd = [{'update_id': 20 + i, 'message': {'text': txt}}]; w.last_poll = 0; n = len(t.out); w.step()
    print(txt, '→', t.out[n:][:1]); assert t.out[n:] and need in t.out[n], txt
# разведка новых контор: подделка браузера
class R:
    def __init__(s, u, b): s.url, s.status, s.body, s.headers = u, 200, b, {'content-type': 'application/json'}
    def text(s): return s.body
class PG:
    url = ''
    def on(s, ev, cb): setattr(s, ev, cb)
    def goto(s, url, **k):
        s.url = url
        s.response(R(url + 'api/line', '{"events":[' + ','.join('{"id":%d,"odds":[1.9,3.4,4.1]}' % i for i in range(80)) + ']}'))
    def wait_for_timeout(s, ms): pass
    def eval_on_selector_all(s, sel, js): return [['https://x.ru/sport/football', 'Футбол']]
    def inner_text(s, sel): return 'Футбол'
    def close(s): pass
class B:
    def new_page(s, **k): return PG()
r = S.new_bk_recon(B(), wait_ms=0)
print([(x['bk'], x['football_url'], len(x['responses']), 'head' in x['responses'][-1]) for x in r['sites']])
assert len(r['sites']) == 2 and r['sites'][0]['football_url']
print('ВСЁ ОК')

import sys, types
sys.path.insert(0, '/home/claude/stavki')
import stavki as S

class Resp:
    def __init__(s, st, url): s.status, s.url = st, url
class Req:
    def __init__(s, url, h): s.url, s.headers = url, h
class Ctx:
    def __init__(s, st): s.request = types.SimpleNamespace(get=lambda *a, **k: types.SimpleNamespace(status=st, text=lambda: '[]'))
class Page:
    def __init__(s, api_status, key='NEWKEY', ctx=403, fetch=403, title='Pinnacle', text='Soccer'):
        s.h = {}; s.api_status = api_status; s.key = key; s.url = S.PIN_SITE; s.context = Ctx(ctx)
        s.fetch = fetch; s._title = title; s._text = text
    def on(s, ev, f): s.h[ev] = f
    def goto(s, *a, **k):
        u = S.PIN_API + '/sports/29/leagues'
        if s.key: s.h['request'](Req(u, {'x-api-key': s.key}))
        s.h['response'](Resp(s.api_status, u))
    def wait_for_timeout(s, ms): pass
    def title(s): return s._title
    def inner_text(s, *a, **k): return s._text
    def evaluate(s, js, arg): return {'s': s.fetch, 't': '[]'}
class Br:
    def __init__(s, p): s.p = p
    def new_page(s, **k): return s.p

saved = {}
S.save_config_keys = lambda d: saved.update(d)
S.load_config = lambda: {'pinnacle_key': 'OLDKEY'}

# 1) page's own API calls get 403, all keys 403 → message about VPN address
f = S.PinnacleFeed()
calls = []
def hg(path, f=f):
    calls.append(f.headers['x-api-key'])
    f.diag['last_http'] = {'s': 403}
    raise RuntimeError('Pinnacle ответил 403 на ' + path)
f.http_get = hg
try:
    f.start(Br(Page(403))); assert False
except RuntimeError as e:
    msg = str(e)
print(msg)
assert "адресе VPN" in msg, msg
assert calls == ['NEWKEY', 'OLDKEY', S.PIN_PUBLIC_KEY], calls
assert [k for k, _ in f.diag['keys']] == ['страница', 'сохранённый', 'открытый']

# 2) page key fails, saved key works → thread mode, key not overwritten
f = S.PinnacleFeed(); saved.clear()
def hg2(path, f=f):
    if f.headers['x-api-key'] != 'OLDKEY':
        f.diag['last_http'] = {'s': 403}; raise RuntimeError('403')
    return []
f.http_get = hg2
f.run_thread = lambda: None
f.start(Br(Page(200)))
assert f.mode == 'thread' and saved == {}, (f.mode, saved)

# 3) direct fails, in-page fetch works → browser mode works
f = S.PinnacleFeed()
f.http_get = hg.__func__ if hasattr(hg, '__func__') else (lambda p: (_ for _ in ()).throw(RuntimeError('403')))
pg = Page(200, fetch=200)
f.start(Br(pg))
assert f.mode == 'browser'
assert f.get('/x') == []

# 4) restricted text
f = S.PinnacleFeed(); f.http_get = lambda p: (_ for _ in ()).throw(RuntimeError('403'))
try:
    f.start(Br(Page(403, key=None, text='Pinnacle is not available in your country'))); assert False
except RuntimeError as e:
    assert 'из этой страны' in str(e), str(e)
print('ok')

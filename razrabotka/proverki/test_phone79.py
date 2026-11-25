"""Проверка -79: вход с телефона через проход — пароль, жетон, запреты; без пароля с ноутбука всё как раньше."""
import threading, urllib.request, urllib.error, json, http.cookiejar
exec(open('/home/claude/bet/shot60.py',encoding='utf-8').read().split("srv=S.ThreadingHTTPServer")[0])
import tempfile, pathlib
S.HERE = pathlib.Path(tempfile.mkdtemp())
S.CFG = {'port': 8798}
srv=S.ThreadingHTTPServer(('127.0.0.1',8798),S.Handler); threading.Thread(target=srv.serve_forever,daemon=True).start()
B='http://127.0.0.1:8798'
class NoRedir(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None
op = urllib.request.build_opener(NoRedir)
def req(path, data=None, remote=False, cookie=None, ctype='application/json'):
    h = {'Content-Type': ctype}
    if remote: h['Cf-Connecting-Ip'] = '1.2.3.4'
    if cookie: h['Cookie'] = cookie
    r = urllib.request.Request(B + path, data=data, headers=h)
    try:
        resp = op.open(r, timeout=10); return resp.status, resp.read().decode('utf-8', 'replace'), resp.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace'), e.headers
st, body, _ = req('/api/state'); print('ноутбук без пароля:', st); assert st == 200
st, body, _ = req('/api/state', remote=True); print('телефон без пароля, api:', st); assert st == 401
st, body, _ = req('/', remote=True); print('телефон, страница:', st, 'вход' in body); assert 'Пароль для входа' in body
st, body, _ = req('/api/phone_pass', json.dumps({'p': 'short'}).encode()); print('короткий пароль:', body); assert '"ok": false' in body
st, body, _ = req('/api/phone_pass', json.dumps({'p': 'Длинный-пароль-1'}).encode(), remote=True); print('пароль с телефона:', st); assert st in (401, 403)
st, body, _ = req('/api/phone_pass', json.dumps({'p': 'Длинный-пароль-1'}).encode()); print('пароль с ноутбука:', body); assert '"ok": true' in body
assert 'Длинный' not in (S.HERE / 'config.json').read_text(encoding='utf-8'), 'пароль в открытом виде!'
st, body, _ = req('/login', 'p=wrong'.encode(), remote=True, ctype='application/x-www-form-urlencoded'); print('неверный:', 'Неверный' in body)
import urllib.parse
st, body, hd = req('/login', urllib.parse.urlencode({'p': 'Длинный-пароль-1'}).encode(), remote=True, ctype='application/x-www-form-urlencoded')
ck = hd.get('Set-Cookie', ''); print('верный:', st, ck[:40]); assert st == 303 and ck.startswith('stk=')
cookie = ck.split(';')[0]
st, body, _ = req('/api/state', remote=True, cookie=cookie); print('телефон с жетоном:', st); assert st == 200
st, body, _ = req('/api/telegram', json.dumps({'token': 'x'}).encode(), remote=True, cookie=cookie); print('ключ Telegram с телефона:', st); assert st == 403
st, body, _ = req('/api/ping', remote=True); assert st == 200
for i in range(9): req('/login', b'p=bad', remote=True, ctype='application/x-www-form-urlencoded')
st, body, _ = req('/login', urllib.parse.urlencode({'p': 'Длинный-пароль-1'}).encode(), remote=True, ctype='application/x-www-form-urlencoded')
print('после 9 ошибок:', 'Слишком много' in body); assert 'Слишком много' in body
print('ВСЁ ОК')

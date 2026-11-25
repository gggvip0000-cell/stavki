"""Pinnacle с его сайта: вечерние записи 21.11 (на odds.ru Pinnacle уже нет)."""
import json, glob, sys, os, datetime
if os.path.exists('/tmp/stavki.sqlite3'): os.remove('/tmp/stavki.sqlite3')
sys.path.insert(0, '/home/claude/stavki')
import stavki as S
store = {}
for fn in glob.glob('/home/claude/bet/rr/*.txt'):
    t = open(fn, encoding='utf-8', errors='ignore').read()
    if t.startswith('/next-api'):
        u, b = t.split('\n\n', 1); store[u.strip()] = b
class FakeOdds:
    def evaluate(self, js, url):
        if isinstance(url, list): return [dict(self.evaluate(js, u), ms=5) for u in url]
        if url in store: return {'status': 200, 'text': store[url]}
        return {'status': 404, 'text': 'nf'}
pin = {}
for fn in glob.glob('/home/claude/bet/rp/pin_net_*.txt'):
    t = open(fn, 'rb').read(); u, b = t.split(b'\n\n', 1); pin[u.decode().replace(S.PIN_API, '')] = b.decode('utf-8', 'ignore')
class R:
    def __init__(s, st, t): s.status = st; s._t = t
    def text(s): return s._t
class Req:
    def get(s, url, headers=None, timeout=None):
        path = url.replace(S.PIN_API, '')
        assert headers.get('x-api-key') == 'K'
        if path in pin: return R(200, pin[path])
        import re
        m = re.match(r'/leagues/(\d+)/(matchups|markets/straight)$', path)
        if m:                                   # другие лиги — из «избранного» ответа, отфильтрованного по лиге
            lid = int(m.group(1)); hm = json.loads(pin['/sports/29/matchups/highlighted'])
            ids = {x['id'] for x in hm if x['league']['id'] == lid}
            if m.group(2) == 'matchups': return R(200, json.dumps([x for x in hm if x['id'] in ids]))
            hk = json.loads(pin['/sports/29/markets/highlighted/straight?primaryOnly=false'])
            return R(200, json.dumps([k for k in hk if k['matchupId'] in ids]))
        return R(200, '[]')
class Ctx: request = Req()
class PinPage: context = Ctx()
T0 = datetime.datetime(2026, 11, 21, 20, 15, tzinfo=S.MSK).timestamp(); clock = [T0]
S.time.time = lambda: clock[0]; S.time.sleep = lambda x: None
class FDT(datetime.datetime):
    @classmethod
    def now(cls, tz=None): return datetime.datetime.fromtimestamp(clock[0], tz or S.MSK)
S.datetime.datetime = FDT
S.HERE = __import__('pathlib').Path('/tmp')
S.MY_BOOKMAKERS = ['Фонбет', 'Винлайн', 'PARI']
c = S.Collector(dict(S.DEFAULT_CONFIG, pause_between_requests=0), S.db_open()); c.page = FakeOdds()
c.pin.page = PinPage(); c.pin.headers = {'x-api-key': 'K'}; c.pin_start_try = T0; c.pin.mode = 'browser'
c.refresh_events()
print('матчей odds.ru', len(S.STATE.matches), 'с англ. названиями', sum(1 for m in S.STATE.matches.values() if m.get('home_en')))
for k in range(300):
    clock[0] += 1.1; c.poll_pin()
st = S.STATE.status['feeds']['Pinnacle']; print('Pinnacle:', st)
assert st['matched'] >= 30, st
mids = [int(u.split('matchId=')[1].split('&')[0]) for u in store if 'coefficients' in u and 'full_time&periodId=full_time&marketId=match_winner' in u]
ms = [S.STATE.matches[m] for m in mids if m in S.STATE.matches]
print('матчей с записанными ценами контор:', len(ms), 'из них с Pinnacle:', sum(1 for m in ms if m['id'] in S.STATE.pin_fair))
c.update_batch(ms)
snap = S.STATE.snapshot()
mine = [v for v in snap['values'] if v['bookmaker'] in S.MY_BOOKMAKERS]
print('строк с перевесом всего', len(snap['values']), 'у моих контор', len(mine))
for v in sorted(mine, key=lambda v: -v['ev'])[:8]:
    print(' ', v['bookmaker'], v['match'], v['market_name'], v['outcome'], v['odds'], 'честная', v['fair'], f"+{v['ev']*100:.1f}%", 'Pinnacle', v.get('pin_age'))
assert mine
n = c.con.execute('SELECT COUNT(*) FROM pin').fetchone()[0]; print('записей цены Pinnacle в базе:', n); assert n > 0
# цена закрытия по записи с сайта Pinnacle
mid = next(iter(S.STATE.pin_fair)); m = S.STATE.matches[mid]
cf = c.closing_fair(mid, '1x2', 'П1', None, m['start']); print('цена закрытия П1', m['title'], cf); assert cf
# Pinnacle перестал отвечать — ошибка видна, через 10 неудач страница перезапускается
class Bad:
    class context:
        class request:
            @staticmethod
            def get(*a, **k): raise RuntimeError('net::ERR_CONNECTION_RESET')
c.pin.page = Bad(); started = []
c.start_pin = lambda: started.append(1)
for k in range(12): clock[0] += 700; c.poll_pin()
print('ошибка:', S.STATE.status['feeds']['Pinnacle'].get('error'), '| перезапусков:', len(started)); assert started
# режим своего потока: те же данные через http_get, основной цикл только забирает готовое
import copy
S.STATE.pin_fair.clear(); c.pin = S.PinnacleFeed(); c.pin.headers = {'x-api-key': 'K'}; c.pin.mode = 'thread'
c.pin.http_get = lambda path: json.loads(Req().get(S.PIN_API + path, headers={'x-api-key': 'K'}).text())
for k in range(400):
    clock[0] += 2
    with S.STATE.lock: ms = dict(S.STATE.matches)
    ch = c.pin.poll(ms)
    with c.pin.lock: c.pin.pending |= set(ch)
c.poll_pin()
print('поток: сопоставлено', S.STATE.status['feeds']['Pinnacle']['matched'], 'режим', S.STATE.status['feeds']['Pinnacle']['mode'])
assert S.STATE.status['feeds']['Pinnacle']['matched'] >= 30
print('ВСЁ ОК')

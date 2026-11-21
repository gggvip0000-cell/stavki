# -*- coding: utf-8 -*-
"""Ставки v1 — «на что можно поставить прямо сейчас».

Берёт коэффициенты с odds.ru (15 контор, в том числе Pinnacle) через обычный браузер,
считает честную цену по Pinnacle и показывает ставки российских контор, где коэффициент
выше честной цены. Окно программы: http://localhost:8765 — обновляется само.
Ничего не ставит и никуда не входит.
"""
import datetime
import json
import math
import re
import urllib.request
import sqlite3
import subprocess
import zipfile
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = "2026.11.21-3"
REPO_RAW = "https://raw.githubusercontent.com/gggvip0000-cell/stavki/main/"
HERE = Path(__file__).resolve().parent
RESTART_EXIT_CODE = 3            # Stavki.bat на этот код скачивает свежую версию и запускает снова
MSK = datetime.timezone(datetime.timedelta(hours=3))
PINNACLE_ID = 18

DEFAULT_CONFIG = {
    "port": 8765,
    "hours_ahead": 24,            # какие матчи брать: начало в ближайшие N часов
    "markets": ["match_winner", "total_points"],
    "leagues_only": [],           # пусто = все лиги, где есть Pinnacle; иначе список id лиг odds.ru
    "my_bookmakers": [],          # пусто = все российские конторы на odds.ru; иначе названия как на сайте
    "pause_between_requests": 0.5,
    "batch_matches": 6,           # сколько матчей запрашивать одновременно
    "my_bookmakers_list": ["Фонбет", "Винлайн", "PARI"],   # конторы, где есть счёт (выбор владельца 21.11)
    "refresh_events_sec": 120,
    "headless": True,
}

# ---------------------------------------------------------------- расчёт

def fair_power(odds):
    """Честные вероятности из коэффициентов Pinnacle: p_i = (1/o_i)^k, сумма = 1.
    Проверено на 45 685 матчах: точнее, чем делить маржу поровну."""
    inv = [1.0 / o for o in odds]
    lo, hi = 0.3, 4.0
    for _ in range(80):
        k = (lo + hi) / 2
        s = sum(x ** k for x in inv)
        if s > 1:
            lo = k
        else:
            hi = k
    return [x ** ((lo + hi) / 2) for x in inv]


def values_from_rates(data, pinnacle_id=PINNACLE_ID):
    """Из ответа odds.ru (data) делает список: исход × контора с перевесом над честной ценой."""
    data = data if isinstance(data, dict) else {}
    names = {b.get('id'): b.get('name', '') for b in (data.get('bookmakers') or []) if isinstance(b, dict)}
    out = []
    pin_rows = 0
    for r in (data.get('rates') or []):
        if not isinstance(r, dict):
            continue
        outcomes = [(o or {}).get('name', '?') for o in (r.get('outcomes') or [])]
        bks = [b for b in (r.get('bookmakers') or []) if isinstance(b, dict)]
        r = dict(r, bookmakers=bks)
        pin = next((b for b in bks if b.get('id') == pinnacle_id), None)
        if not pin:
            continue
        try:
            po = [None] * len(outcomes)
            for o in (pin.get('odds') or []):
                po[o['outcome']] = float(o['value'])
            if any(v is None or v <= 1.0 for v in po):
                continue
        except (ValueError, KeyError, IndexError, TypeError):
            continue
        pin_rows += 1
        p = fair_power(po)
        for b in r.get('bookmakers', []):
            if b.get('id') == pinnacle_id:
                continue
            for o in (b.get('odds') or []):
                try:
                    odd = float(o['value'])
                    i = o['outcome']
                except (ValueError, KeyError, TypeError):
                    continue
                if odd <= 1.0 or i >= len(p):
                    continue
                out.append({
                    'outcome': outcomes[i], 'bookmaker': names.get(b['id'], str(b['id'])), 'bk_id': b['id'],
                    'odds': odd, 'fair': round(1 / p[i], 3), 'pin_odds': po[i],
                    'ev': odd * p[i] - 1,
                })
    return out, pin_rows

def margins_from_rates(data):
    """Маржа каждой конторы по каждой строке рынка: сумма 1/кф − 1."""
    data = data if isinstance(data, dict) else {}
    names = {b.get('id'): b.get('name', '') for b in (data.get('bookmakers') or []) if isinstance(b, dict)}
    out = []
    for r in (data.get('rates') or []):
        if not isinstance(r, dict):
            continue
        n = len(r.get('outcomes') or [])
        for b in (r.get('bookmakers') or []):
            if not isinstance(b, dict):
                continue
            try:
                vals = [float(o['value']) for o in (b.get('odds') or [])]
            except (ValueError, KeyError, TypeError):
                continue
            if n and len(vals) == n and all(v > 1 for v in vals):
                m = sum(1 / v for v in vals) - 1
                if -0.05 < m < 0.3:
                    out.append((names.get(b.get('id'), str(b.get('id'))), m))
    return out

# ---------------------------------------------------------------- состояние

class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.matches = {}        # id -> dict(match info, last_update, markets{})
        self.values = {}         # key -> value row
        self.status = {'started': now_str(), 'events_updated': None, 'errors': [], 'requests': 0,
                       'cycle_info': '', 'last_ok': None, 'version': VERSION, 'update_available': None,
                       'restarting': False, 'avg_request': None, 'razvedka': None}
        self.restart_requested = False
        self.razvedka_requested = False
        self.margins = {}        # (контора, рынок) -> [сумма, число строк]

    def snapshot(self):
        with self.lock:
            vals = sorted(self.values.values(), key=lambda v: -v['ev'])
            now = time.time()
            rows = []
            for v in vals:
                m = self.matches.get(v['match_id'], {})
                rows.append(dict(v, age=int(now - v['updated']), held=int(now - v['first_seen']),
                                 match=m.get('title', ''), league=m.get('league', ''),
                                 start=m.get('start_str', ''), url=m.get('url', '')))
            tracked = len(self.matches)
            fresh = sum(1 for m in self.matches.values() if m.get('last_update') and now - m['last_update'] < 300)
            st = dict(self.status, tracked=tracked, fresh=fresh, now=now_str())
            marg = {}
            for (bk, market), (sm, n) in self.margins.items():
                marg.setdefault(bk, {})[MARKET_NAMES.get(market, market)] = [round(100 * sm / n, 1), n]
        return {'values': rows, 'status': st, 'margins': marg, 'mine': MY_BOOKMAKERS}


def now_str():
    return datetime.datetime.now(MSK).strftime('%d.%m %H:%M:%S')


STATE = State()
MY_BOOKMAKERS = []

# ---------------------------------------------------------------- база для учёта (CLV потом)

def db_open():
    con = sqlite3.connect(str(HERE / 'stavki.sqlite3'), check_same_thread=False)
    con.execute('CREATE TABLE IF NOT EXISTS pin (ts REAL, match_id INT, market TEXT, raw TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS value_seen (match_id INT, market TEXT, outcome TEXT, bookmaker TEXT,'
                ' first_seen REAL, last_seen REAL, best_ev REAL, odds_at_best REAL, fair_at_best REAL,'
                ' PRIMARY KEY (match_id, market, outcome, bookmaker))')
    con.execute('CREATE TABLE IF NOT EXISTS matches (match_id INT PRIMARY KEY, title TEXT, league TEXT,'
                ' start_ts REAL, url TEXT)')
    con.commit()
    return con

# ---------------------------------------------------------------- окно программы

PAGE = r"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Ставки — можно ставить сейчас</title>
<style>
body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#0f1419;color:#e6e6e6}
header{padding:14px 20px;background:#151c24;border-bottom:1px solid #253040;display:flex;gap:24px;align-items:center;flex-wrap:wrap}
h1{font-size:20px;margin:0 16px 0 0}
.st{font-size:13px;color:#9fb0c0}
.ok{color:#5fd38d}.bad{color:#ff6b6b}
main{padding:16px 20px}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{padding:7px 9px;border-bottom:1px solid #222c38;text-align:left;white-space:nowrap}
th{color:#9fb0c0;font-weight:600;position:sticky;top:0;background:#0f1419}
tr.big td{background:#132a1d}
.ev{font-weight:700;color:#5fd38d}
.dim{color:#7d8b99}
input{width:60px;background:#0f1419;color:#e6e6e6;border:1px solid #33414f;padding:3px 5px}
label{font-size:13px;color:#9fb0c0;margin-right:12px}
a{color:#7fb6ff}
.empty{padding:30px;color:#9fb0c0}
.ubtn{background:#2f7d4f;color:#fff;border:0;padding:7px 14px;border-radius:6px;font-size:14px;cursor:pointer}
.ubtn:hover{background:#3a9a62}
.ver{font-size:12px;color:#5f6e7c}
.rbtn{background:#24313f;color:#cfd8e3;border:1px solid #33414f;padding:5px 10px;border-radius:6px;font-size:13px;cursor:pointer}
.src{font-size:12px;color:#d8a657}
h2{font-size:15px;color:#9fb0c0;margin:28px 0 8px}
.mt{width:auto}
.mt td,.mt th{font-size:13px;padding:5px 18px 5px 9px}
</style></head><body>
<header><h1>Можно ставить сейчас</h1>
<span id="upd"></span>
<span class="st" id="st">загрузка…</span>
<span><label>перевес от, % <input id="thr" type="number" step="0.5" value="5"></label>
<label>кф до <input id="mx" type="number" step="0.5" value="4"></label>
<label>контора <input id="bk" type="text" style="width:110px" placeholder="все"></label>
<label><input id="mine" type="checkbox" checked style="width:auto"> только мои конторы</label></span>
<span id="rz"></span>
</header><main><div id="tb"></div><div id="mg"></div></main>
<script>
function fmt(s){if(s<60)return s+' с';if(s<3600)return Math.floor(s/60)+' мин';return Math.floor(s/3600)+' ч '+Math.floor(s%3600/60)+' мин'}
async function tick(){
 try{
  const r=await fetch('/api/state',{cache:'no-store'});const d=await r.json();const s=d.status;
  const parts=['сейчас '+s.now,'матчей в работе '+s.tracked+' (обновлены за 5 мин: '+s.fresh+')','список матчей обновлён '+(s.events_updated||'—')];
  if(s.cycle_info)parts.push(s.cycle_info);
  if(s.avg_request)parts.push('ответ odds.ru в среднем '+s.avg_request+' с');
  let html=parts.join(' · ');
  if(s.errors.length)html+='<br><span class="bad">последняя ошибка: '+s.errors[s.errors.length-1]+'</span>';
  document.getElementById('st').innerHTML=html;
  const u=document.getElementById('upd');
  if(s.restarting){u.innerHTML='<span class="st">Обновляюсь… окно вернётся само примерно через минуту</span>'}
  else if(s.update_available){u.innerHTML='<button class="ubtn" onclick="doUpdate()">Обновить до версии '+s.update_available+'</button>'}
  else{u.innerHTML='<span class="ver">версия '+s.version+'</span>'}
  const thr=parseFloat(document.getElementById('thr').value||0)/100, mx=parseFloat(document.getElementById('mx').value||99), bk=document.getElementById('bk').value.trim().toLowerCase();
  const onlyMine=document.getElementById('mine').checked;
  const rz=document.getElementById('rz');
  if(s.razvedka){rz.innerHTML='<span class="st">Разведка контор: '+s.razvedka+'</span>'}
  else{rz.innerHTML='<button class="rbtn" onclick="doRazvedka()">Разведка контор (≈4 мин)</button>'}
  renderMargins(d.margins, d.mine);
  const rows=d.values.filter(v=>v.ev>=thr&&v.odds<=mx&&(!bk||v.bookmaker.toLowerCase().includes(bk))&&(!onlyMine||d.mine.includes(v.bookmaker)));
  if(!rows.length){document.getElementById('tb').innerHTML='<div class="empty">Сейчас ставок с таким перевесом нет. Страница обновляется сама.</div>';return}
  let h='<table><tr><th>Перевес</th><th>Матч</th><th>Начало (МСК)</th><th>Лига</th><th>Ставка</th><th>Контора</th><th>Кф конторы</th><th>Честная цена</th><th>Мин. кф (+порог)</th><th>Pinnacle</th><th>Обновлено</th><th>Держится</th><th>Откуда цена</th></tr>';
  for(const v of rows){
   h+='<tr class="'+(v.ev>=0.08?'big':'')+'"><td class="ev">+'+(v.ev*100).toFixed(1)+'%</td><td><a href="'+v.url+'bet/" target="_blank">'+v.match+'</a></td><td>'+v.start+'</td><td class="dim">'+v.league+'</td><td>'+v.market_name+': '+v.outcome+'</td><td>'+v.bookmaker+'</td><td><b>'+v.odds+'</b></td><td>'+v.fair.toFixed(2)+'</td><td>'+(v.fair*(1+thr)).toFixed(2)+'</td><td class="dim">'+v.pin_odds+'</td><td class="dim">'+fmt(v.age)+' назад</td><td class="dim">'+fmt(v.held)+'</td><td class="src">odds.ru — сверить на сайте</td></tr>'}
  document.getElementById('tb').innerHTML=h+'</table>';
 }catch(e){document.getElementById('st').innerHTML='<span class="bad">нет связи с программой: она перезапускается или закрыта (чёрное окно Stavki)</span>'}
}
function renderMargins(m,mine){
 const bks=Object.keys(m||{}).sort((a,b)=>(mine.includes(b)-mine.includes(a))||a.localeCompare(b));
 if(!bks.length){document.getElementById('mg').innerHTML='';return}
 let h='<h2>Маржа контор с запуска программы (чем ниже, тем чаще кф выше честной цены). В скобках — число линий</h2><table class="mt"><tr><th>Контора</th><th>1Х2</th><th>Тоталы</th></tr>';
 for(const b of bks){const r=m[b];const c=x=>x?x[0]+'% <span class="dim">('+x[1]+')</span>':'—';
  h+='<tr><td>'+(mine.includes(b)?'<b>'+b+'</b>':b)+'</td><td>'+c(r['1Х2'])+'</td><td>'+c(r['Тотал'])+'</td></tr>'}
 document.getElementById('mg').innerHTML=h+'</table>';
}
async function doRazvedka(){
 document.getElementById('rz').innerHTML='<span class="st">Разведка контор: запускаю…</span>';
 try{await fetch('/api/razvedka',{method:'POST'})}catch(e){}
}
async function doUpdate(){
 document.getElementById('upd').innerHTML='<span class="st">Обновляюсь… окно вернётся само примерно через минуту</span>';
 try{await fetch('/api/update',{method:'POST'})}catch(e){}
}
tick();setInterval(tick,3000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/api/state'):
            body = json.dumps(STATE.snapshot(), ensure_ascii=False).encode('utf-8')
            ctype = 'application/json; charset=utf-8'
        else:
            body = PAGE.encode('utf-8')
            ctype = 'text/html; charset=utf-8'
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path.startswith('/api/razvedka'):
            with STATE.lock:
                if not STATE.status['razvedka'] or STATE.status['razvedka'].startswith('готово'):
                    STATE.razvedka_requested = True
                    STATE.status['razvedka'] = 'в очереди…'
            log('нажата кнопка «Разведка контор»')
            body = b'{"ok": true}'
        elif self.path.startswith('/api/update'):
            with STATE.lock:
                STATE.restart_requested = True
                STATE.status['restarting'] = True
            log('нажата кнопка «Обновить»')
            body = b'{"ok": true}'
        else:
            body = b'{"ok": false}'
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass

# ---------------------------------------------------------------- сбор

MARKET_NAMES = {'match_winner': '1Х2', 'total_points': 'Тотал', 'asian_handicap': 'Фора',
                'both_teams_to_score': 'Обе забьют', 'double_chance': 'Двойной шанс'}

FETCH_MANY_JS = """async (urls) => Promise.all(urls.map(async (url) => { const t0 = performance.now();
 try { const r = await fetch(url, {credentials: 'include', cache: 'no-store'});
 return {status: r.status, text: await r.text(), ms: performance.now() - t0}; }
 catch (e) { return {status: -1, text: String(e), ms: performance.now() - t0}; } }))"""

RAZVEDKA_SITES = [('fonbet', 'Фонбет', 'https://fon.bet/'),
                  ('pari', 'PARI', 'https://pari.ru/'),
                  ('winline', 'Винлайн', 'https://winline.ru/')]

FETCH_JS = """async (url) => { try { const r = await fetch(url, {credentials: 'include', cache: 'no-store'});
 return {status: r.status, text: await r.text()}; } catch (e) { return {status: -1, text: String(e)}; } }"""


def log(msg):
    line = f'{now_str()} {msg}'
    print(line, flush=True)
    try:
        with open(HERE / 'log.txt', 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def add_error(msg):
    log('ОШИБКА: ' + msg)
    with STATE.lock:
        STATE.status['errors'] = (STATE.status['errors'] + [f'{now_str()} {msg}'])[-5:]


class Collector:
    def __init__(self, cfg, con):
        self.cfg = cfg
        self.con = con
        self.page = None
        self.browser = None
        self.pw = None
        self.last_events = 0
        self.ever_ok = False

    # --- браузер
    def start_browser(self):
        from playwright.sync_api import sync_playwright
        if self.pw is None:
            self.pw = sync_playwright().start()
        for channel in ('chrome', 'msedge', None):
            try:
                kw = {'headless': self.cfg['headless']}
                if channel:
                    kw['channel'] = channel
                self.browser = self.pw.chromium.launch(**kw)
                break
            except Exception as e:
                log(f'браузер {channel or "chromium"} не запустился: {str(e).splitlines()[0]}')
        if self.browser is None:
            raise RuntimeError('не удалось запустить браузер')
        self.page = self.browser.new_page(locale='ru-RU')
        self.page.goto('https://odds.ru/football/', wait_until='domcontentloaded', timeout=90000)
        self.page.wait_for_timeout(5000)
        log('браузер открыт, odds.ru загружен')

    def restart_browser(self):
        try:
            if self.browser:
                self.browser.close()
        except Exception:
            pass
        self.browser = None
        time.sleep(5)
        self.start_browser()

    def shutdown_for_update(self):
        log('закрываю браузер и перезапускаюсь для обновления')
        try:
            if self.browser:
                self.browser.close()
            if self.pw:
                self.pw.stop()
        except Exception:
            pass
        try:
            self.con.close()
        except Exception:
            pass
        (HERE / 'restarting.flag').write_text(VERSION, encoding='utf-8')
        sys.exit(RESTART_EXIT_CODE)

    def parse_api(self, res, url):
        if res['status'] != 200:
            raise RuntimeError(f'ответ {res["status"]} на {url[:90]}')
        j = json.loads(res['text'])
        if not isinstance(j, dict) or j.get('status') != 'ok':
            raise RuntimeError(f'status={j.get("status") if isinstance(j, dict) else "?"} на {url[:90]}')
        data = j.get('data')
        return data if isinstance(data, dict) else {}

    def get_many(self, urls):
        res = self.page.evaluate(FETCH_MANY_JS, urls)
        ms = [r.get('ms', 0) for r in res]
        with STATE.lock:
            STATE.status['requests'] += len(urls)
            if ms:
                avg = sum(ms) / len(ms) / 1000
                old = STATE.status.get('avg_request')
                STATE.status['avg_request'] = round(avg if old is None else 0.8 * old + 0.2 * avg, 1)
        return res

    def get_json(self, url):
        res = self.page.evaluate(FETCH_JS, url)
        with STATE.lock:
            STATE.status['requests'] += 1
        if res['status'] != 200:
            raise RuntimeError(f'ответ {res["status"]} на {url[:90]}')
        j = json.loads(res['text'])
        if not isinstance(j, dict) or j.get('status') != 'ok':
            raise RuntimeError(f'status={j.get("status") if isinstance(j, dict) else "?"} на {url[:90]}')
        data = j.get('data')
        return data if isinstance(data, dict) else {}

    # --- список матчей
    def refresh_events(self):
        now = datetime.datetime.now(MSK)
        horizon = now + datetime.timedelta(hours=self.cfg['hours_ahead'])
        dates = sorted({now.date(), horizon.date()} | {(now + datetime.timedelta(days=1)).date()})
        found = {}
        ok_dates = 0
        for d in dates:
            if d > horizon.date():
                continue
            try:
                data = self.get_json(f'/next-api/sports/events/ru/?sport=football&status=all&date={d.isoformat()}&source=default')
            except Exception as e:
                add_error(f'список матчей на {d.isoformat()}: {str(e).splitlines()[0][:120]}')
                continue
            ok_dates += 1
            for lg in data.get('leagues', []):
                if self.cfg['leagues_only'] and lg.get('id') not in self.cfg['leagues_only']:
                    continue
                for ev in lg.get('events', []):
                    if (ev.get('status') or {}).get('name') != 'upcoming':
                        continue
                    try:
                        start = datetime.datetime.strptime(f"{ev['date']} {ev['time']}", '%Y-%m-%d %H:%M').replace(tzinfo=MSK)
                    except Exception:
                        continue
                    if not (now < start <= horizon):
                        continue
                    found[ev['id']] = {
                        'id': ev['id'], 'url': ev.get('url', ''),
                        'title': f"{ev['home']['title']} — {ev['away']['title']}",
                        'league': f"{lg.get('region', '')}: {lg.get('title', '')}",
                        'start': start.timestamp(), 'start_str': start.strftime('%d.%m %H:%M'),
                    }
            time.sleep(self.cfg['pause_between_requests'])
        if ok_dates == 0:
            raise RuntimeError('список матчей не получен ни за один день')
        with STATE.lock:
            for mid in list(STATE.matches):
                if mid not in found:
                    STATE.matches.pop(mid)
            for mid, m in found.items():
                old = STATE.matches.get(mid, {})
                m['last_update'] = old.get('last_update')
                m['no_pin'] = old.get('no_pin', 0)
                STATE.matches[mid] = m
            for k in [k for k, v in STATE.values.items() if v['match_id'] not in found]:
                STATE.values.pop(k)
            STATE.status['events_updated'] = now_str()
        cur = self.con.cursor()
        for m in found.values():
            cur.execute('INSERT OR REPLACE INTO matches VALUES (?,?,?,?,?)',
                        (m['id'], m['title'], m['league'], m['start'], m['url']))
        self.con.commit()
        self.last_events = time.time()
        log(f'матчей в ближайшие {self.cfg["hours_ahead"]} ч: {len(found)}')

    # --- какой матч обновлять следующим
    def interval_for(self, m, now):
        left = m['start'] - now
        base = 45 if left < 3 * 3600 else 120 if left < 12 * 3600 else 400
        if m.get('no_pin', 0) >= 2:       # в этом матче нет Pinnacle — заглядываем редко
            base = 1800
        return base

    def pick_next(self):
        now = time.time()
        best, best_over = None, -1e9
        with STATE.lock:
            for m in STATE.matches.values():
                last = m.get('last_update') or 0
                over = (now - last) / self.interval_for(m, now)
                if over > best_over:
                    best, best_over = m, over
        return best, best_over

    def match_url(self, mid, market):
        return (f'/next-api/coefficients/rates/ru/?sport=football&matchId={mid}'
                f'&metricId=full_time&periodId=full_time&marketId={market}&source=default')

    def pick_batch(self, k):
        now = time.time()
        with STATE.lock:
            scored = []
            for m in STATE.matches.values():
                last = m.get('last_update') or 0
                scored.append(((now - last) / self.interval_for(m, now), m))
        scored.sort(key=lambda x: -x[0])
        return [m for over, m in scored[:k] if over >= 1]

    def update_batch(self, ms):
        urls = [self.match_url(m['id'], mk) for m in ms for mk in self.cfg['markets']]
        res = self.get_many(urls)
        by_url = dict(zip(urls, res))
        errors = 0
        for m in ms:
            datas = {}
            for mk in self.cfg['markets']:
                u = self.match_url(m['id'], mk)
                try:
                    datas[mk] = self.parse_api(by_url[u], u)
                except Exception as e:
                    errors += 1
                    last_err = str(e).splitlines()[0][:200]
            self.apply_match(m, datas)
        self.con.commit()
        if errors:
            add_error(f'{errors} из {len(urls)} запросов не удались: {last_err}')
        return errors, len(urls)

    def apply_match(self, m, datas):
        mid = m['id']
        new_vals = {}
        any_pin = False
        marg = []
        for market, data in datas.items():
            vals, pin_rows = values_from_rates(data)
            marg += [(bk, market, mg) for bk, mg in margins_from_rates(data)]
            if pin_rows:
                any_pin = True
                compact = []
                for r in (data.get('rates') or []):
                    if not isinstance(r, dict):
                        continue
                    pin = next((b for b in (r.get('bookmakers') or []) if isinstance(b, dict) and b.get('id') == PINNACLE_ID), None)
                    if pin:
                        compact.append([[(o or {}).get('name') for o in (r.get('outcomes') or [])],
                                        [o.get('value') for o in sorted(pin.get('odds') or [], key=lambda x: x.get('outcome', 0))]])
                self.con.execute('INSERT INTO pin VALUES (?,?,?,?)',
                                 (time.time(), mid, market, json.dumps(compact, ensure_ascii=False)))
            for v in vals:
                if v['ev'] <= 0:
                    continue
                key = (mid, market, v['outcome'], v['bookmaker'])
                v.update(match_id=mid, market=market, market_name=MARKET_NAMES.get(market, market),
                         mine=v['bookmaker'] in MY_BOOKMAKERS)
                new_vals[key] = v
        now = time.time()
        with STATE.lock:
            for k in [k for k in STATE.values if k[0] == mid and k[1] in datas and k not in new_vals]:
                STATE.values.pop(k)
            for k, v in new_vals.items():
                old = STATE.values.get(k)
                v['first_seen'] = old['first_seen'] if old else now
                v['updated'] = now
                STATE.values[k] = v
            for bk, market, mg in marg:
                acc = STATE.margins.setdefault((bk, market), [0.0, 0])
                acc[0] += mg
                acc[1] += 1
            mm = STATE.matches.get(mid)
            if mm:
                mm['last_update'] = now
                mm['no_pin'] = 0 if any_pin else mm.get('no_pin', 0) + 1
        cur = self.con.cursor()
        for k, v in new_vals.items():
            cur.execute('INSERT INTO value_seen VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(match_id,market,outcome,bookmaker)'
                        ' DO UPDATE SET last_seen=excluded.last_seen,'
                        ' odds_at_best=CASE WHEN excluded.best_ev>best_ev THEN excluded.odds_at_best ELSE odds_at_best END,'
                        ' fair_at_best=CASE WHEN excluded.best_ev>best_ev THEN excluded.fair_at_best ELSE fair_at_best END,'
                        ' best_ev=MAX(best_ev, excluded.best_ev)',
                        (k[0], k[1], k[2], k[3], now, now, v['ev'], v['odds'], v['fair']))

    # --- разведка сайтов контор (по кнопке)
    def run_razvedka(self):
        stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M')
        out = HERE / f'razvedka_kontor_{stamp}'
        out.mkdir(exist_ok=True)
        lines, reqs, saved, wss = [], [], [], []

        def note(msg):
            lines.append(f'{now_str()} {msg}')
            log('разведка: ' + msg)

        def set_status(t):
            with STATE.lock:
                STATE.status['razvedka'] = t

        browser = None
        try:
            for channel in ('chrome', 'msedge', None):
                try:
                    kw = {'headless': False}
                    if channel:
                        kw['channel'] = channel
                    browser = self.pw.chromium.launch(**kw)
                    break
                except Exception as e:
                    note(f'браузер {channel} не запустился: {str(e).splitlines()[0]}')
            for tag, name, url in RAZVEDKA_SITES:
                set_status(f'смотрю {name}… (окно браузера откроется само, не трогайте)')
                page = browser.new_page(viewport={'width': 1400, 'height': 900}, locale='ru-RU')

                def on_resp(r, tag=tag):
                    try:
                        rt = r.request.resource_type
                        ct = r.headers.get('content-type', '')
                        reqs.append({'site': tag, 'url': r.url, 'status': r.status, 'type': rt, 'ct': ct,
                                     'time': datetime.datetime.now().strftime('%H:%M:%S')})
                        if (rt in ('xhr', 'fetch') or 'json' in ct) and len(saved) < 900:
                            body = r.body()
                            if len(body) <= 8_000_000:
                                fn = f'{tag}_net_{len(saved) + 1:03d}.txt'
                                (out / fn).write_bytes(r.url.encode('utf-8') + b'\n\n' + body)
                                saved.append(fn)
                    except Exception:
                        pass

                def on_ws(ws, tag=tag):
                    entry = {'site': tag, 'url': ws.url, 'frames': []}
                    wss.append(entry)

                    def fr(payload, d):
                        if len(entry['frames']) < 400:
                            t = payload if isinstance(payload, str) else payload[:3000].hex()
                            entry['frames'].append({'dir': d, 'time': datetime.datetime.now().strftime('%H:%M:%S'),
                                                    'data': t[:30000]})
                    ws.on('framereceived', lambda p: fr(p, 'in'))
                    ws.on('framesent', lambda p: fr(p, 'out'))

                page.on('response', on_resp)
                page.on('websocket', on_ws)
                try:
                    page.goto(url, wait_until='domcontentloaded', timeout=90000)
                    page.wait_for_timeout(8000)
                    try:
                        page.get_by_text('Футбол', exact=False).first.click(timeout=6000)
                        note(f'{name}: нажал «Футбол», адрес {page.url}')
                    except Exception:
                        note(f'{name}: кнопку «Футбол» не нашёл, адрес {page.url}')
                    page.wait_for_timeout(10000)
                    for _ in range(6):
                        page.mouse.wheel(0, 1500)
                        page.wait_for_timeout(700)
                    (out / f'{tag}.html').write_text(page.content(), encoding='utf-8')
                    page.screenshot(path=str(out / f'{tag}.png'))
                    set_status(f'{name}: слушаю обновления коэффициентов 40 с…')
                    page.wait_for_timeout(40000)
                    page.screenshot(path=str(out / f'{tag}_after40s.png'))
                    note(f'{name}: готово, адрес {page.url}')
                except Exception as e:
                    note(f'{name}: ошибка {str(e).splitlines()[0][:200]}')
                page.close()
        finally:
            try:
                if browser:
                    browser.close()
            except Exception:
                pass
            (out / 'log.txt').write_text('\n'.join(lines), encoding='utf-8')
            (out / 'requests.json').write_text(json.dumps(reqs, ensure_ascii=False, indent=1), encoding='utf-8')
            (out / 'websockets.json').write_text(json.dumps(wss, ensure_ascii=False, indent=1), encoding='utf-8')
            z = HERE / f'razvedka_kontor_{stamp}.zip'
            with zipfile.ZipFile(z, 'w', zipfile.ZIP_DEFLATED) as zf:
                for f in out.iterdir():
                    zf.write(f, f.name)
            set_status(f'готово — пришлите в чат файл {z.name} (папка Stavki)')
            try:
                subprocess.Popen(['explorer', '/select,', str(z)])
            except Exception:
                pass

    def run(self):
        self.start_browser()
        fails = 0
        t_cycle, n_cycle = time.time(), 0
        while True:
            if STATE.restart_requested:
                self.shutdown_for_update()
            if STATE.razvedka_requested:
                STATE.razvedka_requested = False
                try:
                    self.run_razvedka()
                except Exception as e:
                    add_error('разведка: ' + str(e).splitlines()[0][:150])
                    with STATE.lock:
                        STATE.status['razvedka'] = 'готово с ошибкой — пришлите снимок окна'
            try:
                if time.time() - self.last_events > self.cfg['refresh_events_sec']:
                    self.refresh_events()
                    self.ever_ok = True
                ms = self.pick_batch(self.cfg['batch_matches'])
                if not ms:
                    time.sleep(1)
                    continue
                try:
                    errs, total = self.update_batch(ms)
                except Exception:
                    with STATE.lock:
                        for m in ms:
                            mm = STATE.matches.get(m['id'])
                            if mm:
                                mm['last_update'] = time.time()   # не застревать на одних и тех же матчах
                    raise
                if errs == total:
                    raise RuntimeError('все запросы пакета не удались')
                self.ever_ok = True
                n_cycle += len(ms)
                time.sleep(self.cfg['pause_between_requests'])
                if time.time() - t_cycle > 60:
                    with STATE.lock:
                        STATE.status['cycle_info'] = f'обновлено матчей за минуту: {n_cycle}'
                        STATE.status['last_ok'] = now_str()
                    t_cycle, n_cycle = time.time(), 0
                fails = 0
            except Exception as e:
                fails += 1
                add_error(str(e).splitlines()[0][:200])
                if fails >= 3:                      # подряд — значит, беда не в одном матче
                    time.sleep(min(60, 5 * (fails - 2)))
                if fails >= 3 and not self.ever_ok and self.cfg['headless']:
                    log('в фоновом режиме сайт не отвечает — открываю браузер в обычном окне')
                    self.cfg['headless'] = False
                    fails = 5
                if fails % 5 == 0:
                    log('перезапускаю браузер')
                    try:
                        self.restart_browser()
                    except Exception as e2:
                        add_error('перезапуск браузера: ' + str(e2).splitlines()[0][:150])


def remote_version():
    url = REPO_RAW + 'stavki.py?t=' + str(int(time.time()))
    req = urllib.request.Request(url, headers={'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(req, timeout=20) as r:
        text = r.read().decode('utf-8', 'replace')
    m = re.search(r'^VERSION = "([^"]+)"', text, re.M)
    return m.group(1) if m else None


def vkey(v):
    return tuple(int(x) for x in re.findall(r'\d+', v))


def update_checker():
    """Раз в 10 минут смотрит, есть ли на GitHub версия новее. Если есть — в окне появляется кнопка «Обновить»."""
    while True:
        try:
            rv = remote_version()
            if rv and vkey(rv) > vkey(VERSION):
                with STATE.lock:
                    if STATE.status['update_available'] != rv:
                        log(f'есть новая версия: {rv}')
                    STATE.status['update_available'] = rv
        except Exception as e:
            log(f'проверка обновлений не удалась: {str(e).splitlines()[0][:120]}')
        time.sleep(600)


def load_config():
    p = HERE / 'config.json'
    cfg = dict(DEFAULT_CONFIG)
    if p.exists():
        try:
            cfg.update(json.loads(p.read_text(encoding='utf-8')))
        except Exception as e:
            print('config.json не прочитан, беру настройки по умолчанию:', e)
    else:
        p.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding='utf-8')
    return cfg


def main():
    global MY_BOOKMAKERS
    cfg = load_config()
    MY_BOOKMAKERS = list(cfg.get('my_bookmakers_list') or [])
    con = db_open()
    srv = ThreadingHTTPServer(('127.0.0.1', cfg['port']), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f'http://localhost:{cfg["port"]}'
    log(f'«Ставки», версия {VERSION}. Окно программы: {url}')
    flag = HERE / 'restarting.flag'
    if flag.exists():                 # перезапуск после обновления: окно уже открыто, оно само переподключится
        flag.unlink()
    else:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    threading.Thread(target=update_checker, daemon=True).start()
    Collector(cfg, con).run()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception:
        log('Программа остановилась:\n' + traceback.format_exc())
        input('Нажмите Enter, чтобы закрыть окно')

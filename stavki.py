# -*- coding: utf-8 -*-
"""Ставки v1 — «на что можно поставить прямо сейчас».

Берёт коэффициенты с odds.ru (15 контор, в том числе Pinnacle) через обычный браузер,
считает честную цену по Pinnacle и показывает ставки российских контор, где коэффициент
выше честной цены. Окно программы: http://localhost:8765 — обновляется само.
Ничего не ставит и никуда не входит.
"""
import datetime
import difflib
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

VERSION = "2026.11.21-8"
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
    "direct_poll_sec": 5,
    "paper_stake_rub": 100,       # условная ставка на бумаге; пороги способов — в STRATEGIES
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

# ---------------------------------------------------------------- прямые цены с сайтов контор

# Фонбет и PARI работают на одной платформе: одинаковые коды ставок (проверено разведкой 21.11).
F_1X2 = (921, 922, 923)
F_TOTALS = [(930, 931), (940, 941), (1848, 1849), (1696, 1697), (1727, 1728), (1730, 1731), (1733, 1734),
            (1736, 1737), (1739, 1791), (1793, 1794), (1796, 1797), (1799, 1800), (1802, 1803), (1805, 1806)]
DIRECT_BOOKS = [
    # название как на odds.ru, сайт, адрес линии по умолчанию, scopeMarket
    {'name': 'Фонбет', 'site': 'https://fon.bet/', 'host': 'https://line-vk01-w.bk6bba-resources.ru',
     'host_mark': 'bk6bba-resources', 'scope': 1600},
    {'name': 'PARI', 'site': 'https://pari.ru/', 'host': 'https://line-vk01-w.pb06e2-resources.ru',
     'host_mark': 'pb06e2-resources', 'scope': 2300},
]


def norm_team(t):
    t = (t or '').lower().replace('ё', 'е')
    t = re.sub(r'[^a-zа-я0-9 ]+', ' ', t)
    words = [w for w in t.split() if w not in ('фк', 'fc', 'пфк', 'футбольный', 'клуб', 'ск', 'фс')]
    return ' '.join(words)


def team_sim(a, b):
    a, b = norm_team(a), norm_team(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if (a in b or b in a) and min(len(a), len(b)) >= 4:
        return 0.9
    return difflib.SequenceMatcher(None, a, b).ratio()


def line_of(name):
    m = re.search(r'\(([-+]?\d+(?:\.\d+)?)\)', name or '')
    return float(m.group(1)) if m else None


def chance_rel(odds, fair):
    """шанс по честной цене и «надёжность» = перевес / разброс ставки (чем выше, тем чаще ставки
    такого вида приводят к плюсу на коротком отрезке; расчёт 21.11 на 5+ сезонах)"""
    p = 1.0 / fair if fair else 0.0
    ev = odds * p - 1
    sd = odds * math.sqrt(p * (1 - p)) if 0 < p < 1 else 0
    return p, (ev / sd if sd else 0.0)


# способы отбора на бумаге — записаны заранее и на ходу не меняются (решение владельца 21.11)
STRATEGIES = [
    ('Б', 'перевес от 5%, кф до 4, лучший по надёжности (основной)',
     lambda v: v['ev'] >= 0.05 and v['odds'] <= 4.0, 'rel'),
    ('А', 'перевес от 5%, кф до 4, лучший по перевесу',
     lambda v: v['ev'] >= 0.05 and v['odds'] <= 4.0, 'ev'),
    ('В', 'перевес от 3%, шанс от 55%, лучший по перевесу',
     lambda v: v['ev'] >= 0.03 and v['chance'] >= 0.55 and v['odds'] <= 4.0, 'ev'),
]
CAND_MIN_EV = 0.03          # журнал CLV: все ставки моих контор с перевесом от 3% и кф до 4


def event_of(v):
    """событие = матч + рынок: все линии тотала одного матча — одно событие"""
    return '1x2' if v['market_name'] == '1Х2' else 'total'


def pinnacle_fair(odds_data):
    """Из сохранённых ответов odds.ru по матчу: честные цены Pinnacle.
    Возвращает {('1x2', None): [p1,px,p2], ('total', 2.5): [p_over, p_under]} и цены Pinnacle."""
    out = {}
    for market, (data, ts) in odds_data.items():
        for r in (data.get('rates') or []):
            if not isinstance(r, dict):
                continue
            names = [(o or {}).get('name', '') for o in (r.get('outcomes') or [])]
            pin = next((b for b in (r.get('bookmakers') or []) if isinstance(b, dict) and b.get('id') == PINNACLE_ID), None)
            if not pin:
                continue
            try:
                po = [None] * len(names)
                for o in (pin.get('odds') or []):
                    po[o['outcome']] = float(o['value'])
                if any(v is None or v <= 1 for v in po):
                    continue
            except (ValueError, KeyError, IndexError, TypeError):
                continue
            p = fair_power(po)
            if market == 'match_winner' and len(po) == 3:
                out[('1x2', None)] = (p, po, ts)
            elif market == 'total_points' and len(po) == 2:
                ln = line_of(names[0])
                if ln is not None:
                    out[('total', ln)] = (p, po, ts)
    return out


class DirectFeed:
    """Линия конторы напрямую с её сайта: полный снимок + изменения каждые несколько секунд."""

    def __init__(self, book):
        self.book = book
        self.name = book['name']
        self.page = None
        self.host = book['host']
        self.version = None
        self.sports = {}
        self.events = {}
        self.factors = {}          # id события -> {код: ставка}
        self.touched = {}          # id события -> когда последний раз пришло изменение
        self.last_poll = 0
        self.last_full = 0
        self.last_ok = None
        self.fails = 0
        self.match_map = {}        # id события -> id матча odds.ru или None
        self.match_tried = {}
        self.page_url = ''
        self.last_error = ''

    def start(self, browser):
        self.page = browser.new_page(locale='ru-RU')
        seen = []

        def on_req(r):
            if self.book['host_mark'] in r.url and '/events/' in r.url:
                seen.append(r.url)
        self.page.on('request', on_req)
        self.page.goto(self.book['site'], wait_until='domcontentloaded', timeout=90000)
        self.page.wait_for_timeout(6000)
        self.page_url = self.page.url
        if seen:
            m = re.match(r'(https://[^/]+(?:/ma)?)/events/', seen[0])
            if m:
                self.host = m.group(1)
        log(f'{self.name}: сайт открыт, адрес линии {self.host}')

    def fetch(self, path):
        url = self.host + path
        site = self.book['site'].rstrip('/')
        try:
            r = self.page.context.request.get(url, headers={'Referer': site + '/', 'Origin': site}, timeout=30000)
            status, text = r.status, r.text()
        except Exception as e:
            res = self.page.evaluate(FETCH_JS, url)      # запасной путь — как это делает сам сайт
            status, text = res['status'], res['text']
            if status != 200:
                raise RuntimeError(f'нет ответа ({str(e).splitlines()[0][:80]}; {text[:80]})')
        if status != 200:
            raise RuntimeError(f'ответ {status} с {url.split("/events")[0]}: {text[:80]}')
        return json.loads(text)

    def merge(self, j):
        for sp in (j.get('sports') or []):
            if isinstance(sp, dict) and 'id' in sp:
                self.sports[sp['id']] = sp
        now = time.time()
        for e in (j.get('events') or []):
            if isinstance(e, dict) and 'id' in e:
                self.events[e['id']] = dict(self.events.get(e['id'], {}), **e)
        for c in (j.get('customFactors') or []):
            if not isinstance(c, dict) or 'e' not in c:
                continue
            d = self.factors.setdefault(c['e'], {})
            for f in (c.get('factors') or []):
                if isinstance(f, dict) and 'f' in f:
                    d[f['f']] = f
            self.touched[c['e']] = now
        for b in (j.get('eventBlocks') or []):
            if isinstance(b, dict) and b.get('eventId') in self.events:
                self.events[b['eventId']]['_blocked'] = b.get('state') == 'blocked'
        if j.get('packetVersion'):
            self.version = j['packetVersion']

    def poll(self):
        sc = self.book['scope']
        if self.version is None or time.time() - self.last_full > 900:
            j = self.fetch(f'/events/list?lang=ru&version=0&scopeMarket={sc}')
            n = len(j.get('events') or [])
            if n < 300:
                j2 = self.fetch(f'/events/list?lang=ru&scopeMarket={sc}')
                if len(j2.get('events') or []) > n:
                    j = j2
            self.events, self.factors = {}, {}
            self.merge(j)
            self.last_full = time.time()
            log(f'{self.name}: полная линия — событий {len(self.events)}, футбол до матча: {len(self.football())}')
        else:
            self.merge(self.fetch(f'/events/list?lang=ru&version={self.version}&scopeMarket={sc}'))
        self.last_poll = time.time()
        self.last_ok = time.time()
        self.fails = 0

    def is_football(self, sport_id):
        s, hops = self.sports.get(sport_id), 0
        while s and hops < 6:
            if s.get('id') == 1 or s.get('parentId') == 1:
                return True
            s = self.sports.get(s.get('parentId'))
            hops += 1
        return False

    def football(self):
        now = time.time()
        return [e for e in self.events.values()
                if e.get('level') == 1 and e.get('place') == 'line' and not e.get('_blocked')
                and e.get('startTime', 0) > now + 60 and self.is_football(e.get('sportId'))]

    def odds_of(self, eid):
        fs = self.factors.get(eid, {})
        out = {}
        v = [fs.get(k, {}).get('v') for k in F_1X2]
        if all(isinstance(x, (int, float)) and x > 1 for x in v):
            out[('1x2', None)] = v
        for a, b in F_TOTALS:
            fa, fb = fs.get(a), fs.get(b)
            if fa and fb and isinstance(fa.get('v'), (int, float)) and isinstance(fb.get('v'), (int, float)):
                try:
                    ln = fa.get('p', 0) / 100
                except TypeError:
                    continue
                out[('total', ln)] = [fa['v'], fb['v']]
        return out

    def match_to_oddsru(self, ev, matches):
        eid = ev['id']
        if eid in self.match_map and (self.match_map[eid] or time.time() - self.match_tried.get(eid, 0) < 600):
            return self.match_map[eid]
        best, best_s = None, 0
        for m in matches.values():
            if abs(m['start'] - ev.get('startTime', 0)) > 20 * 60:
                continue
            s1 = team_sim(ev.get('team1'), m.get('home'))
            s2 = team_sim(ev.get('team2'), m.get('away'))
            sc = (s1 + s2) / 2
            if min(s1, s2) >= 0.55 and sc > best_s:
                best, best_s = m['id'], sc
        res = best if best_s >= 0.72 else None
        self.match_map[eid] = res
        self.match_tried[eid] = time.time()
        return res


def settle_one(market, outcome, line, odds, home, away):
    """Прибыль ставки в долях ставки (1 = ставка). Учитывает возврат и «азиатские» линии x.25/x.75."""
    if market == '1x2':
        res = 'П1' if home > away else ('П2' if away > home else 'Х')
        return odds - 1 if outcome == res else -1.0
    goals = home + away
    over = outcome.startswith('Больше')
    frac = round((line * 4) % 4)
    lines = [line - 0.25, line + 0.25] if frac in (1, 3) else [line]
    total = 0.0
    for ln in lines:
        part = 1 / len(lines)
        if goals == ln:
            r = 0.0
        elif (goals > ln) == over:
            r = odds - 1
        else:
            r = -1.0
        total += part * r
    return total


# ---------------------------------------------------------------- состояние

class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.matches = {}        # id -> dict(match info, last_update, markets{})
        self.values = {}         # key -> value row
        self.status = {'started': now_str(), 'events_updated': None, 'errors': [], 'requests': 0,
                       'cycle_info': '', 'last_ok': None, 'version': VERSION, 'update_available': None,
                       'restarting': False, 'avg_request': None, 'razvedka': None, 'feeds': {}}
        self.odds_data = {}      # id матча odds.ru -> {рынок: (ответ, когда)}
        self.direct_values = {}  # прямые цены контор: ключ -> строка
        self.direct_cover = {}   # контора -> матчи odds.ru, по которым есть прямые цены
        self.restart_requested = False
        self.razvedka_requested = False
        self.margins = {}        # (контора, рынок) -> [сумма, число строк]

    def snapshot(self):
        with self.lock:
            now = time.time()
            covered = {(n, mid) for n, f in self.status['feeds'].items() if f.get('last_ok') and now - f['last_ok'] < 90
                       for mid in self.direct_cover.get(n, ())}
            vals = [v for v in self.values.values() if (v['bookmaker'], v['match_id']) not in covered]
            vals += list(self.direct_values.values())
            vals.sort(key=lambda v: -v['ev'])
            rows = []
            for v in vals:
                m = self.matches.get(v['match_id'], {})
                if m and m.get('start', 0) < now + 60:
                    continue
                rows.append(dict(v, age=int(now - v['updated']), held=int(now - v['first_seen']),
                                 match=m.get('title', ''), league=m.get('league', ''),
                                 start=m.get('start_str', ''), start_ts=m.get('start', 0), url=m.get('url', ''),
                                 source=v.get('source', 'odds.ru'),
                                 pin_age=int(now - v['pin_ts']) if v.get('pin_ts') else None,
                                 chance=round(chance_rel(v['odds'], v['fair'])[0], 4),
                                 rel=round(chance_rel(v['odds'], v['fair'])[1], 4)))
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
STATS_DB = None
STATS_STAKE = 100

# ---------------------------------------------------------------- база для учёта (CLV потом)

def db_open():
    con = sqlite3.connect(str(HERE / 'stavki.sqlite3'), check_same_thread=False)
    con.execute('CREATE TABLE IF NOT EXISTS pin (ts REAL, match_id INT, market TEXT, raw TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS value_seen (match_id INT, market TEXT, outcome TEXT, bookmaker TEXT,'
                ' first_seen REAL, last_seen REAL, best_ev REAL, odds_at_best REAL, fair_at_best REAL,'
                ' PRIMARY KEY (match_id, market, outcome, bookmaker))')
    con.execute('CREATE TABLE IF NOT EXISTS matches (match_id INT PRIMARY KEY, title TEXT, league TEXT,'
                ' start_ts REAL, url TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS results (match_id INT PRIMARY KEY, home INT, away INT, ts REAL)')
    # бумага с 21.11 (версия -8): одна ставка на событие (матч + рынок) для каждого способа отбора,
    # в конторе с лучшим кф; цены с сайта конторы и с odds.ru считаются раздельно
    con.execute('CREATE TABLE IF NOT EXISTS paper2 (id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL, match_id INT,'
                ' title TEXT, league TEXT, start_ts REAL, strategy TEXT, event TEXT, src TEXT, bookmaker TEXT,'
                ' market_name TEXT, outcome TEXT, line REAL, odds REAL, fair REAL, ev REAL, rel REAL, pin_age REAL,'
                ' status TEXT DEFAULT "open", profit REAL, closing_fair REAL, clv REAL, settled REAL,'
                ' UNIQUE (match_id, event, strategy, src))')
    # журнал CLV: каждая подходящая ставка каждой моей конторы — по первой увиденной цене
    con.execute('CREATE TABLE IF NOT EXISTS cand (match_id INT, bookmaker TEXT, src TEXT, market_name TEXT,'
                ' outcome TEXT, line REAL, start_ts REAL, first_seen REAL, odds REAL, fair REAL, ev REAL,'
                ' pin_age REAL, closing_fair REAL, clv REAL, done INT DEFAULT 0,'
                ' PRIMARY KEY (match_id, bookmaker, market_name, outcome))')
    con.commit()
    migrate_old_paper(con)
    return con


def pick_for_strategies(rows):
    """rows — строки «ставка в конторе»; возвращает [(способ, строка)]: по одной на событие и источник цены"""
    groups = {}
    for v in rows:
        groups.setdefault((v['match_id'], event_of(v), v['src']), []).append(v)
    out = []
    for vs in groups.values():
        for code, _desc, cond, key in STRATEGIES:
            c = [v for v in vs if cond(v)]
            if c:
                out.append((code, max(c, key=lambda v: (v[key], v['odds']))))
    return out


def migrate_old_paper(con):
    """старые записи (каждая линия × каждая контора) пересчитываются в новую бумагу; старая таблица — в архив"""
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'paper' not in names or 'paper_old' in names:
        return
    rows = []
    for r in con.execute('SELECT created, match_id, title, league, start_ts, bookmaker, source, market_name, outcome,'
                         ' line, odds, fair, ev FROM paper ORDER BY created').fetchall():
        v = dict(zip(['created', 'match_id', 'match', 'league', 'start_ts', 'bookmaker', 'source', 'market_name',
                      'outcome', 'line', 'odds', 'fair', 'ev'], r))
        if not v['fair'] or not v['odds']:
            continue
        v['src'] = 'сайт' if v['source'] == 'сайт' else 'odds.ru'
        v['ev'] = v['odds'] / v['fair'] - 1
        v['chance'], v['rel'] = chance_rel(v['odds'], v['fair'])
        rows.append(v)
    picks = []
    for t in sorted({v['created'] for v in rows}):       # как при живой записи: побеждает первая подходящая цена
        picks += pick_for_strategies([v for v in rows if v['created'] == t])
    for code, v in picks:
        con.execute('INSERT OR IGNORE INTO paper2 (created, match_id, title, league, start_ts, strategy, event, src,'
                    ' bookmaker, market_name, outcome, line, odds, fair, ev, rel, pin_age) VALUES'
                    ' (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (v['created'], v['match_id'], v['match'], v['league'], v['start_ts'], code, event_of(v), v['src'],
                     v['bookmaker'], v['market_name'], v['outcome'], v['line'], v['odds'], v['fair'], v['ev'],
                     v['rel'], None))
    con.execute('ALTER TABLE paper RENAME TO paper_old')
    con.commit()
    log(f'бумажные ставки пересчитаны по новым правилам (старых строк: {len(rows)})')

# ---------------------------------------------------------------- окно программы

PAGE = r"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Ставки — можно ставить сейчас</title>
<style>
*{box-sizing:border-box}
body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#0f1419;color:#e6e6e6}
header{padding:12px 20px;background:#151c24;border-bottom:1px solid #253040;display:flex;gap:18px;align-items:center;flex-wrap:wrap}
h1{font-size:20px;margin:0}
.st{font-size:12px;color:#8696a6}
.bad{color:#ff6b6b}
input{width:56px;background:#0f1419;color:#e6e6e6;border:1px solid #33414f;padding:3px 5px;border-radius:4px}
label{font-size:13px;color:#9fb0c0}
.ubtn{background:#2f7d4f;color:#fff;border:0;padding:7px 14px;border-radius:6px;font-size:14px;cursor:pointer}
.lbtn{background:#24313f;color:#cfd8e3;border:1px solid #33414f;padding:4px 10px;border-radius:6px;font-size:12px;cursor:pointer}
.ver{font-size:12px;color:#5f6e7c}
main{padding:16px 20px}
.cols{display:grid;grid-template-columns:repeat(3,minmax(300px,1fr));gap:16px;align-items:start}
@media(max-width:1000px){.cols{grid-template-columns:1fr}}
.col{background:#131a22;border-radius:10px;border-top:6px solid var(--c);min-height:120px}
.colh{display:flex;justify-content:space-between;align-items:baseline;padding:12px 14px 8px}
.bk{font-size:22px;font-weight:800;color:var(--c)}
.cnt{font-size:13px;color:#9fb0c0}
.feed{font-size:12px;padding:0 14px 10px;color:#8696a6}
.feed.ok{color:#5fd38d}.feed.warn{color:#d8a657}
.card{margin:0 10px 10px;background:#1a232d;border-radius:8px;padding:10px 12px;border-left:4px solid var(--c)}
.card.stale{opacity:.55}
.r1{display:flex;justify-content:space-between;align-items:baseline;gap:10px}
.mh{font-size:15px;font-weight:700}.mh a{color:#cfe1ff;text-decoration:none}
.var{display:grid;grid-template-columns:1fr auto auto;gap:4px 12px;align-items:baseline;padding:7px 0 6px;border-top:1px solid #26313d;margin-top:6px}
.var .bet{font-size:16px}.var.best .bet{font-size:18px}
.star{color:#f2c230;font-size:12px;font-weight:700;margin-right:4px}
.ch{font-size:20px;font-weight:800;color:#fff;text-align:right;white-space:nowrap}
.ch small{font-size:11px;color:#8696a6;font-weight:400;display:block;text-align:right}
.var .ev{font-size:15px;text-align:right}
.var .need{grid-column:1/4;margin-top:0;font-size:12px}
.var:not(.best){opacity:.85}
.bet{font-size:18px;font-weight:700}
.odd{font-size:18px;font-weight:800;color:#fff;margin-left:6px}
.ev{font-size:20px;font-weight:800;color:#5fd38d;white-space:nowrap}
.m{font-size:14px;margin-top:4px}
.m a{color:#cfe1ff;text-decoration:none}
.sm{font-size:12px;color:#8696a6;margin-top:3px}
.need{font-size:13px;margin-top:6px;color:#cfd8e3}
.src{font-size:12px;margin-top:3px}
.src.ok{color:#5fd38d}.src.warn{color:#d8a657}
.empty{padding:6px 14px 16px;color:#7d8b99;font-size:13px}
.pp{background:#131a22;border-radius:10px;padding:12px 16px;margin-bottom:16px;overflow-x:auto}
.pp h2{font-size:16px;margin:0 0 6px}
.big{font-size:15px}
.pos{color:#5fd38d}.neg{color:#ff6b6b}
.pp table td,.pp table th{font-size:12px;padding:3px 14px 3px 6px}
details{margin-top:26px;color:#9fb0c0}
summary{cursor:pointer;font-size:14px}
table{border-collapse:collapse;margin-top:8px}
td,th{padding:4px 16px 4px 8px;border-bottom:1px solid #222c38;font-size:13px;text-align:left}
</style></head><body>
<header><h1>Можно ставить сейчас</h1><span id="upd"></span>
<label>перевес от, % <input id="thr" type="number" step="0.5" value="5"></label>
<label>кф до <input id="mx" type="number" step="0.5" value="4"></label>
<span class="st" id="st">загрузка…</span></header>
<main><div id="paper"></div><div class="cols" id="cols"></div>
<details><summary>Подробнее: работа программы, маржа контор, разведка</summary><div id="more"></div></details></main>
<script>
const PAGE_VERSION='__VERSION__';
const COLORS={'Фонбет':'#e8392f','PARI':'#f2c230','Винлайн':'#ff7a1a'};
function fmt(s){if(s==null)return '—';if(s<60)return s+' с';if(s<3600)return Math.floor(s/60)+' мин';return Math.floor(s/3600)+' ч '+Math.floor(s%3600/60)+' мин'}
function when(ts){const d=new Date(ts*1000),n=new Date();const hm=d.toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit',timeZone:'Europe/Moscow'});
 const dd=d.toLocaleDateString('ru-RU',{timeZone:'Europe/Moscow'}),nd=n.toLocaleDateString('ru-RU',{timeZone:'Europe/Moscow'});
 const left=Math.round((ts*1000-n)/60000);const l=left<60?('через '+left+' мин'):('через '+Math.floor(left/60)+' ч '+left%60+' мин');
 return (dd===nd?'сегодня ':dd.slice(0,5)+' ')+hm+' · '+l}
function betText(v){const t=(v.match||'').split(' — ');
 if(v.market_name==='1Х2'){if(v.outcome==='П1')return 'Победа: '+(t[0]||'хозяева');if(v.outcome==='П2')return 'Победа: '+(t[1]||'гости');return 'Ничья'}
 const m=v.outcome.match(/(Больше|Меньше) \(([\d.]+)\)/);if(m)return (m[1]==='Больше'?'Тотал больше ':'Тотал меньше ')+m[2];return v.market_name+': '+v.outcome}
async function tick(){
 try{
  const r=await fetch('/api/state',{cache:'no-store'});const d=await r.json();const s=d.status;
  if(s.version!==PAGE_VERSION){location.reload();return}
  const u=document.getElementById('upd');
  if(s.restarting)u.innerHTML='<span class="st">Обновляюсь… окно вернётся само примерно через минуту</span>';
  else if(s.update_available)u.innerHTML='<button class="ubtn" onclick="post(\'/api/update\')">Обновить до версии '+s.update_available+'</button>';
  else u.innerHTML='<span class="ver">версия '+s.version+'</span> <button class="lbtn" onclick="post(\'/api/check_update\');this.textContent=\'проверяю…\'">проверить обновления</button>';
  let st='обновлено '+s.now+' · матчей в работе '+s.tracked;
  if(s.errors.length)st+=' · <span class="bad">ошибка: '+s.errors[s.errors.length-1]+'</span>';
  document.getElementById('st').innerHTML=st;
  const thr=parseFloat(document.getElementById('thr').value||0)/100, mx=parseFloat(document.getElementById('mx').value||99);
  const rows=d.values.filter(v=>v.ev>=thr&&v.odds<=mx&&d.mine.includes(v.bookmaker));
  let h='';
  for(const b of d.mine){
   const c=COLORS[b]||'#7fb6ff';const rs=rows.filter(v=>v.bookmaker===b);
   const byM={};for(const v of rs)(byM[v.match_id]=byM[v.match_id]||[]).push(v);
   const cards=Object.values(byM).map(vs=>vs.sort((x,y)=>y.rel-x.rel)).sort((x,y)=>y[0].rel-x[0].rel);
   const f=s.feeds[b];let feed;
   if(f&&f.last_ok&&(Date.now()/1000-f.last_ok)<90)feed='<div class="feed ok">✓ цены прямо с сайта конторы · матчей '+f.events+', сопоставлено '+f.matched+'</div>';
   else feed='<div class="feed warn">цены с odds.ru, могут отставать — перед ставкой сверить на сайте конторы'+(f&&f.error?'<br>прямая линия не работает: '+f.error:'')+'</div>';
   h+='<div class="col" style="--c:'+c+'"><div class="colh"><span class="bk">'+b+'</span><span class="cnt">'+(cards.length?cards.length+' матч.':'')+'</span></div>'+feed;
   if(!cards.length)h+='<div class="empty">Сейчас подходящих ставок нет</div>';
   for(const vs of cards){
    const v0=vs[0];const direct=v0.source==='сайт';
    const age=Math.max(...vs.map(v=>v.age));const pa=vs.map(v=>v.pin_age).filter(x=>x!=null);const pin=pa.length?Math.max(...pa):null;
    const old=age>180||(pin!=null&&pin>180);
    h+='<div class="card'+(old?' stale':'')+'"><div class="mh"><a href="'+v0.url+'bet/" target="_blank">'+v0.match+'</a></div>'
     +'<div class="sm">'+when(v0.start_ts)+' · '+v0.league+'</div>';
    vs.forEach((v,i)=>{
     h+='<div class="var'+(i===0?' best':'')+'"><div>'+(i===0&&vs.length>1?'<span class="star">★ лучший</span>':'')+'<span class="bet">'+betText(v)+'</span><span class="odd">'+v.odds+'</span></div>'
      +'<div class="ch">'+Math.round(v.chance*100)+'%<small>шанс</small></div><div class="ev">+'+(v.ev*100).toFixed(1)+'%</div>'
      +'<div class="need">брать, если кф не ниже <b>'+(v.fair*(1+thr)).toFixed(2)+'</b> <span class="st">(честная цена '+v.fair.toFixed(2)+')</span></div></div>'});
    h+='<div class="src '+(direct?'ok':'warn')+'">'+(direct?'кф с сайта конторы, проверен '+fmt(age)+' назад':'кф с odds.ru, '+fmt(age)+' назад — сверить')+(pin!=null?' · Pinnacle '+fmt(pin)+' назад':'')+'</div></div>'}
   h+='</div>'}
  document.getElementById('cols').innerHTML=h;
  renderPaper(d.paper);
  let m='<p class="st">'+[ 'матчей в работе '+s.tracked+' (обновлены за 5 мин: '+s.fresh+')','список матчей обновлён '+(s.events_updated||'—'),s.cycle_info,(s.avg_request?'ответ odds.ru в среднем '+s.avg_request+' с':'')].filter(x=>x).join(' · ')+'</p>';
  if(s.errors.length)m+='<p class="st">последние ошибки:<br>'+s.errors.join('<br>')+'</p>';
  m+=s.razvedka?'<p class="st">Разведка контор: '+s.razvedka+'</p>':'<p><button class="lbtn" onclick="post(\'/api/razvedka\')">Разведка контор (≈4 мин)</button></p>';
  const bks=Object.keys(d.margins||{}).sort((a,b)=>(d.mine.includes(b)-d.mine.includes(a))||a.localeCompare(b));
  if(bks.length){m+='<table><tr><th>Маржа контор (с запуска программы)</th><th>1Х2</th><th>Тоталы</th></tr>';
   for(const b of bks){const x=d.margins[b];const c=y=>y?y[0]+'% <span class="st">('+y[1]+')</span>':'—';m+='<tr><td>'+(d.mine.includes(b)?'<b>'+b+'</b>':b)+'</td><td>'+c(x['1Х2'])+'</td><td>'+c(x['Тотал'])+'</td></tr>'}
   m+='</table>'}
  document.getElementById('more').innerHTML=m;
 }catch(e){document.getElementById('st').innerHTML='<span class="bad">нет связи с программой: она перезапускается или закрыта (чёрное окно Stavki)</span>'}
}
function sg(x,suf){if(x==null)return '—';return '<span class="'+(x>0?'pos':(x<0?'neg':''))+'">'+(x>0?'+':'')+x+(suf||'')+'</span>'}
function renderPaper(p){
 const el=document.getElementById('paper');if(!p||p.error){el.innerHTML=p&&p.error?'<div class="pp st">бумага: '+p.error+'</div>':'';return}
 const wasOpen=!!(el.querySelector('details')&&el.querySelector('details').open);
 const main=p.strategies.find(x=>x.code==='Б'&&x.src==='сайт');const c0=p.cand.find(x=>x.src==='сайт');
 let h='<div class="pp"><h2>Ставки на бумаге (понарошку, по '+p.stake_rub+' ₽, одна ставка на событие)</h2><div class="big">Основной способ Б (цены с сайта конторы): ставок '+main.n+', рассчитано '+main.done
  +(main.done?' · выиграло '+main.w+' из '+(main.w+main.l)+' ('+main.winpct+'%), возвратов '+main.push+' · итог '+sg(main.profit_rub,' ₽')+' ('+sg(main.roi,'%')+' на ставку)':'')
  +' · CLV '+(main.nclv?sg(main.clv,'%'):'—')+'</div>'
  +'<div class="st">Проверка перевеса (CLV по всем подходящим ставкам с сайта конторы): матчей '+c0.matches+', ставок '+c0.done+(c0.done?' · средний CLV '+sg(c0.clv,'%')+', лучше закрытия в '+c0.pos+'%':'')+'</div>'
  +'<details'+(wasOpen?' open':'')+'><summary class="st">все способы отбора и последние ставки</summary><table><tr><th>Способ</th><th>Цены</th><th>Ставок</th><th>Рассчитано</th><th>Выиграло</th><th>Возвр.</th><th>Итог, ₽</th><th>На ставку</th><th>Ср. кф</th><th>Ожидали</th><th>CLV</th></tr>';
 for(const g of p.strategies){if(!g.n)continue;h+='<tr><td><b>'+g.code+'</b> '+g.desc+'</td><td>'+(g.src==='сайт'?'с сайта конторы':'с odds.ru (не сверено)')+'</td><td>'+g.n+'</td><td>'+g.done+'</td><td>'+(g.w+g.l?g.w+' из '+(g.w+g.l)+' ('+g.winpct+'%)':'—')+'</td><td>'+g.push+'</td><td>'+sg(g.profit_rub)+'</td><td>'+sg(g.roi,'%')+'</td><td>'+(g.odds||'—')+'</td><td>'+sg(g.ev,'%')+'</td><td>'+sg(g.clv,'%')+'</td></tr>'}
 h+='</table><table><tr><th>Проверка перевеса (все подходящие ставки)</th><th>Ставок</th><th>Матчей</th><th>Средний CLV</th><th>Лучше закрытия</th></tr>';
 for(const x of p.cand)h+='<tr><td>'+(x.src==='сайт'?'цены с сайта конторы':'цены с odds.ru (не сверено)')+'</td><td>'+x.done+' <span class="st">(ждут матча: '+x.wait+')</span></td><td>'+x.matches+'</td><td>'+sg(x.clv,'%')+'</td><td>'+(x.pos==null?'—':x.pos+'%')+'</td></tr>';
 h+='</table><table><tr><th>Когда</th><th>Матч</th><th>Ставка</th><th>Контора</th><th>Кф</th><th>Перевес</th><th>Способы</th><th>Итог</th><th>CLV</th></tr>';
 for(const r of p.last){const t=new Date(r.created*1000).toLocaleString('ru-RU',{timeZone:'Europe/Moscow',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
  h+='<tr><td>'+t+'</td><td>'+r.title+'</td><td>'+r.market_name+': '+r.outcome+'</td><td>'+r.bookmaker+(r.src==='сайт'?'':' <span class="st">(odds.ru)</span>')+'</td><td>'+r.odds+'</td><td>+'+(r.ev*100).toFixed(1)+'%</td><td>'+r.strategies+'</td><td>'+(r.status==='open'?'<span class="st">ждём матч</span>':r.status+' '+sg(Math.round(r.profit*p.stake_rub),' ₽'))+'</td><td>'+(r.clv==null?'—':sg(Math.round(r.clv*1000)/10,'%'))+'</td></tr>'}
 el.innerHTML=h+'</table></details></div>';
}
async function post(u){try{await fetch(u,{method:'POST'})}catch(e){}}
tick();setInterval(tick,3000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/api/state'):
            snap = STATE.snapshot()
            try:
                snap['paper'] = paper_stats(STATS_DB, STATS_STAKE)
            except Exception as e:
                snap['paper'] = {'error': str(e)[:120]}
            body = json.dumps(snap, ensure_ascii=False).encode('utf-8')
            ctype = 'application/json; charset=utf-8'
        else:
            body = PAGE.replace('__VERSION__', VERSION).encode('utf-8')
            ctype = 'text/html; charset=utf-8'
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path.startswith('/api/check_update'):
            with STATE.lock:
                STATE.status['check_now'] = True
            body = b'{"ok": true}'
        elif self.path.startswith('/api/razvedka'):
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
        self.feeds = [DirectFeed(b) for b in DIRECT_BOOKS if b['name'] in MY_BOOKMAKERS]

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
        for f in self.feeds:
            try:
                f.start(self.browser)
            except Exception as e:
                add_error(f'{f.name}: сайт не открылся: {str(e).splitlines()[0][:120]}')

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
        if self.con.execute("SELECT 1 FROM paper2 WHERE status='open' AND start_ts < ? LIMIT 1",
                            (now.timestamp() - 3 * 3600,)).fetchone():
            dates = [(now - datetime.timedelta(days=1)).date()] + dates   # дорасчёт вчерашних матчей
        found = {}
        ok_dates = 0
        for d in dates:
            if d > horizon.date():
                continue
            if d < now.date():
                try:
                    data = self.get_json(f'/next-api/sports/events/ru/?sport=football&status=all&date={d.isoformat()}&source=default')
                    for lg in data.get('leagues', []):
                        for ev in lg.get('events', []):
                            if (ev.get('status') or {}).get('name') == 'completed':
                                self.con.execute('INSERT OR REPLACE INTO results VALUES (?,?,?,?)',
                                                 (ev['id'], int(ev['home']['score']), int(ev['away']['score']), time.time()))
                except Exception as e:
                    add_error(f'результаты за {d.isoformat()}: {str(e).splitlines()[0][:100]}')
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
                    if (ev.get('status') or {}).get('name') == 'completed':
                        try:
                            self.con.execute('INSERT OR REPLACE INTO results VALUES (?,?,?,?)',
                                             (ev['id'], int(ev['home']['score']), int(ev['away']['score']), time.time()))
                        except Exception:
                            pass
                        continue
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
                        'home': ev['home']['title'], 'away': ev['away']['title'],
                        'title': f"{ev['home']['title']} — {ev['away']['title']}",
                        'league': f"{lg.get('region', '')}: {lg.get('title', '')}",
                        'start': start.timestamp(), 'start_str': start.strftime('%d.%m %H:%M'),
                    }
            time.sleep(self.cfg['pause_between_requests'])
        if ok_dates == 0:
            raise RuntimeError('список матчей не получен ни за один день')
        self.con.commit()
        self.settle_paper()
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
            for mid in [mid for mid in STATE.odds_data if mid not in found]:
                STATE.odds_data.pop(mid)
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

    def record_paper(self):
        now = time.time()
        rows = []
        for v in STATE.snapshot()['values']:
            if v['bookmaker'] not in MY_BOOKMAKERS or v['ev'] <= 0:
                continue
            if not v.get('start_ts') or v['start_ts'] < now + 60:
                continue
            v = dict(v, src='сайт' if v.get('source') == 'сайт' else 'odds.ru')
            v['line'] = line_of(v['outcome']) if event_of(v) == 'total' else None
            if event_of(v) == 'total' and v['line'] is None:
                continue
            rows.append(v)
        cur = self.con.cursor()
        added = 0
        try:
            for code, v in pick_for_strategies(rows):
                cur.execute('INSERT OR IGNORE INTO paper2 (created, match_id, title, league, start_ts, strategy, event,'
                            ' src, bookmaker, market_name, outcome, line, odds, fair, ev, rel, pin_age) VALUES'
                            ' (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                            (now, v['match_id'], v['match'], v['league'], v['start_ts'], code, event_of(v), v['src'],
                             v['bookmaker'], v['market_name'], v['outcome'], v['line'], v['odds'], v['fair'],
                             v['ev'], v['rel'], v.get('pin_age')))
                added += cur.rowcount
            for v in rows:
                if v['ev'] >= CAND_MIN_EV and v['odds'] <= 4.0:
                    cur.execute('INSERT OR IGNORE INTO cand (match_id, bookmaker, src, market_name, outcome, line,'
                                ' start_ts, first_seen, odds, fair, ev, pin_age) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                                (v['match_id'], v['bookmaker'], v['src'], v['market_name'], v['outcome'], v['line'],
                                 v['start_ts'], now, v['odds'], v['fair'], v['ev'], v.get('pin_age')))
        except Exception as e:
            add_error('бумажная ставка: ' + str(e)[:100])
        self.con.commit()
        if added:
            log(f'бумажных ставок записано: {added}')

    def closing_fair(self, match_id, market, outcome, line, start_ts):
        mk = 'match_winner' if market == '1x2' else 'total_points'
        row = self.con.execute('SELECT raw FROM pin WHERE match_id=? AND market=? AND ts<=? ORDER BY ts DESC LIMIT 1',
                               (match_id, mk, start_ts)).fetchone()
        if not row:
            return None
        try:
            for names, odds in json.loads(row[0]):
                if outcome in names:
                    po = [float(x) for x in odds]
                    p = fair_power(po)
                    return round(1 / p[names.index(outcome)], 3)
        except Exception:
            return None
        return None

    def settle_paper(self):
        rows = self.con.execute("SELECT p.id, p.event, p.outcome, p.line, p.odds, p.match_id, p.start_ts, r.home, r.away"
                                " FROM paper2 p JOIN results r ON r.match_id = p.match_id WHERE p.status='open'").fetchall()
        n = 0
        for pid, event, outcome, line, odds, mid, start_ts, home, away in rows:
            pr = settle_one(event, outcome, line, odds, home, away)
            st = 'выигрыш' if pr > 0 else ('проигрыш' if pr < 0 else 'возврат')
            cf = self.closing_fair(mid, event, outcome, line, start_ts)
            clv = (odds / cf - 1) if cf else None
            self.con.execute('UPDATE paper2 SET status=?, profit=?, closing_fair=?, clv=?, settled=? WHERE id=?',
                             (st, pr, cf, clv, time.time(), pid))
            n += 1
        # журнал CLV: после начала матча последняя цена Pinnacle до старта уже известна
        for mid, bk, mname, outcome, line, start_ts, odds in self.con.execute(
                'SELECT match_id, bookmaker, market_name, outcome, line, start_ts, odds FROM cand'
                ' WHERE done=0 AND start_ts < ?', (time.time() - 120,)).fetchall():
            cf = self.closing_fair(mid, '1x2' if mname == '1Х2' else 'total', outcome, line, start_ts)
            self.con.execute('UPDATE cand SET closing_fair=?, clv=?, done=1 WHERE match_id=? AND bookmaker=?'
                             ' AND market_name=? AND outcome=?',
                             (cf, (odds / cf - 1) if cf else None, mid, bk, mname, outcome))
        self.con.commit()
        if n:
            log(f'рассчитано бумажных ставок: {n}')

    def poll_feeds(self):
        now = time.time()
        for f in self.feeds:
            if f.page is None or now - f.last_poll < self.cfg.get('direct_poll_sec', 5):
                continue
            try:
                f.poll()
            except Exception as e:
                f.fails += 1
                f.last_poll = time.time()
                f.last_error = str(e).splitlines()[0][:160]
                with STATE.lock:
                    STATE.status['feeds'].setdefault(f.name, {}).update(error=f.last_error, fails=f.fails,
                                                                        page_url=f.page_url, host=f.host)
                if f.fails in (1, 5) or f.fails % 20 == 0:
                    add_error(f'{f.name} (прямая линия): {str(e).splitlines()[0][:150]}')
                if f.fails % 10 == 0:
                    f.version = None          # начать заново с полного снимка
                continue
            self.direct_values_for(f)

    def direct_values_for(self, f):
        now = time.time()
        with STATE.lock:
            matches = dict(STATE.matches)
            odds_data = {k: dict(v) for k, v in STATE.odds_data.items()}
        new, matched, urgent, cover = {}, 0, [], set()
        evs = f.football()
        for ev in evs:
            mid = f.match_to_oddsru(ev, matches)
            if not mid:
                continue
            matched += 1
            cover.add(mid)
            fair = pinnacle_fair(odds_data.get(mid, {}))
            if not fair:
                continue
            for key, bo in f.odds_of(ev['id']).items():
                if key not in fair:
                    continue
                p, po, pts = fair[key]
                if len(bo) != len(p):
                    continue
                for i, odd in enumerate(bo):
                    ev_ = odd * p[i] - 1
                    if ev_ <= 0:
                        continue
                    if key[0] == '1x2':
                        outcome, market_name = ['П1', 'Х', 'П2'][i], '1Х2'
                    else:
                        ln = ('%g' % key[1])
                        outcome, market_name = (f'Больше ({ln})' if i == 0 else f'Меньше ({ln})'), 'Тотал'
                    k = ('direct', f.name, mid, market_name, outcome)
                    new[k] = {'bookmaker': f.name, 'match_id': mid, 'market': key[0], 'market_name': market_name,
                              'outcome': outcome, 'odds': odd, 'fair': round(1 / p[i], 3), 'pin_odds': po[i],
                              'ev': ev_, 'source': 'сайт', 'pin_ts': pts, 'odds_ts': f.touched.get(ev['id'], f.last_full)}
                    if now - pts > 60 and ev_ >= 0.03:
                        urgent.append(mid)
        with STATE.lock:
            for k in [k for k in STATE.direct_values if k[1] == f.name and k not in new]:
                STATE.direct_values.pop(k)
            for k, v in new.items():
                old = STATE.direct_values.get(k)
                v['first_seen'] = old['first_seen'] if old else now
                v['updated'] = f.last_ok or now        # цена подтверждена последним опросом сайта
                STATE.direct_values[k] = v
            for mid in urgent:                     # цену Pinnacle по таким матчам обновить первой очередью
                mm = STATE.matches.get(mid)
                if mm:
                    mm['last_update'] = 0
            STATE.direct_cover[f.name] = cover
            STATE.status['feeds'][f.name] = {'last_ok': f.last_ok, 'events': len(evs), 'matched': matched,
                                             'host': f.host, 'error': '', 'fails': 0}

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
            od = STATE.odds_data.setdefault(mid, {})
            for market, data in datas.items():
                od[market] = (data, now)
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
                self.poll_feeds()
                self.record_paper()
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


def paper_stats(con, stake_rub):
    def agg(where, args=()):
        r = con.execute('SELECT COUNT(*), SUM(status!="open"), SUM(status="выигрыш"), SUM(status="проигрыш"),'
                        ' SUM(status="возврат"), SUM(COALESCE(profit,0)), AVG(ev), AVG(clv), COUNT(clv), AVG(odds)'
                        ' FROM paper2 WHERE ' + where, args).fetchone()
        n, done, w, l, push, prof, ev, clv, nclv, odds = r
        done, w, l = done or 0, w or 0, l or 0
        return {'n': n or 0, 'done': done, 'w': w, 'l': l, 'push': push or 0,
                'winpct': round(100 * w / (w + l)) if w + l else None,
                'profit_rub': round((prof or 0) * stake_rub),
                'roi': round(100 * (prof or 0) / done, 1) if done else None,
                'ev': round(100 * ev, 1) if ev is not None else None,
                'odds': round(odds, 2) if odds else None,
                'clv': round(100 * clv, 1) if clv is not None else None, 'nclv': nclv or 0}
    out = {'stake_rub': stake_rub, 'strategies': [], 'cand': [], 'last': []}
    for code, desc, _c, _k in STRATEGIES:
        for src in ('сайт', 'odds.ru'):
            out['strategies'].append(dict(agg('strategy=? AND src=?', (code, src)), code=code, desc=desc, src=src))
    for src in ('сайт', 'odds.ru'):
        n, nd, clv, pos, nm = con.execute('SELECT SUM(done=0), COUNT(clv), AVG(clv), AVG(clv>0),'
                                          ' COUNT(DISTINCT CASE WHEN clv IS NOT NULL THEN match_id END)'
                                          ' FROM cand WHERE src=?', (src,)).fetchone()
        out['cand'].append({'src': src, 'wait': n or 0, 'done': nd or 0, 'matches': nm or 0,
                            'clv': round(100 * clv, 1) if clv is not None else None,
                            'pos': round(100 * pos) if pos is not None else None})
    for r in con.execute('SELECT MAX(created), title, start_ts, bookmaker, src, market_name, outcome, odds, ev,'
                         ' status, profit, clv, GROUP_CONCAT(strategy, ", ") FROM paper2'
                         ' GROUP BY match_id, bookmaker, src, market_name, outcome, odds'
                         ' ORDER BY MAX(created) DESC LIMIT 30').fetchall():
        out['last'].append(dict(zip(['created', 'title', 'start_ts', 'bookmaker', 'src', 'market_name', 'outcome',
                                     'odds', 'ev', 'status', 'profit', 'clv', 'strategies'], r)))
    return out


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
        for _ in range(180):              # раз в 3 минуты или сразу по кнопке
            if STATE.status.get('check_now'):
                STATE.status['check_now'] = False
                break
            time.sleep(1)


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
    global MY_BOOKMAKERS, STATS_DB, STATS_STAKE
    cfg = load_config()
    MY_BOOKMAKERS = list(cfg.get('my_bookmakers_list') or [])
    con = db_open()
    STATS_DB = sqlite3.connect(str(HERE / 'stavki.sqlite3'), check_same_thread=False)
    STATS_STAKE = cfg.get('paper_stake_rub', 100)
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

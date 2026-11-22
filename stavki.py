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
import urllib.parse
import urllib.request
import sqlite3
import subprocess
import gzip
import io
import collections
import struct
import zipfile
import zlib
import os
import base64
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = "2026.11.21-87"
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
    "my_bookmakers_list": ["Фонбет", "PARI", "Винлайн"],   # конторы, где есть счёт (выбор владельца 21.11)
    "refresh_events_sec": 120,
    "headless": True,
    "telegram_token": "",         # заполняется кнопкой «Подключить Telegram» в окне
    "telegram_chat_id": "",
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


def values_from_rates(data, pinnacle_id=PINNACLE_ID, fair_ext=None, market=None):
    """Из ответа odds.ru (data) делает список: исход × контора с перевесом над честной ценой.
    Если Pinnacle в ответе нет — берётся честная цена с сайта Pinnacle (fair_ext)."""
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
        if pin:
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
        else:
            key = None
            if market == 'match_winner' and outcomes == ['П1', 'Х', 'П2']:
                key = ('1x2', None)
            elif market == 'total_points' and len(outcomes) == 2 and outcomes[0].startswith('Больше'):
                ln = line_of(outcomes[0])
                key = ('total', ln) if ln is not None else None
            if not fair_ext or key not in fair_ext:
                continue
            p, po, pin_ts = fair_ext[key]
            if key[0] == 'total':
                adj = [true_ev(fair_ext, 'total', key[1], i, 2.0) for i in (0, 1)]
                if any(a is None for a in adj):
                    continue
                adj_pw = [a[1] for a in adj]
                adj_pp = [a[2] for a in adj]
            else:
                adj_pw, adj_pp = None, None
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
                if not pin and adj_pw is not None:
                    pw, pu = adj_pw[i], adj_pp[i]
                    if pw <= 0:
                        continue
                    out.append({
                        'outcome': outcomes[i], 'bookmaker': names.get(b['id'], str(b['id'])), 'bk_id': b['id'],
                        'odds': odd, 'fair': round((1 - pu) / pw, 3), 'pin_odds': po[i],
                        'ev': odd * pw + pu - 1, 'p_win': pw, 'p_push': pu, 'pin_ts': pin_ts})
                    continue
                out.append({
                    'outcome': outcomes[i], 'bookmaker': names.get(b['id'], str(b['id'])), 'bk_id': b['id'],
                    'odds': odd, 'fair': round(1 / p[i], 3), 'pin_odds': po[i],
                    'ev': odd * p[i] - 1,
                    **({'pin_ts': pin_ts} if not pin else {}),
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
# пары кодов «больше/меньше» и «фора 1/фора 2» из каталога Фонбета (factorsCatalog/tables, разведка 21.11);
# линия = p/100 у первого кода (у форы — фора первой команды). Подсобытия «1-й тайм» и «угловые» — те же коды.
F_TOTALS = [(930, 931), (940, 941), (1848, 1849), (1696, 1697), (1727, 1728), (1730, 1731), (1733, 1734), (1736, 1737), (1739, 1791), (1793, 1794), (1796, 1797), (1799, 1800), (1802, 1803), (1805, 1806)]
F_AH = [(1851, 1852), (910, 912), (927, 928), (937, 938), (989, 991), (1569, 1572), (1672, 1675), (1677, 1678), (1680, 1681), (1683, 1684), (1686, 1687), (1689, 1690), (1692, 1718), (1723, 1724), (1845, 1846)]
F_TT1 = [(974, 976), (1809, 1810), (1812, 1813), (1815, 1816), (1818, 1819), (1821, 1822), (1824, 1825), (1827, 1828), (1830, 1831), (2203, 2204)]
F_TT2 = [(978, 980), (1854, 1871), (1873, 1874), (1880, 1881), (1883, 1884), (1886, 1887), (1893, 1894), (1896, 1897), (1899, 1900), (2209, 2210)]
F_MATCH_ODDS = (921, 922, 923, 924, 1571, 925)   # П1 Х П2 1Х 12 Х2 (каталог Фонбета, таблица «Исходы»)
FB_PARTS = {'1-й тайм': 'h1_', 'угловые': 'c_'}
MARKET_LABEL = {'1x2': '1Х2', 'total': 'Тотал', 'ah': 'Фора', 'tt1': 'Инд. тотал хозяев', 'tt2': 'Инд. тотал гостей'}
PART_LABEL = {'': '', 'h1_': '1-й тайм: ', 'c_': 'Угловые: '}
SETTLEABLE = {'1x2', 'total', 'ah', 'tt1', 'tt2'}     # рассчитываются по счёту матча → идут на бумагу


def split_fam(fam):
    for pre in ('h1_', 'c_'):
        if fam.startswith(pre):
            return pre, fam[len(pre):]
    return '', fam


def market_label(fam):
    pre, base = split_fam(fam)
    return PART_LABEL[pre] + MARKET_LABEL.get(base, base)


def fmt_ln(x):
    return '%+g' % x if x else '0'


def outcome_names(fam, line):
    """названия исходов по порядку цен: одинаковые у Pinnacle, Фонбета и в базе (по ним ищется цена закрытия)"""
    base = split_fam(fam)[1]
    if base == '1x2':
        return ['П1', 'Х', 'П2']
    if base == 'ah':
        return [f'Ф1 ({fmt_ln(line)})', f'Ф2 ({fmt_ln(-line)})']
    ln = '%g' % line
    return [f'Больше ({ln})', f'Меньше ({ln})']


def bet_info(v):
    """(ставка как на сайте конторы, где искать): «Тотал 3 Больше», «Ф1 (−1.5) · Мельбурн»; «Угловые → Инд. тоталы»"""
    t = (v.get('match') or '').split(' — ')
    home, away = t[0], t[-1]
    pre, base = split_fam(event_of(v))
    out = v.get('outcome', '')
    ln = line_of(out)
    lns = '%g' % ln if ln is not None else ''
    bm = 'Б' if out.startswith('Больше') else 'М'       # владелец 21.11: «просто Б или М»
    if base == '1x2':
        bet, sec = {'П1': 'П1 · ' + home, 'Х': 'Х · ничья', 'П2': 'П2 · ' + away}.get(out, out), 'Исходы'
    elif base == 'ah':
        side = out[:2]
        bet, sec = f"{side} ({fmt_ln(ln)}) · {home if side == 'Ф1' else away}", 'Форы'
    elif base in ('tt1', 'tt2'):
        bet, sec = f"{home if base == 'tt1' else away} · {bm} {lns}", 'Инд. тоталы'   # «ИНД. ТОТАЛ» — в пометке
    else:
        bet, sec = f'{bm} {lns}', 'Тоталы'
    where = {'': '', 'h1_': '1-й тайм → ', 'c_': 'Угловые → '}[pre] + sec
    return bet, where


def bet_kind(fam):
    """крупная пометка над ставкой — сразу видно, что это: «ГОЛЫ · ТОТАЛ», «1-Й ТАЙМ · ИСХОД», «УГЛОВЫЕ · ФОРА»"""
    pre, base = split_fam(fam)
    goals = pre != 'c_'
    kind = {'1x2': 'ИСХОД', 'ah': 'ФОРА', 'total': 'ТОТАЛ ГОЛОВ' if goals else 'ТОТАЛ',
            'tt1': 'ИНД. ТОТАЛ ГОЛОВ' if goals else 'ИНД. ТОТАЛ',
            'tt2': 'ИНД. ТОТАЛ ГОЛОВ' if goals else 'ИНД. ТОТАЛ'}.get(base, base.upper())
    part = {'': 'МАТЧ', 'h1_': '1-Й ТАЙМ', 'c_': 'УГЛОВЫЕ'}[pre]
    return f'{part} · {kind}', {'': 'm', 'h1_': 'h1', 'c_': 'c'}[pre]


def bet_view(fam, outcome):
    """(раздел окна, к какой команде ставка h/a/'' , заголовок рынка) — для карточек по разделам (владелец 21.11)"""
    pre, base = split_fam(fam)
    o = outcome or ''
    side = ''
    if base == '1x2':
        side = {'П1': 'h', 'П2': 'a'}.get(o, '')
    elif base == 'ah':
        side = 'h' if o.startswith('Ф1') else ('a' if o.startswith('Ф2') else '')
    elif base in ('tt1', 'tt2'):
        side = 'h' if base == 'tt1' else 'a'
    title = {'': {'1x2': 'Исход матча', 'total': 'Тотал голов', 'ah': 'Фора', 'tt1': 'Инд. тотал', 'tt2': 'Инд. тотал'},
             'h1_': {'1x2': 'Исход 1-го тайма', 'total': 'Тотал 1-го тайма', 'ah': 'Фора 1-го тайма',
                     'tt1': 'Инд. тотал 1-го тайма', 'tt2': 'Инд. тотал 1-го тайма'},
             'c_': {'1x2': 'Исход по угловым', 'total': 'Тотал угловых', 'ah': 'Фора по угловым',
                    'tt1': 'Инд. тотал угловых', 'tt2': 'Инд. тотал угловых'}}.get(pre, {}).get(base, market_label(fam))
    sec = {'': 'm', 'h1_': 'h1', 'c_': 'c'}.get(pre, 'm')
    order = ['1x2', 'total', 'ah', 'tt1', 'tt2'].index(base) if base in ('1x2', 'total', 'ah', 'tt1', 'tt2') else 9
    return sec, side, title, order


def db_market(fam):
    return {'1x2': 'match_winner', 'total': 'total_points'}.get(fam, fam)


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


# -84 (пункт 3, Совет 22.11: «Зенит-2» ⊃ «Зенит» давало 0.9): вторая команда, дубль, молодёжь — разные команды.
# Пометку «женщины» здесь не сравниваем: у odds.ru в названии её нет, пол проверяется по турниру (is_women).
TEAM_MARK = {'2', '3', 'ii', 'iii', 'b', 'б', 'мол', 'молодежь', 'молодежная', 'дубль', 'рез', 'резерв', 'reserves',
             'res', 'u17', 'u18', 'u19', 'u20', 'u21', 'u22', 'u23', 'youth', 'jong'}


def team_marks(t):
    return {w for w in t.split() if w in TEAM_MARK}


def team_sim(a, b):
    a, b = norm_team(a), norm_team(b)
    if not a or not b:
        return 0.0
    if team_marks(a) != team_marks(b):
        return 0.0
    if a == b:
        return 1.0
    if (a in b or b in a) and min(len(a), len(b)) >= 4:
        return 0.9
    return difflib.SequenceMatcher(None, a, b).ratio()


def line_of(name):
    m = re.search(r'\(([-+]?\d+(?:\.\d+)?)\)', name or '')
    return float(m.group(1)) if m else None


def win_push(fair, fam, line, side):
    """шанс выигрыша и возврата для линии семейства fam по честным ценам Pinnacle (fair: ключ → (p, po, ts)).
    Половинные линии (x.5) — прямо из цены; целые — по соседним половинным: возврат = их разница.
    side: 0 — больше / фора хозяев, 1 — меньше / фора гостей. None — нет нужных соседних линий."""
    base = split_fam(fam)[1]

    def p_first(l):                          # шанс первого исхода (больше / хозяева) на половинной линии
        d = fair.get((fam, round(l, 2)))
        return d[0][0] if d else None
    if round(line * 2) % 2 == 1:              # половинная линия: 2.5, -0.5 (нет возврата)
        p1 = p_first(line)
        if p1 is None:
            return None
        return (p1 if side == 0 else 1 - p1), 0.0
    if base == 'ah':                          # фора хозяев h: хозяева выигрывают при разнице > −h
        hi, lo = p_first(line + 0.5), p_first(line - 0.5)   # хозяева покрывают h+0.5 и h−0.5
        if hi is None or lo is None:
            return None
        push = max(0.0, hi - lo)
        return (lo, push) if side == 0 else (1 - hi, push)
    hi, lo = p_first(line - 0.5), p_first(line + 0.5)       # больше L−0.5 и больше L+0.5
    if hi is None or lo is None:
        return None
    push = max(0.0, hi - lo)
    return (lo, push) if side == 0 else (1 - hi, push)


def true_ev(fair, fam, line, side, odds):
    """перевес ставки на линию с возможным возвратом; четвертная линия = половина на соседние.
    Возвращает (перевес, шанс выигрыша, шанс возврата) или None."""
    if split_fam(fam)[1] == '1x2' or line is None:
        d = fair.get((fam, None))
        if not d:
            return None
        p = d[0][side]
        return odds * p - 1, p, 0.0
    frac = round((abs(line) * 4) % 2)
    parts = [line - 0.25, line + 0.25] if frac == 1 else [line]
    ev = pw = pp = 0.0
    for l in parts:
        r = win_push(fair, fam, l, side)
        if r is None:
            return None
        w, u = r
        ev += (w * odds + u - 1) / len(parts)
        pw += w / len(parts)
        pp += u / len(parts)
    return ev, pw, pp


def chance_rel(odds, fair, p_win=None, p_push=0.0):
    """шанс по честной цене и «надёжность» = перевес / разброс ставки (чем выше, тем чаще ставки
    такого вида приводят к плюсу на коротком отрезке; расчёт 21.11 на 5+ сезонах)"""
    if p_win is None:
        p = 1.0 / fair if fair else 0.0
        ev = odds * p - 1
        sd = odds * math.sqrt(p * (1 - p)) if 0 < p < 1 else 0
        return p, (ev / sd if sd else 0.0)
    p, u = p_win, p_push or 0.0                 # с возвратом: исходы +(кф−1) / 0 / −1
    ev = p * odds + u - 1
    var = p * (odds - 1) ** 2 + (1 - p - u) * 1.0 - ev ** 2
    return p, (ev / math.sqrt(var) if var > 0 else 0.0)


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


EVENT_GROUP = {'ah': '1x2'}        # фора и исход — одна ставка по сути (Ф1 −0.5 = П1, Ф2 +0.5 = Х2)


def event_group(fam):
    pre, base = split_fam(fam)
    return pre + EVENT_GROUP.get(base, base)


def event_of(v):
    """семейство рынка строки: 1x2, total, ah, tt1, tt2 (с приставкой h1_/c_)"""
    m = v.get('market')
    if m in ('match_winner', 'total_points'):
        return '1x2' if m == 'match_winner' else 'total'
    if m:
        return m
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


# ---------------------------------------------------------------- Pinnacle прямо с сайта (с 21.11: на odds.ru его больше нет)

PIN_API = 'https://guest.api.arcadia.pinnacle.com/0.1'
PIN_SITE = 'https://www.pinnacle.com/en/soccer/matchups/'
PIN_PUBLIC_KEY = 'CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R'   # открытый ключ, который сайт сам шлёт гостям (разведка 21.11)
EN_DROP = {'fc', 'cf', 'sc', 'ac', 'afc', 'cd', 'sd', 'ud', 'fk', 'sk', 'club', 'de', 'the', 'calcio', 'football',
           'futbol', 'clube', 'cp', 'sv', 'vfb', 'vfl', 'tsg', 'bk', 'if', 'ik', 'aik', 'ca', 'cs', 'as', 'ss', 'us',
           'rc', 'rcd', 'og', 'nk', 'hnk', 'fsv', 'spvgg', 'balompie', 'real', '1', '1913', '1899', 's', 'r', 'l'}
EN_ALIAS = {'internazionale': 'inter', 'utd': 'united', 'st': 'saint', 'munchen': 'munich', 'monchengladbach': 'gladbach',
            'koln': 'cologne', 'psg': 'paris', 'man': 'manchester', 'brom': 'bromwich', 'wolves': 'wolverhampton',
            'peterboro': 'peterborough', 'hearts': 'heart', 'nottm': 'nottingham', 'nott': 'nottingham',
            'spurs': 'tottenham', 'qpr': 'queens', 'sheff': 'sheffield', 'weds': 'wednesday', 'mgladbach': 'gladbach'}
EN_MARK = {'women', 'w', 'u17', 'u18', 'u19', 'u20', 'u21', 'u23', 'ii', 'b', 'reserves', 'res', 'youth', 'jong',
           'castilla', 'atletic', 'reserve', 'academy', 'u22'}
EN_COMMON = {'united', 'city', 'town', 'county', 'athletic', 'atletico', 'sporting', 'olympique', 'racing', 'dynamo',
             'dinamo', 'inter', 'saint', 'san', 'santa', 'union', 'rovers', 'wanderers', 'albion', 'deportivo', 'young',
             'boys', 'new', 'north', 'south', 'west', 'east', 'central', 'la', 'el', 'los', 'del', 'royal'}


def pin_interval(start_ts, now):
    left = start_ts - now
    return 60 if left < 3 * 3600 else 180 if left < 12 * 3600 else 600


def pin_fresh(start_ts, ts, now):
    """цена Pinnacle годится, пока она не старше двух кругов опроса своей лиги (минимум 3 мин)"""
    return now - ts <= max(180, 2 * pin_interval(start_ts, now))


def am_to_dec(price):
    """американский кф Pinnacle → десятичный"""
    price = float(price)
    return round(1 + (price / 100 if price > 0 else 100 / -price), 4)


def en_tokens(name):
    import unicodedata
    t = (name or '').lower().replace('ß', 'ss').replace("'", '').replace('-', ' ')
    t = ''.join(ch for ch in unicodedata.normalize('NFKD', t) if not unicodedata.combining(ch))
    t = re.sub(r'\(([^)]*)\)', r' \1 ', t)
    t = re.sub(r'[^a-z0-9 ]+', ' ', t)
    words = [EN_ALIAS.get(w, w) for w in t.split()]
    marks = {w for w in words if w in EN_MARK}
    core = [w for w in words if w not in EN_DROP and w not in EN_MARK]
    return core or words, marks


def is_women(league):
    """женский турнир: у odds.ru «Женская …»/«…, женщины», у Pinnacle «… Women»"""
    return bool(re.search(r'женск|женщ|women', league or '', re.I))


def no_w(name):
    """название без пометки «женщины» (W, Women, -w) — для сравнения внутри уже проверенного женского турнира"""
    return re.sub(r'(?:^|[\s(\-])(?:w|women)(?:\)|$|(?=[\s\-]))', ' ', name or '', flags=re.I).strip()


def en_sim(a, b):
    (ca, ma), (cb, mb) = en_tokens(a), en_tokens(b)
    if ma != mb:
        return 0.0
    sa, sb = ' '.join(ca), ' '.join(cb)
    r = difflib.SequenceMatcher(None, sa, sb).ratio()
    if set(ca) <= set(cb) or set(cb) <= set(ca):
        r = max(r, 0.9)
    elif (set(ca) & set(cb)) - EN_COMMON:
        r = max(r, 0.75)
    return r


def en_names_any(home_en, away_en, url):
    """английские названия для поиска страницы матча. Нет home_en (матч записан до -11 или уже начался и пропал
    из списка odds.ru) — берём обе части адреса odds.ru без ориентации: для ссылки хозяева/гости не важны,
    find_fotmob сверяет оба порядка (22.11: 14 из 54 матчей не искались вовсе)."""
    if home_en and away_en:
        return home_en, away_en
    m = re.search(r'/match/([^/]+)-vs-([^/]+)/\d+-\d+/?$', url or '')
    return (m.group(1), m.group(2)) if m else (None, None)


def en_names_of(ev):
    """английские названия команд odds.ru — из адреса матча: /match/<a>-vs-<b>/<idA>-<idB>/ (порядок по номерам)"""
    m = re.search(r'/match/([^/]+)/(\d+)-(\d+)/?$', ev.get('url') or '')
    if not m or '-vs-' not in m.group(1):
        return None, None
    a, b = m.group(1).split('-vs-', 1)
    ida, idb = int(m.group(2)), int(m.group(3))
    hid, aid = (ev.get('home') or {}).get('id'), (ev.get('away') or {}).get('id')
    if (hid, aid) == (ida, idb):
        return a, b
    if (hid, aid) == (idb, ida):
        return b, a
    return None, None


class PinnacleFeed:
    """Цены Pinnacle с его сайта (через VPN владельца): лиги по очереди, ближайшие матчи — чаще."""
    name = 'Pinnacle'

    def __init__(self):
        self.page = None
        self.headers = {}
        self.leagues = {}           # id -> {'name', 'count', 'last', 'next_start'}
        self.leagues_ts = 0
        self.regular = {}           # id матча Pinnacle -> {'home','away','start','league'}
        self.special = {}           # угловые/карточки: id -> {'parent','units'}
        self.markets = {}           # id матча Pinnacle -> [рынки как есть] (для следующих частей)
        self.match_map = {}         # id Pinnacle -> (id odds.ru, перевёрнуто ли) или None
        self.match_tried = {}
        self.fair = {}              # id odds.ru -> {ключ: (p, цены, когда)}
        self.fair_parts = {}        # id odds.ru -> {лига: {ключ: ...}} (угловые приходят из отдельной лиги)
        self.pin_written = {}       # id odds.ru -> когда последний раз записали в базу
        self.fair_league = {}       # id odds.ru -> лига Pinnacle
        self.taken = {}             # id odds.ru -> id Pinnacle (один матч odds.ru — один матч Pinnacle)
        self.removed = []           # id odds.ru, у которых рынок закрылся
        self.last_req = 0
        self.last_ok = None
        self.fails = 0
        self.last_error = ''
        self.page_url = ''
        self.host = PIN_API
        self.lock = threading.Lock()
        self.mode = None            # 'thread' — свой поток напрямую; 'browser' — через окно браузера
        self.pending = set()        # id odds.ru с новой ценой — забирает основной цикл
        self.thread = None

    def http_get(self, path):
        import gzip
        req = urllib.request.Request(PIN_API + path, headers=dict(
            self.headers, **{'Accept-Encoding': 'gzip', 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                             'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0 Safari/537.36'}))
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read()
            if r.headers.get('Content-Encoding') == 'gzip':
                body = gzip.decompress(body)
        j = json.loads(body.decode('utf-8'))
        if not isinstance(j, list):
            raise RuntimeError(f'Pinnacle прислал не то на {path[:60]}')
        return j

    def run_thread(self):
        """свой поток: лиги по очереди, не задерживая Фонбет и PARI"""
        while self.mode == 'thread':
            with STATE.lock:
                matches = dict(STATE.matches)
            try:
                changed = self.poll(matches)
                with self.lock:
                    self.pending |= set(changed)
                time.sleep(0.5)
            except Exception as e:
                self.fails += 1
                self.last_error = str(e).splitlines()[0][:160]
                if self.fails in (1, 5) or self.fails % 20 == 0:
                    add_error('Pinnacle: ' + self.last_error, 'Pinnacle')
                if self.fails >= 10:                 # напрямую не выходит — дальше через окно браузера
                    log('Pinnacle: напрямую не отвечает, перехожу на загрузку через браузер')
                    self.mode = 'browser'
                    break
                time.sleep(min(30, 2 * self.fails))

    def start(self, browser):
        self.page = browser.new_page(locale='en-US')
        hdr = {}

        def on_req(r):
            if 'arcadia.pinnacle.com' in r.url and 'x-api-key' in r.headers:
                hdr.update({k: v for k, v in r.headers.items() if k.lower() in ('x-api-key', 'x-device-uuid')})
        self.page.on('request', on_req)
        try:
            self.page.goto(PIN_SITE, wait_until='domcontentloaded', timeout=90000)
            self.page.wait_for_timeout(8000)
            self.page_url = self.page.url
        except Exception as e:
            log('Pinnacle: страница сайта не открылась (' + str(e).splitlines()[0][:80] + '), пробую напрямую')
        if hdr.get('x-api-key'):
            save_config_keys({'pinnacle_key': hdr['x-api-key']})
        else:                       # скрытое окно сайт мог не обслужить — открытый ключ сайта из прошлого раза
            hdr['x-api-key'] = load_config().get('pinnacle_key') or PIN_PUBLIC_KEY
        self.headers = dict(hdr, Referer='https://www.pinnacle.com/', Accept='application/json')
        try:
            self.http_get('/sports/29/leagues?all=false')
            self.mode = 'thread'
        except Exception as e:
            log('Pinnacle напрямую (без браузера) не ответил: ' + str(e).splitlines()[0][:100])
            self.mode = 'browser'
        if self.mode == 'browser':
            try:
                self.get('/sports/29/leagues?all=false')
            except Exception as e:
                raise RuntimeError('Pinnacle не отвечает — включён ли VPN? (' + str(e).splitlines()[0][:80] + ')')
        else:
            if not (self.thread and self.thread.is_alive()):
                self.thread = threading.Thread(target=self.run_thread, daemon=True)
                self.thread.start()
        log('Pinnacle: цены берутся напрямую с сайта' + (' (свой поток)' if self.mode == 'thread' else ' (через браузер)'))

    def get(self, path):
        if self.mode == 'thread':
            return self.http_get(path)
        r = self.page.context.request.get(PIN_API + path, headers=self.headers, timeout=15000)
        if r.status != 200:
            raise RuntimeError(f'Pinnacle ответил {r.status} на {path[:60]}')
        j = json.loads(r.text())
        if not isinstance(j, list):
            raise RuntimeError(f'Pinnacle прислал не то на {path[:60]}')
        return j

    def hurry(self, mid):
        """цена по матчу нужна срочно — его лиги (основную и угловых) опросить первыми (не чаще раза в 30 с)"""
        for lid in list((self.fair_parts.get(mid) or {}).keys()) or [self.fair_league.get(mid)]:
            lg = self.leagues.get(lid)
            if lg and time.time() - lg.get('last', 0) > 30:
                lg['last'] = 0

    def pick_leagues(self, now, k):
        def interval(lg):
            ns = lg.get('next_start')
            base = 1 if ns is None else pin_interval(ns, now)
            if lg.get('errors'):                       # сбойная лига: ждать дольше с каждой ошибкой
                base = max(base, min(600, 30 * 2 ** min(lg['errors'], 5)))
            return base
        scored = sorted(self.leagues.items(), key=lambda kv: -(now - kv[1]['last']) / interval(kv[1]))
        return [lid for lid, lg in scored[:k] if now - lg['last'] >= interval(lg)]

    def poll(self, matches, k=3):
        """одна-три лиги за вызов; возвращает id матчей odds.ru, у которых обновилась честная цена"""
        now = time.time()
        if now - self.last_req < 1.0:
            return []
        self.last_req = now
        if now - self.leagues_ts > 600:
            lgs = self.get('/sports/29/leagues?all=false')
            for lg in lgs:
                if lg.get('matchupCount', 0) > 0 and not lg.get('isHidden'):
                    old = self.leagues.get(lg['id'], {'last': 0, 'next_start': None})
                    self.leagues[lg['id']] = dict(old, name=lg.get('name', ''), count=lg.get('matchupCount', 0))
            self.leagues_ts = now
        changed, errors, tried = [], [], 0
        for lid in self.pick_leagues(now, k):
            tried += 1
            try:
                mu = self.get(f'/leagues/{lid}/matchups')
                mk = self.get(f'/leagues/{lid}/markets/straight')
            except Exception as e:
                lg = self.leagues[lid]
                lg['last'] = time.time()                 # сбойная лига ждёт свой круг, а не держит очередь
                lg['errors'] = lg.get('errors', 0) + 1
                errors.append(str(e).splitlines()[0][:120])
                continue
            with self.lock:
                changed += self.ingest(lid, mu, mk, matches)
        if tried and len(errors) == tried:
            raise RuntimeError(errors[-1])
        self.last_ok = time.time()
        self.fails = 0
        return changed

    def ingest(self, lid, matchups, markets, matches):
        now = time.time()
        starts = []
        for x in matchups or []:
            if x.get('type') != 'matchup' or x.get('isLive'):
                continue
            try:
                st = datetime.datetime.fromisoformat(x['startTime'].replace('Z', '+00:00')).timestamp()
            except Exception:
                continue
            if x.get('parentId'):
                self.special[x['id']] = {'parent': x['parentId'], 'units': x.get('units')}
                if x.get('units') == 'Corners' and st > now:
                    starts.append(st)
                continue
            if x.get('units') != 'Regular':
                continue
            ps = {p.get('alignment'): p.get('name') for p in x.get('participants') or []}
            if not ps.get('home') or not ps.get('away'):
                continue
            self.regular[x['id']] = {'home': ps['home'], 'away': ps['away'], 'start': st, 'league': lid}
            if st > now:
                starts.append(st)
        lg = self.leagues.setdefault(lid, {'name': '', 'count': 0})
        lg['last'] = now
        lg['errors'] = 0
        clear_error('Pinnacle')
        lg['next_start'] = min(starts) if starts else now + 86400
        by = {}
        for k in markets or []:
            if k.get('status', 'open') == 'open':
                by.setdefault(k.get('matchupId'), []).append(k)
        changed = set()
        had = {mid for mid, parts in self.fair_parts.items() if lid in parts}
        got_parts = {}
        for pid, ks in by.items():
            self.markets[pid] = ks
            if pid in self.regular:
                base, pre_of = pid, {0: '', 1: 'h1_'}
            elif (self.special.get(pid) or {}).get('units') == 'Corners':
                base, pre_of = self.special[pid]['parent'], {0: 'c_'}
            else:
                continue
            if base not in self.regular:
                continue
            got = self.map_match(base, matches)
            if not got:
                continue
            mid, swapped = got
            fair = got_parts.setdefault(mid, {})
            for k in ks:
                pre = pre_of.get(k.get('period'))
                if pre is None:
                    continue
                pr = {p.get('designation'): p for p in k.get('prices') or []}
                try:
                    if k['type'] == 'moneyline' and {'home', 'away', 'draw'} <= set(pr):
                        h, d, a = (am_to_dec(pr[x]['price']) for x in ('home', 'draw', 'away'))
                        po = [a, d, h] if swapped else [h, d, a]
                        fair[(pre + '1x2', None)] = (fair_power(po), po, now)
                    elif k['type'] == 'total' and {'over', 'under'} <= set(pr):
                        po = [am_to_dec(pr['over']['price']), am_to_dec(pr['under']['price'])]
                        fair[(pre + 'total', float(pr['over']['points']))] = (fair_power(po), po, now)
                    elif k['type'] == 'team_total' and {'over', 'under'} <= set(pr) and k.get('side') in ('home', 'away'):
                        side = k['side'] if not swapped else ('away' if k['side'] == 'home' else 'home')
                        po = [am_to_dec(pr['over']['price']), am_to_dec(pr['under']['price'])]
                        fam = 'tt1' if side == 'home' else 'tt2'
                        fair[(pre + fam, float(pr['over']['points']))] = (fair_power(po), po, now)
                    elif k['type'] == 'spread' and {'home', 'away'} <= set(pr):
                        hl = float(pr['home']['points'])
                        h, a = am_to_dec(pr['home']['price']), am_to_dec(pr['away']['price'])
                        if swapped:                       # хозяева odds.ru = гости Pinnacle
                            fair[(pre + 'ah', -hl)] = (fair_power([a, h]), [a, h], now)
                        else:
                            fair[(pre + 'ah', hl)] = (fair_power([h, a]), [h, a], now)
                except (KeyError, TypeError, ValueError, ZeroDivisionError):
                    continue
            if pid in self.regular:
                self.fair_league[mid] = lid
        for mid, fair in got_parts.items():
            if fair:
                self.fair_parts.setdefault(mid, {})[lid] = fair
                changed.add(mid)
        for mid in had - changed:                       # рынок закрыт или матч убран — цену этой лиги не держим
            self.fair_parts[mid].pop(lid, None)
            changed.add(mid)
        out = []
        for mid in changed:
            parts = self.fair_parts.get(mid) or {}
            merged = {}
            for d in parts.values():
                merged.update(d)
            if merged:
                self.fair[mid] = merged
                out.append(mid)
            else:
                self.fair.pop(mid, None)
                self.fair_parts.pop(mid, None)
                self.fair_league.pop(mid, None)
                self.removed.append(mid)
        return out

    def map_match(self, pid, matches):
        if pid in self.match_map and (self.match_map[pid] or time.time() - self.match_tried.get(pid, 0) < 600):
            return self.match_map[pid]
        r = self.regular[pid]
        best, best_s = None, 0.0
        # -84 (пункт 3, «Зенит-2 ⊃ Зенит»): женский матч — только с женским. 22.11 Мельбурн Виктори — Перт Глори (женская
        # W-лига): цена Pinnacle за 9 ч до начала сдвинулась на 52% (1.40 → 2.13) — похоже на чужой матч. У odds.ru в адресе
        # пометки «женщины» нет, у Pinnacle она в названии лиги/команд; сравниваем пол турнира, а названия — без пометки
        p_lg = (self.leagues.get(r.get('league')) or {}).get('name', '')
        p_w = is_women(p_lg) or bool((en_tokens(r['home'])[1] | en_tokens(r['away'])[1]) & {'w', 'women'})
        for m in matches.values():
            if not m.get('home_en') or abs(m['start'] - r['start']) > 20 * 60:
                continue
            if self.taken.get(m['id'], pid) != pid:
                continue
            o_w = is_women(m.get('league'))
            if o_w != p_w:
                continue
            for swapped, (h, a) in ((False, (r['home'], r['away'])), (True, (r['away'], r['home']))):
                if o_w:
                    s1, s2 = en_sim(no_w(h), no_w(m['home_en'])), en_sim(no_w(a), no_w(m['away_en']))
                else:
                    s1, s2 = en_sim(h, m['home_en']), en_sim(a, m['away_en'])
                sc = (s1 + s2) / 2
                if min(s1, s2) >= 0.5 and sc > best_s:
                    best, best_s = (m['id'], swapped), sc
        res = best if best_s >= 0.7 else None
        if res:
            self.taken[res[0]] = pid
        self.match_map[pid] = res
        self.match_tried[pid] = time.time()
        return res

    def compact(self, mid, fresh_since=0):
        """для таблицы pin (цена закрытия): {рынок: [[названия исходов], [кф]]} — только цены не старше fresh_since"""
        out = {}
        for key, (p, po, ts) in self.fair.get(mid, {}).items():
            if ts < fresh_since:
                continue
            out.setdefault(db_market(key[0]), []).append([outcome_names(key[0], key[1]), po])
        return out


def fair_for(mid, odds_data):
    """честная цена матча: Pinnacle с его сайта (свежая, до 20 мин), иначе — как раньше, с odds.ru"""
    with STATE.lock:
        d = STATE.pin_fair.get(mid)
        m = STATE.matches.get(mid)
    if d and m:
        now = time.time()
        d = {k: v for k, v in d.items() if pin_fresh(m['start'], v[2], now)}
        if d:
            return d
    return pinnacle_fair(odds_data or {})


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
        self.miscs = {}            # id события -> счёт из лайва (score1, score2, comment)

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
        for m in (j.get('eventMiscs') or []):
            if isinstance(m, dict) and 'id' in m:
                self.miscs[m['id']] = dict(self.miscs.get(m['id'], {}), **m)
        if j.get('packetVersion'):
            self.version = j['packetVersion']
        kids = {}
        for e in self.events.values():
            if e.get('parentId') and e.get('name') in FB_PARTS and not e.get('_blocked'):
                kids.setdefault(e['parentId'], []).append((e['id'], FB_PARTS[e['name']]))
        self.kids = kids

    def load_geo(self):
        """страны турниров (для ссылки на страницу матча): geoCategoryId → routeAlias"""
        if getattr(self, 'geo', None) or time.time() - getattr(self, 'geo_try', 0) < 1800:
            return
        self.geo_try = time.time()
        try:
            j = self.fetch(f"/sportEvent/geoCategories?version=0&lang=ru&scopeMarket={self.book['scope']}")
            self.geo = {str(g.get('id')): g.get('routeAlias') for g in (j.get('geoCategories') or []) if g.get('routeAlias')}
        except Exception as e:
            log(f'{self.name}: страны турниров не получены ({str(e).splitlines()[0][:80]}) — ссылки будут на odds.ru')

    def event_url(self, ev):
        sp = self.sports.get(ev.get('sportId')) or {}
        alias = (getattr(self, 'geo', None) or {}).get(str(sp.get('geoCategoryId')))
        if not alias:
            return None
        return f"{self.book['site']}sports/football/country/{alias}/{ev['sportId']}/{ev['id']}"

    def poll(self):
        self.load_geo()
        sc = self.book['scope']
        if self.version is None or time.time() - self.last_full > 900:
            j = self.fetch(f'/events/list?lang=ru&version=0&scopeMarket={sc}')
            n = len(j.get('events') or [])
            if n < 300:
                j2 = self.fetch(f'/events/list?lang=ru&scopeMarket={sc}')
                if len(j2.get('events') or []) > n:
                    j = j2
            self.events, self.factors, self.miscs = {}, {}, {}
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

    @staticmethod
    def odds_one(fs, pre, out):
        v = [fs.get(k, {}).get('v') for k in F_1X2]
        if all(isinstance(x, (int, float)) and x > 1 for x in v):
            out[(pre + '1x2', None)] = v
        for fam, plist in (('total', F_TOTALS), ('ah', F_AH), ('tt1', F_TT1), ('tt2', F_TT2)):
            for a, b in plist:
                fa, fb = fs.get(a), fs.get(b)
                if not (fa and fb and isinstance(fa.get('v'), (int, float)) and isinstance(fb.get('v'), (int, float))):
                    continue
                if fa['v'] <= 1 or fb['v'] <= 1:
                    continue
                try:
                    ln = fa.get('p', 0) / 100
                except TypeError:
                    continue
                out[(pre + fam, ln)] = [fa['v'], fb['v']]

    def odds_of(self, eid):
        out = {}
        self.odds_one(self.factors.get(eid, {}), '', out)
        for cid, pre in getattr(self, 'kids', {}).get(eid, []):
            self.odds_one(self.factors.get(cid, {}), pre, out)
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


SOFA_API = 'https://www.sofascore.com/api/v1'
PAGE_FETCH_JS = """async (u) => { try { const r = await fetch(u, {credentials: 'include'});
    return {s: r.status, t: await r.text()} } catch (e) { return {s: 0, t: String(e)} } }"""


class ExtStats:
    """Sofascore, затем FotMob (разведка 21.11: оба открываются у владельца, запросы — изнутри страницы сайта):
    счёт основного времени (без доп. времени), первого тайма и угловые сыгранного матча."""

    def __init__(self):
        self.pages = {}
        self.page_try = {}
        self.fm_days = {}           # дата -> (когда получено, матчи FotMob)
        self.last_error = ''

    def page(self, browser, key, url):
        if getattr(self, 'blocked', {}).get(key, 0) > time.time():
            return None
        p = self.pages.get(key)
        if p is not None or browser is None:
            return p
        if time.time() - self.page_try.get(key, 0) < 1800:
            return None
        self.page_try[key] = time.time()
        try:
            p = browser.new_page(locale='ru-RU')
            p.goto(url, wait_until='domcontentloaded', timeout=60000)
            p.wait_for_timeout(4000)
            self.pages[key] = p
            return p
        except Exception as e:
            self.last_error = f'{key}: {str(e).splitlines()[0][:100]}'
            log(f'статистика матчей: {key} не открылся — попробую через 30 мин')
            try:
                p.close()
            except Exception:
                pass
            return None

    def get(self, key, url):
        try:
            r = self.pages[key].evaluate(PAGE_FETCH_JS, url)
        except Exception as e:
            self.last_error = f'{key}: {str(e).splitlines()[0][:100]}'
            self.pages.pop(key, None)          # страница сломалась — откроется заново
            return None
        if r.get('s') == 403 and 'challenge' in str(r.get('t')):
            # 22.11 у владельца: Sofascore отвечает программе «403 challenge» (проверка «вы не робот») — 30 мин не дёргать
            self.blocked = dict(getattr(self, 'blocked', {}), **{key: time.time() + 1800})
            self.last_http = f'{key} не пускает программу (проверка «вы не робот») — пока ищем на FotMob'
            return None
        if r.get('s') != 200:
            self.last_http = f"{url.split('?')[0][-60:]} → ответ {r.get('s')}: {str(r.get('t'))[:80]}"
            return None
        try:
            return json.loads(r['t'])
        except ValueError:
            self.last_http = f"{url.split('?')[0][-60:]} → не JSON: {str(r.get('t'))[:80]}"
            return None

    @staticmethod
    def pair(h, a, home_en, away_en):
        """True — та же ориентация, False — хозяева и гости наоборот, None — не тот матч"""
        if min(en_sim(home_en, h), en_sim(away_en, a)) >= 0.6:
            return True
        if min(en_sim(home_en, a), en_sim(away_en, h)) >= 0.6:
            return False
        return None

    def find_sofa(self, home_en, away_en, start_ts):
        """матч на Sofascore по английским названиям и времени ±20 мин → (событие, та же ориентация) или (None, None)"""
        q_home, q_away = home_en.replace('-', ' '), away_en.replace('-', ' ')
        log_ = {'home': home_en, 'away': away_en, 'start': start_ts, 'tries': []}
        if not hasattr(self, 'sofa_log'):
            self.sofa_log = []
        self.sofa_log = (self.sofa_log + [log_])[-40:]
        for q in (f'{q_home} {q_away}', q_home, q_away):
            self.last_http = ''
            j = self.get('sofascore', f'{SOFA_API}/search/events?q={urllib.parse.quote(q)}&page=0')
            res = (j or {}).get('results') or []
            near = sorted(((abs((r.get('entity') or {}).get('startTimestamp', 0) - start_ts),
                            (r.get('entity') or {}).get('name', '')) for r in res))[:3]
            log_['tries'].append({'q': q, 'ok': j is not None, 'http': self.last_http, 'n': len(res),
                                  'nearest': [(round(dt / 60), nm) for dt, nm in near]})
            for r in res:
                e = r.get('entity') or {}
                if abs((e.get('startTimestamp') or 0) - start_ts) > 20 * 60:
                    continue
                same = self.pair((e.get('homeTeam') or {}).get('name', ''), (e.get('awayTeam') or {}).get('name', ''),
                                 home_en, away_en)
                if same is not None:
                    log_['found'] = e.get('name')
                    return e, same
        return None, None

    def sofa_page(self, browser, home_en, away_en, start_ts):
        """адрес страницы матча на Sofascore (формат проверен разведкой 21.11: /ru/football/match/<slug>/<customId>)"""
        if self.page(browser, 'sofascore', 'https://www.sofascore.com/ru/football') is None:
            return None
        e, _ = self.find_sofa(home_en, away_en, start_ts)
        if not e or not e.get('slug') or not e.get('customId'):
            return ''
        return f"https://www.sofascore.com/ru/football/match/{e['slug']}/{e['customId']}"

    def sofa(self, home_en, away_en, start_ts):
        q_home, q_away = home_en.replace('-', ' '), away_en.replace('-', ' ')
        ev, same = None, None
        for q in (f'{q_home} {q_away}', q_home, q_away):
            j = self.get('sofascore', f'{SOFA_API}/search/events?q={urllib.parse.quote(q)}&page=0') or {}
            for r in j.get('results') or []:
                e = r.get('entity') or {}
                if abs((e.get('startTimestamp') or 0) - start_ts) > 20 * 60:
                    continue
                same = self.pair((e.get('homeTeam') or {}).get('name', ''), (e.get('awayTeam') or {}).get('name', ''),
                                 home_en, away_en)
                if same is not None:
                    ev = e
                    break
            if ev:
                break
        if not ev:
            return None
        d = {'src': 'sofascore', 'ext_id': str(ev['id'])}
        j = (self.get('sofascore', f"{SOFA_API}/event/{ev['id']}") or {}).get('event') or {}
        if (j.get('status') or {}).get('type') != 'finished':
            return dict(d, finished=False)
        hs, as_ = j.get('homeScore') or {}, j.get('awayScore') or {}
        d.update(finished=True, ft=(hs.get('normaltime'), as_.get('normaltime')),
                 ht=(hs.get('period1'), as_.get('period1')))
        st = self.get('sofascore', f"{SOFA_API}/event/{ev['id']}/statistics") or {}
        for per in st.get('statistics') or []:
            if per.get('period') != 'ALL':
                continue
            for g in per.get('groups') or []:
                for it in g.get('statisticsItems') or []:
                    if it.get('key') == 'cornerKicks' or it.get('name') == 'Corner kicks':
                        d['c'] = (it.get('homeValue'), it.get('awayValue'))
        if not same:
            d = {k: (v[1], v[0]) if isinstance(v, tuple) else v for k, v in d.items()}
        return d

    def fm_list(self, start_ts):
        """матчи FotMob за день начала (и соседние сутки — сайт считает день по своему часовому поясу); кэш 30 мин"""
        out = []
        for dd in (-1, 0, 1):
            day = (datetime.datetime.fromtimestamp(start_ts, MSK) + datetime.timedelta(days=dd)).strftime('%Y%m%d')
            got = self.fm_days.get(day)
            if not got or time.time() - got[0] > 1800:
                j = self.get('fotmob', f'https://www.fotmob.com/api/data/matches?date={day}')
                if j is None:
                    continue                    # не ответил — не запоминать пустой день
                got = (time.time(), [m for lg in j.get('leagues') or [] for m in lg.get('matches') or []])
                self.fm_days[day] = got
            out += got[1]
        return out

    def find_fotmob(self, home_en, away_en, start_ts):
        """матч FotMob по времени ±20 мин и названиям (полное и короткое). С -56: если обе команды не сошлись на 0.6,
        достаточно одной почти точно (≥0.9) — при условии, что в это время такой матч ровно один (команда не играет
        два матча сразу). Промахи с ближайшими по времени матчами — в fm_miss (отчёт для разработки)."""
        def sim(name, x):
            return max(en_sim(name, x.get('name') or ''), en_sim(name, x.get('shortName') or '') if x.get('shortName') else 0)
        best, loose, near = None, [], []
        for x in self.fm_list(start_ts):
            dt = abs((x.get('timeTS') or 0) / 1000 - start_ts)
            if dt > 20 * 60:
                continue
            h, a = x.get('home') or {}, x.get('away') or {}
            near.append((round(dt / 60), h.get('name'), a.get('name')))
            for same, s1, s2 in ((True, sim(home_en, h), sim(away_en, a)), (False, sim(home_en, a), sim(away_en, h))):
                if min(s1, s2) >= 0.6:
                    if best is None or s1 + s2 > best[0]:
                        best = (s1 + s2, x, same)
                elif max(s1, s2) >= 0.9:
                    loose.append((x, same))
        if best:
            return best[1], best[2]
        if len({x.get('id') for x, _ in loose}) == 1:
            return loose[0]
        if not hasattr(self, 'fm_miss'):
            self.fm_miss = []
        self.fm_miss = ([m for m in self.fm_miss if (m['home'], m['away']) != (home_en, away_en)]
                        + [{'home': home_en, 'away': away_en, 'start': start_ts, 'near': sorted(near)[:5]}])[-40:]
        return None, None

    def stats_page(self, browser, home_en, away_en, start_ts):
        """страница матча со статистикой: FotMob (весь день одним запросом; /match/<id> — проверено разведкой 21.11:
        владение, удары, удары в створ…), иначе Sofascore. None — ни один сайт не открылся, '' — матч не нашёлся."""
        opened = False
        if self.page(browser, 'fotmob', 'https://www.fotmob.com/') is not None:
            opened = True
            m, _ = self.find_fotmob(home_en, away_en, start_ts)
            if m and m.get('id'):
                return f"https://www.fotmob.com/match/{m['id']}"
        if self.page(browser, 'sofascore', 'https://www.sofascore.com/ru/football') is not None:
            opened = True
            e, _ = self.find_sofa(home_en, away_en, start_ts)
            if e and e.get('slug') and e.get('customId'):
                return f"https://www.sofascore.com/ru/football/match/{e['slug']}/{e['customId']}"
        return '' if opened else None

    def fotmob(self, home_en, away_en, start_ts):
        m, same = None, None
        for x in self.fm_list(start_ts):
            if abs((x.get('timeTS') or 0) / 1000 - start_ts) > 20 * 60:
                continue
            same = self.pair((x.get('home') or {}).get('name', ''), (x.get('away') or {}).get('name', ''),
                             home_en, away_en)
            if same is not None:
                m = x
                break
        if not m:
            return None
        d = {'src': 'fotmob', 'ext_id': str(m['id'])}
        # -64: статус в списке дня — из кэша (до 30 мин), 22.11 Пачука—Толука из-за этого ждала расчёта ~10 мин;
        # окончен ли матч — по свежим matchDetails
        j = self.get('fotmob', f"https://www.fotmob.com/api/data/matchDetails?matchId={m['id']}") or {}
        if not (((j.get('header') or {}).get('status') or {}).get('finished')
                or ((m.get('status') or {}).get('finished') and j)):
            return dict(d, finished=False)
        d['finished'] = True
        content = j.get('content') or {}
        for e in ((content.get('matchFacts') or {}).get('events') or {}).get('events') or []:
            if e.get('type') == 'Half' and e.get('halfStrShort') == 'HT':
                d['ht'] = (e.get('homeScore'), e.get('awayScore'))
            if e.get('type') == 'Half' and e.get('halfStrShort') == 'FT':
                d['ft'] = (e.get('homeScore'), e.get('awayScore'))     # конец основного времени
        for g in (((content.get('stats') or {}).get('Periods') or {}).get('All') or {}).get('stats') or []:
            for it in g.get('stats') or []:
                if it.get('key') == 'corners' and isinstance(it.get('stats'), list) and len(it['stats']) == 2:
                    d['c'] = tuple(it['stats'])
        if not same:
            d = {k: (v[1], v[0]) if isinstance(v, tuple) else v for k, v in d.items()}
        return d

    def lookup(self, browser, home_en, away_en, start_ts):
        """объединяет Sofascore и FotMob: недостающее у первого берётся у второго"""
        out = {}
        for key, url, fn in (('sofascore', 'https://www.sofascore.com/ru/football', self.sofa),
                             ('fotmob', 'https://www.fotmob.com/', self.fotmob)):
            if all(isinstance(out.get(k), tuple) and None not in out[k] for k in ('ft', 'ht', 'c')):
                break
            if self.page(browser, key, url) is None:
                continue
            d = fn(home_en, away_en, start_ts)
            if not d or not d.get('finished'):
                continue
            for k, v in d.items():
                if k in ('ft', 'ht', 'c'):
                    if isinstance(v, tuple) and None not in v and not (isinstance(out.get(k), tuple) and None not in out[k]):
                        out[k] = tuple(int(x) for x in v)
                elif k not in out:
                    out[k] = v
        return out

# ================================================================ Винлайн: разбор потока websocket (версия -42)
# Формат восстановлен по коду сайта и проверен на записанных кадрах разведки 21.11 (176 совпадений с DOM, 0 расхождений).
# Рынки с пометкой 'dom' сверены со страницей сайта, 'name' — только по названию из справочника;
# программа берёт ТОЛЬКО сверенные (verified_only=True): 1x2, тотал, фора, то же на 1-й тайм.

STEP_PACK = 20000          # пачка сообщений
STEP_GZIP = 0x8B1F         # 35615: первые байты 1f 8b — сообщение сжато gzip
STEP_PREMATCH = 3
STEP_LIVE = 4
STEP_MENU = 16
STEP_EVENT_FILL = 18       # ответ на 'event.plus' (по коду сайта; в записи не встречался)
STEP_EVENT_FILL_NEW = 1118
STEP_GET_DATE = 38
STEP_INITIALIZED = 51

STEP_NAMES = {
    3: 'GET_PREMATCH', 4: 'LIVE', 7: 'LIVE_OUTRIGHTS', 16: 'GET_MENU', 18: 'GET_EVENT_FILL',
    38: 'GET_DATE', 44: 'GET_BOUNUS_KOEF', 51: 'CLIENT_IS_INITIALIZED', 76: 'SPECIAL_EVENTS_PLUS',
    86: 'GET_SPECIAL_EVENTS_CASH', 94: 'PING', 110: 'GET_MULTIPLICATION', 1118: 'GET_EVENT_FILL_NEW',
    1180: 'TACTICAL_MARKETING', 1181: 'IGNORED_1181', 1348: 'CONTENT_VERSION',
    1399: 'INTERNATIONAL2025_COMMON_DATA', 2000: 'CUPIS_GATEWAY_CONFIG', 2001: 'CUPIS_2001',
    2002: 'CUPIS_2002', 20000: 'STEP_PACK',
}

# Сервер шлёт время как «московские часы, записанные как UTC» (в коде сайта TZ_OFFSET_MS = 108e5).
TZ_OFFSET = 10800

# Команды, которые сайт отправляет текстом сразу после открытия websocket (initCommands).
INIT_COMMANDS = ['lang', 'AA==', 'data', 'WINLINE', 'getdate']
KEEPALIVE_COMMAND = 'getdate'     # сайт шлёт его, если 5 с не было входящих; >40 с тишины — переподключение
WS_URL = 'wss://wss.winline.ru/data_ng?client=newsite&nb=true'


class WinlineDecodeError(Exception):
    pass


# ---------------------------------------------------------------- чтение байтов
class _R:
    __slots__ = ('b', 'p')

    def __init__(self, b, p=0):
        self.b = b
        self.p = p

    def left(self):
        return len(self.b) - self.p

    def u8(self):
        v = self.b[self.p]
        self.p += 1
        return v

    def u16(self):
        v = struct.unpack_from('<H', self.b, self.p)[0]
        self.p += 2
        return v

    def u32(self):
        v = struct.unpack_from('<I', self.b, self.p)[0]
        self.p += 4
        return v

    def i32(self):
        v = struct.unpack_from('<i', self.b, self.p)[0]
        self.p += 4
        return v

    def utf(self):
        n = self.u16()
        raw = self.b[self.p:self.p + n]
        if len(raw) < n:
            raise WinlineDecodeError('строка выходит за конец сообщения')
        self.p += n
        k = raw.find(b'\x1b')
        if k >= 0:
            raw = raw[:k]
        return raw.decode('utf-8', 'replace')

    def skip_block16(self):
        """Блок виджетов события (Re в коде сайта): [длина u16][TLV...] — нам не нужен."""
        n = self.u16()
        self.p += n


# ---------------------------------------------------------------- распаковка
def _gunzip(b):
    # сайт отрезает 10 байт заголовка gzip и распаковывает «сырой» deflate
    try:
        return zlib.decompressobj(-15).decompress(b[10:])
    except zlib.error:
        return gzip.decompress(b)


def unpack_messages(data):
    """bytes кадра -> список (шаг, данные_без_шага). Пачки и gzip раскрываются."""
    out = []
    _unpack(bytes(data), out, 0)
    return out


def _unpack(b, out, depth):
    if depth > 8 or len(b) < 2:
        if len(b) == 1:
            out.append((b[0], b''))
        return
    step = b[0] | (b[1] << 8)
    if step == STEP_GZIP:
        _unpack(_gunzip(b), out, depth + 1)
        return
    if step != STEP_PACK:
        out.append((step, b[2:]))
        return
    i = 2
    while i + 4 <= len(b):
        n = struct.unpack_from('<I', b, i)[0]
        _unpack(b[i + 4:i + 4 + n], out, depth + 1)
        i += 4 + n


# ---------------------------------------------------------------- коэффициенты
def _js_round2(x):
    return math.floor(x * 100 + 0.5) / 100        # Math.round(x*100)/100


def _js_num(x):
    """Как JS превращает число в строку: 2.5 -> '2.5', 3.0 -> '3'."""
    if x == int(x):
        return str(int(x))
    return repr(x)


def set_coeff(V, p, tip_id, is_live):
    """Порт setCoeff сайта: наценка p (обычно 1 — без изменений)."""
    V = list(V)
    if p == 1 or is_live == 1:
        return V
    V = [_js_round2(1 + (g - 1) * p) if g > 1 else g for g in V]
    if tip_id in (114, 115, 116, 117, 181) and len(V) >= 3 and all(V[:3]):
        g0, g1, g2 = V[0], V[1], V[2]
        s = 1 / g0 + 1 / g1 + 1 / g2
        V[0] = 1 / (s - 1 / g2) if g2 != 0 else 1
        V[1] = 1 / (s - 1 / g1) if g1 != 0 else 1
        V[2] = 1 / (s - 1 / g0) if g0 != 0 else 1
        V[:3] = [_js_round2(max(v, 1)) for v in V[:3]]
    out = []
    for g in V:
        if g > 0:
            if g >= 10:
                g = float(math.floor(g))
            elif g < 1.01:
                g = 1.0
        out.append(g)
    return out


# ---------------------------------------------------------------- шаг 16: справочник
def _parse_menu(p):
    r = _R(p)
    recs = []
    for _ in range(r.u32()):
        sid = r.i32()
        sort = r.i32()
        name = r.utf()
        strings = dict(zip(['NP', 'RT', 'FT', 'HT', 'P', 'OT', 'PEN', 'Z', 'W'],
                           [r.utf() for _ in range(9)]))
        recs.append({'kind': 'sport', 'id': sid, 'sort': sort, 'name': name, 'strings': strings})
    for _ in range(r.u32()):
        t = {'kind': 'tipline', 'id': r.u32(), 'sports': r.utf(), 'favorite': r.u32(),
             'count_v': r.u32(), 'src': r.u32(), 'name': r.utf()}
        t['outcomes'] = [r.utf() for _ in range(30)]
        recs.append(t)
    for _ in range(r.u32()):
        recs.append({'kind': 'tv', 'id': r.u32(), 'name': r.utf()})
    variables = {}
    for _ in range(r.u32()):
        k = r.u8()
        variables[k] = r.u32()
    recs.append({'kind': 'vars', 'vars': variables})
    return recs


# ---------------------------------------------------------------- шаг 3: прематч
def _pm_line(r, tip_src, ev_id, with_event):
    L = {'id': r.u32()}
    L['event_id'] = r.u32() if with_event else ev_id
    L['tip'] = r.u16()
    m1 = r.u16()
    m2 = r.u16()
    L['margin'] = m2 / 1e4          # клиент CUPIS берёт второе число (Xe.read)
    L['margin_raw'] = (m1, m2)
    src = tip_src.get(L['tip'])
    if src is None:
        raise WinlineDecodeError('нет типа рынка %d в справочнике (шаг 16 не получен?)' % L['tip'])
    fav = 0
    koef = ''
    if src in (3, 6):
        fav = r.u8()
        koef = _js_num(r.u16() / 100)
    elif src in (4, 7):
        koef = _js_num(r.u16() / 100)
    elif src in (51, 151):
        koef = '1'
    elif src == 61:
        fav = r.u8()
        koef = '1/' + _js_num(r.u16() / 100)
    elif src == 71:
        koef = '1/' + _js_num(r.u16() / 100)
    V = [r.u16() / 100, r.u16() / 100]
    if src in (2, 5, 51):
        V.append(r.u16() / 100)
    elif src == 9:
        V += [r.u16() / 100, r.u16() / 100]
    L['favorite'] = fav
    L['koef'] = koef
    L['V_raw'] = V
    L['V'] = set_coeff(V, L['margin'], L['tip'], 0)
    return L


def _pm_event(r, champ_id, update):
    e = {'id': r.u32(), 'id_radar': r.u32(), 'id_native': r.u32(), 'provider': r.u8(),
         'category': r.u8(), 'id_live': r.u8(), 'lines_availability': r.u8()}
    r.u8()
    r.u8()
    r.skip_block16()
    e['champ_id'] = r.u32() if update else champ_id
    t = r.u32()
    e['t_raw'] = t
    e['start_ts'] = _pm_ts(t)
    e['count_add_line'] = r.u8()
    e['is_od'] = r.u8()
    e['home'] = r.utf()
    e['away'] = r.utf()
    return e


def _pm_ts(t):
    # setDate(1e3*t + 29999 - TZ_OFFSET_MS), затем setSeconds(0): округление до минуты
    return ((t * 1000 + 29999 - TZ_OFFSET * 1000) // 60000) * 60


def _parse_prematch(p, tip_src):
    r = _R(p, 16)                      # 16 байт заголовка (в записи — нули)
    recs = []
    champ = None
    ev = None
    while r.left() > 0:
        s = r.u8()
        if s == 1:
            recs.append({'kind': 'pm_country', 'id': r.u32(), 'is_region': r.u32(), 'name': r.utf(),
                         'sort': r.u32(), 'continent': r.u8(), 'x': r.u16(), 'y': r.u16(),
                         'show_group': r.u8()})
        elif s == 2:
            c = {'kind': 'pm_champ', 'id': r.u32(), 'sport_id': r.u32(), 'country_id': r.u32(),
                 'name': r.utf(), 'sort': r.i32(), 'code': r.u32(), 'count_special': r.u32(),
                 'level': r.u8(), 'sort_level': r.u32(), 'sort_new_level': r.u32()}
            champ = c['id']
            recs.append(c)
        elif s == 3 or s == 34:
            e = _pm_event(r, champ, s == 34)
            e['kind'] = 'pm_event' if s == 3 else 'pm_event_update'
            ev = e['id']
            recs.append(e)
        elif s == 4 or s == 43:
            L = _pm_line(r, tip_src, ev, s == 43)
            L['kind'] = 'pm_line' if s == 4 else 'pm_line_update'
            recs.append(L)
        elif s == 31:
            eid = r.u32()
            t = r.u32()
            recs.append({'kind': 'pm_event_time', 'id': eid, 't_raw': t, 'start_ts': _pm_ts(t)})
        elif s == 32:
            recs.append({'kind': 'pm_event_delete', 'id': r.u32()})
        elif s == 33:
            recs.append({'kind': 'pm_event_add', 'id': r.u32(), 'count_add_line': r.u8(),
                         'is_od': r.u8()})
        elif s == 42:
            recs.append({'kind': 'pm_line_delete', 'id': r.u32()})
        else:
            raise WinlineDecodeError('прематч: неизвестный подшаг %d на %d/%d' % (s, r.p, len(p)))
    return recs


# ---------------------------------------------------------------- шаг 4: лайв
def _parse_live(p):
    r = _R(p, 0)
    n_ch, n_ev, n_ln = r.u32(), r.u32(), r.u32()      # заголовок: число турниров, событий, линий
    recs = [{'kind': 'live_header', 'champs': n_ch, 'events': n_ev, 'lines': n_ln}]
    while r.left() > 0:
        s = r.u8()
        if s == 2:
            recs.append({'kind': 'live_champ', 'id': r.u32(), 'sport_id': r.u32(), 'sort': r.i32(),
                         'country_id': r.u32(), 'code': r.u8(), 'name': r.utf(), 'level': r.u8(),
                         'sort_level': r.u32(), 'sort_new_level': r.u32()})
        elif s == 3 or s == 4:
            e = {'id': r.i32()}
            if s == 3:
                e.update(id_radar=r.u32(), id_native=r.u32(), provider=r.u8(), category=r.u8())
            r.skip_block16()
            e['is_od'] = r.u8()
            r.u8()
            e['duration'] = r.u8()
            e['state'] = r.i32()
            if e['state'] > 3:                         # > STATUSES.DELETE -> событие удалено
                recs.append({'kind': 'live_event_delete', 'id': e['id'], 'state': e['state']})
                continue
            if s == 3:
                e['champ_id'] = r.u32()
                e['home'] = r.utf()
                e['away'] = r.utf()
                t = r.u32()
                e['t_raw'] = t
                e['start_ts'] = t - TZ_OFFSET
            e['time'] = r.utf()
            e['cards'] = {'Y1': r.u8(), 'Y2': r.u8(), 'R1': r.u8(), 'R2': r.u8()}
            e['feed'] = r.u8()
            e['score'] = r.utf()
            e['set_scores'] = r.utf()
            e['add_info'] = r.utf()          # для футбола — угловые «3:3»
            e['line_count'] = r.u8()
            e['kind'] = 'live_event' if s == 3 else 'live_event_update'
            recs.append(e)
        elif s == 5:
            lid = r.u32()
            st = r.u8()
            if st == 5:                                # STATUSES.DELETE линии
                recs.append({'kind': 'live_line_delete', 'id': lid})
                continue
            L = {'kind': 'live_line', 'id': lid, 'state': st, 'event_id': r.u32()}
            n = r.u8()
            L['V'] = [r.u16() / 100 for _ in range(n)]
            L['tip'] = r.u16()
            L['koef'] = r.utf()
            L['favorite'] = r.u8()
            recs.append(L)
        elif s == 6:
            recs.append({'kind': 'live_count', 'event_id': r.u32(), 'n': r.u8()})
        else:
            raise WinlineDecodeError('лайв: неизвестный подшаг %d на %d/%d' % (s, r.p, len(p)))
    return recs


# ---------------------------------------------------------------- шаг 18/1118: роспись события
def _parse_event_fill(p, new_format):
    """По коду сайта (класс Le). В записанной разведке такого ответа нет — НЕ ПРОВЕРЕНО на данных."""
    r = _R(p)
    eid = r.u32()
    rec = {'kind': 'fill_event', 'event_id': eid}
    if new_format:
        rec['team_ids'] = (r.u32(), r.u32())
    recs = [rec]
    while r.left() > 0:
        L = {'kind': 'fill_line', 'event_id': eid, 'id': r.u32(), 'tip': r.u16()}
        r.u16()
        L['margin'] = r.u16() / 1e4
        L['favorite'] = r.u8()
        L['koef'] = r.utf()
        kol = r.u32()
        V = [r.u32() / 1e4 for _ in range(min(kol, 30))]
        L['V_raw'] = V
        L['V'] = set_coeff(V, L['margin'], L['tip'], 0)
        recs.append(L)
    return recs


# ---------------------------------------------------------------- общий вход
_DEFAULT_TIP_SRC = {}


def decode_frame(data, tip_src=None):
    """Двоичный кадр websocket (как пришёл, gzip) -> список записей (dict с полем 'kind' и 'step').

    tip_src — {id типа рынка: idTipEventSrc} из справочника (шаг 16). Нужен для разбора линий
    прематча (длина записи зависит от типа). Если не передан — берётся из последнего справочника,
    который проходил через decode_frame.
    """
    if isinstance(data, str):
        return [{'kind': 'text', 'step': None, 'text': data}]
    if tip_src is None:
        tip_src = _DEFAULT_TIP_SRC
    out = []
    for step, p in unpack_messages(data):
        if step == STEP_MENU:
            recs = _parse_menu(p)
            src = {t['id']: t['src'] for t in recs if t['kind'] == 'tipline'}
            tip_src.update(src)
            if tip_src is not _DEFAULT_TIP_SRC:
                _DEFAULT_TIP_SRC.update(src)
        elif step == STEP_PREMATCH:
            recs = _parse_prematch(p, tip_src)
        elif step == STEP_LIVE:
            recs = _parse_live(p)
        elif step in (STEP_EVENT_FILL, STEP_EVENT_FILL_NEW):
            recs = _parse_event_fill(p, step == STEP_EVENT_FILL_NEW)
        elif step == STEP_GET_DATE and len(p) >= 4:
            t = struct.unpack_from('<I', p, 0)[0]
            recs = [{'kind': 'server_date', 't_raw': t, 'ts': t - TZ_OFFSET}]
        elif step == STEP_INITIALIZED:
            recs = [{'kind': 'initialized'}]
        else:
            recs = [{'kind': 'other', 'name': STEP_NAMES.get(step, ''), 'size': len(p)}]
        for x in recs:
            x['step'] = step
        out.extend(recs)
    return out


# ---------------------------------------------------------------- рынки футбола
# tip -> (семейство, где линия, как читать исходы). Каждая строка подтверждена:
#   'dom'  — коэффициенты совпали со страницей (line.html / match.html);
#   'name' — только по названию рынка и исходов в справочнике сайта (шаг 16), с DOM не сверено.
# Линия: 'none' — без линии; 'a' — koef целиком; 'b' — вторая часть 'период/линия';
# '_fav' — фора: знак по байту favorite (1 — минус у хозяев, 2 — плюс у хозяев).
# Семейство с '{p}' — период из первой части koef: 1 -> 'h1_', 2 -> 'h2_'.
_O_1X2 = ['1', 'X', '2']
_O_AH = ['1', '2']
_O_TOT = ['Больше', 'Меньше']
_O_DC = ['1X', '12', 'X2']

WL_MARKETS = {
    490:  ('1x2', 'none', _O_1X2, 'dom'),          # Исход 1X2 (@NP@)
    2:    ('h1_1x2', 'none', _O_1X2, 'dom'),       # @1HT@ исход 1X2
    956:  ('h2_1x2', 'none', _O_1X2, 'dom'),       # @2HT@ исход 1X2
    939:  ('{p}1x2', 'p', _O_1X2, 'dom'),          # @[a]P@ исход 1X2 (a = номер тайма)
    1049: ('total', 'a', _O_TOT, 'dom'),           # Тотал [a] (@NP@)
    985:  ('h1_total', 'a', _O_TOT, 'dom'),        # @1HT@ тотал [a]
    960:  ('h2_total', 'a', _O_TOT, 'name'),       # @2HT@ тотал [a]
    933:  ('{p}total', 'b', _O_TOT, 'dom'),        # @[a]P@ тотал [b]
    1073: ('ah', 'a_fav', _O_AH, 'dom'),           # Фора [a] (@NP@)
    988:  ('h1_ah', 'a_fav', _O_AH, 'dom'),        # @1HT@ фора [a]
    958:  ('h2_ah', 'a_fav', _O_AH, 'name'),       # @2HT@ фора [a]
    932:  ('{p}ah', 'b_fav', _O_AH, 'dom'),        # @[a]P@ фора [b]
    1050: ('tt1', 'a', _O_TOT, 'name'),            # Тотал [a] (@NP@) @1
    1051: ('tt2', 'a', _O_TOT, 'name'),            # Тотал [a] (@NP@) @2
    986:  ('h1_tt1', 'a', _O_TOT, 'name'),         # @1HT@ тотал [a] @1
    987:  ('h1_tt2', 'a', _O_TOT, 'name'),         # @1HT@ тотал [a] @2
    961:  ('h2_tt1', 'a', _O_TOT, 'name'),
    962:  ('h2_tt2', 'a', _O_TOT, 'name'),
    947:  ('{p}tt1', 'b', _O_TOT, 'name'),         # @[a]P@ тотал [b] @1
    948:  ('{p}tt2', 'b', _O_TOT, 'name'),
    114:  ('dc', 'none', _O_DC, 'name'),           # Двойной шанс (@NP@)
    115:  ('h1_dc', 'none', _O_DC, 'name'),        # @1HT@ двойной шанс
    966:  ('h2_dc', 'none', _O_DC, 'name'),
    978:  ('{p}dc', 'p', _O_DC, 'name'),           # @[a]P@ двойной шанс
    80:   ('c_1x2', 'none', _O_1X2, 'name'),       # Исход 1X2 угловые (@NP@)
    1070: ('c_total', 'a', _O_TOT, 'name'),        # Тотал угловых [a] (@NP@)
    1071: ('c_tt1', 'a', _O_TOT, 'name'),          # Тотал угловых [a] (@NP@) @1
    1072: ('c_tt2', 'a', _O_TOT, 'name'),          # Тотал угловых [a] (@NP@) @2
    1079: ('c_ah', 'a_fav', _O_AH, 'name'),        # Фора угловых [a] (@NP@)
    81:   ('c_h1_1x2', 'none', _O_1X2, 'name'),    # @1P@ исход 1X2 угловые
    1006: ('c_h1_total', 'a', _O_TOT, 'name'),     # @1P@ тотал угловых [a]
    1007: ('c_h1_tt1', 'a', _O_TOT, 'name'),
    1008: ('c_h1_tt2', 'a', _O_TOT, 'name'),
    1010: ('c_h1_ah', 'a_fav', _O_AH, 'name'),     # @1P@ фора угловых [a]
}

FOOTBALL_SPORT_ID = 1


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def market_key(tip, koef, favorite, tipline=None):
    """(семейство, линия, перестановка исходов) или None, если рынок нам не нужен/не распознан."""
    m = WL_MARKETS.get(tip)
    if m is None:
        return None
    fam, how, want, _proof = m
    # порядок исходов берём по названиям из справочника сайта, а не «по привычке»
    if tipline is not None:
        names = [x.strip() for x in tipline['outcomes'][:max(tipline['count_v'], len(want))]]
        try:
            order = [names.index(w) for w in want]
        except ValueError:
            return None
    else:
        order = list(range(len(want)))
    parts = (koef or '').split('/')
    if '{p}' in fam:
        per = parts[0] if parts else ''
        if per not in ('1', '2'):
            return None
        fam = fam.replace('{p}', 'h%s_' % per)
    line = None
    if how in ('a', 'a_fav'):
        line = _num(parts[0])
        if line is None:
            return None
    elif how in ('b', 'b_fav'):
        if len(parts) < 2:
            return None
        line = _num(parts[1])
        if line is None:
            return None
    if how.endswith('_fav'):
        x = abs(line)
        if favorite == 1:
            line = -x
        elif favorite == 2:
            line = x
        line = line + 0.0
        if line == 0:
            line = 0.0
    return fam, line, order


def _odds_out(V, order):
    out = []
    for i in order:
        v = V[i] if i < len(V) else None
        out.append(v if (v is not None and v > 1.0) else None)   # 1.0 = исход закрыт («-» на сайте)
    return out


class WinlineLine:
    """Состояние линии Винлайна, собранное из кадров websocket."""

    def __init__(self):
        self.reset(full=True)

    def reset(self, full=False):
        if full:
            self.sports = {}
            self.tiplines = {}
            self.tip_src = {}
        self.countries = {}
        self.pm_champs = {}
        self.pm_events = {}
        self.pm_lines = {}
        self.live_champs = {}
        self.live_events = {}
        self.live_lines = {}
        self.server_ts = None
        self.initialized = False
        self.frames = 0

    # ---- приём кадров
    def feed(self, frame_bytes):
        if isinstance(frame_bytes, str):
            return []
        recs = decode_frame(frame_bytes, self.tip_src)
        self.frames += 1
        for x in recs:
            self._apply(x)
        return recs

    def _apply(self, x):
        k = x['kind']
        if k == 'sport':
            self.sports[x['id']] = x
        elif k == 'tipline':
            self.tiplines[x['id']] = x
        elif k == 'vars':
            # справочник приходит первым в каждом новом подключении: старое состояние выбрасываем,
            # как сайт (clearDB при переподключении)
            self.reset(full=False)
        elif k == 'server_date':
            self.server_ts = x['ts']
        elif k == 'initialized':
            self.initialized = True
        elif k == 'pm_country':
            self.countries[x['id']] = x
        elif k == 'pm_champ':
            self.pm_champs[x['id']] = x
        elif k == 'pm_event':
            self.pm_events[x['id']] = x
        elif k == 'pm_event_update':
            e = self.pm_events.setdefault(x['id'], {})
            e.update(x)
        elif k in ('pm_event_time', 'pm_event_add'):
            e = self.pm_events.get(x['id'])
            if e is not None:
                e.update({kk: vv for kk, vv in x.items() if kk not in ('kind', 'step')})
        elif k == 'pm_event_delete':
            self.pm_events.pop(x['id'], None)
            for lid in [lid for lid, L in self.pm_lines.items() if L['event_id'] == x['id']]:
                del self.pm_lines[lid]
        elif k in ('pm_line', 'pm_line_update', 'fill_line'):
            self.pm_lines[x['id']] = x
        elif k == 'fill_event':
            for lid in [lid for lid, L in self.pm_lines.items() if L['event_id'] == x['event_id']]:
                del self.pm_lines[lid]
        elif k == 'pm_line_delete':
            self.pm_lines.pop(x['id'], None)
        elif k == 'live_champ':
            self.live_champs[x['id']] = x
        elif k == 'live_event':
            self.live_events[x['id']] = x
        elif k == 'live_event_update':
            e = self.live_events.get(x['id'])
            if e is not None:
                e.update({kk: vv for kk, vv in x.items() if kk not in ('kind', 'step')})
        elif k == 'live_event_delete':
            self.live_events.pop(x['id'], None)
            for lid in [lid for lid, L in self.live_lines.items() if L['event_id'] == x['id']]:
                del self.live_lines[lid]
        elif k == 'live_line':
            self.live_lines[x['id']] = x
        elif k == 'live_line_delete':
            self.live_lines.pop(x['id'], None)

    # ---- выдача
    def _markets(self, lines, verified_only):
        mk = {}
        for L in sorted(lines, key=lambda L: L['id']):
            m = WL_MARKETS.get(L['tip'])
            if m is None or (verified_only and m[3] != 'dom'):
                continue
            key = market_key(L['tip'], L['koef'], L['favorite'], self.tiplines.get(L['tip']))
            if key is None:
                continue
            fam, line, order = key
            odds = _odds_out(L['V'], order)
            if any(o is not None for o in odds):
                mk[(fam, line)] = odds
        return mk

    def football(self, live=None, verified_only=False):
        """Список футбольных событий.

        live=None — все; False — только прематч; True — только лайв.
        verified_only=True — только рынки, сверенные с DOM (см. WL_MARKETS).
        Исход, закрытый на сайте (кф 1.0, на странице «-»), отдаётся как None.
        """
        by_ev_pm = {}
        for L in self.pm_lines.values():
            by_ev_pm.setdefault(L['event_id'], []).append(L)
        by_ev_live = {}
        for L in self.live_lines.values():
            by_ev_live.setdefault(L['event_id'], []).append(L)
        out = []
        if live is not True:
            for e in self.pm_events.values():
                if e['id'] in self.live_events or 'champ_id' not in e:
                    continue
                ch = self.pm_champs.get(e['champ_id'])
                if not ch or ch['sport_id'] != FOOTBALL_SPORT_ID:
                    continue
                out.append(self._ev(e, ch, False, by_ev_pm.get(e['id'], []), verified_only))
        if live is not False:
            for e in self.live_events.values():
                ch = self.live_champs.get(e.get('champ_id')) or self.pm_champs.get(e.get('champ_id'))
                if not ch or ch['sport_id'] != FOOTBALL_SPORT_ID:
                    continue
                out.append(self._ev(e, ch, True, by_ev_live.get(e['id'], []), verified_only))
        out.sort(key=lambda d: (d['start_ts'], d['id']))
        return out

    def _ev(self, e, ch, is_live, lines, verified_only):
        c = self.countries.get(ch.get('country_id'))
        d = {
            'id': e['id'], 'home': e.get('home', ''), 'away': e.get('away', ''),
            'start_ts': e.get('start_ts'), 'league': ch.get('name'),
            'country': c['name'] if c else None, 'champ_id': ch['id'], 'live': is_live,
            'url': 'https://winline.ru/stavki/event/%d' % e['id'],
            'markets': self._markets(lines, verified_only),
        }
        if is_live:
            d['score'] = e.get('score')
            d['time'] = e.get('time')
        else:
            d['count_add_line'] = e.get('count_add_line')    # на сайте «+N» = это число − 1
        return d


def event_plus_command(event_id, kind=0):
    """Два текстовых кадра, которыми сайт просит полную роспись события (по коду сайта, не проверено):
    'event.plus', затем base64([event_id u32 LE][kind u8]); kind 0 — все рынки, 1 — игроки, 2 — спецставки.
    Ответ — шаг 18/1118 (_parse_event_fill)."""
    import base64
    return ['event.plus', base64.b64encode(struct.pack('<IB', event_id, kind)).decode()]


class WinlineFeed:
    """Винлайн напрямую: страница линии футбола в браузере программы, кадры websocket data_ng → WinlineLine.
    Ничего не отправляет сама — подписку делает сайт. Интерфейс как у DirectFeed (для direct_values_for)."""
    name = 'Винлайн'
    SITE = 'https://winline.ru/stavki/sport/futbol'

    def __init__(self):
        self.page = None
        self.host = 'wss.winline.ru'
        self.page_url = ''
        self.line = WinlineLine()
        self.queue = []
        self.last_frame = 0
        self.last_poll = 0
        self.last_full = 0
        self.last_ok = None
        self.fails = 0
        self.version = None
        self.last_error = ''
        self.match_map = {}
        self.match_tried = {}
        self.events, self.miscs, self.factors, self.touched = {}, {}, {}, {}
        self._evs = {}
        self.started = 0

    def start(self, browser):
        self.page = browser.new_page(locale='ru-RU')

        def on_ws(ws):
            if 'data_ng' not in ws.url:
                return

            def rec(payload):
                if isinstance(payload, (bytes, bytearray)):
                    self.queue.append(bytes(payload))
            ws.on('framereceived', rec)
        self.page.on('websocket', on_ws)
        self.line = WinlineLine()
        self.queue = []
        self.started = time.time()
        self.page.goto(self.SITE, wait_until='domcontentloaded', timeout=90000)
        self.page.wait_for_timeout(5000)
        self.page_url = self.page.url
        log(f'Винлайн: сайт открыт, кадров получено {len(self.queue)}')

    def poll(self):
        try:
            self.page.wait_for_timeout(1)          # дать браузеру передать накопившиеся кадры
        except Exception as e:
            raise RuntimeError('страница Винлайна не отвечает: ' + str(e).splitlines()[0][:80])
        q, self.queue = self.queue, []
        bad = 0
        for fr in q:
            try:
                self.line.feed(fr)
            except Exception:
                bad += 1
        if q:
            self.last_frame = time.time()
        if bad and bad == len(q):
            raise RuntimeError(f'кадры Винлайна не разбираются ({bad} шт.) — сайт мог сменить формат')
        if time.time() - max(self.last_frame, self.started) > 90:
            self.line = WinlineLine()
            self.started = time.time()
            self.page.reload(wait_until='domcontentloaded', timeout=90000)     # поток встал — открыть заново
            raise RuntimeError('от Винлайна нет данных 90 с — страница открыта заново')
        if not self.line.pm_events:
            raise RuntimeError('Винлайн ещё не прислал линию')
        now = time.time()
        self._evs = {e['id']: e for e in self.line.football(live=False, verified_only=True) if e.get('start_ts')}
        self.last_poll = now
        self.last_ok = now
        self.last_full = self.started
        self.fails = 0

    def football(self):
        now = time.time()
        return [{'id': e['id'], 'team1': e['home'], 'team2': e['away'], 'startTime': e['start_ts'], '_wl': e}
                for e in self._evs.values() if e['start_ts'] > now + 60]

    def odds_of(self, eid):
        out = {}
        for key, odds in ((self._evs.get(eid) or {}).get('markets') or {}).items():
            if odds and all(isinstance(x, (int, float)) and x > 1 for x in odds):
                out[key] = list(odds)
        return out

    def match_odds(self, ev):
        m = ((self._evs.get(ev['id']) or {}).get('markets') or {}).get(('1x2', None)) or [None] * 3
        return list(m) + [None, None, None]       # двойной шанс у Винлайна не сверен — не показываем

    def event_url(self, ev):
        return ev['_wl']['url']

    match_to_oddsru = DirectFeed.match_to_oddsru


def settle_ah(margin, hcap, odds):
    """азиатская фора: margin — разница мячей своей команды, hcap — её фора; четверти делятся пополам"""
    frac = round((abs(hcap) * 4) % 2)
    parts = [hcap - 0.25, hcap + 0.25] if frac == 1 else [hcap]
    total = 0.0
    for h in parts:
        x = margin + h
        total += (odds - 1 if x > 0 else (0.0 if x == 0 else -1.0)) / len(parts)
    return total


def settle_one(market, outcome, line, odds, home, away):
    """Прибыль ставки в долях ставки (1 = ставка). Учитывает возврат и «азиатские» линии x.25/x.75."""
    if market == '1x2':
        res = 'П1' if home > away else ('П2' if away > home else 'Х')
        return odds - 1 if outcome == res else -1.0
    if market == 'ah':                         # line — фора хозяев
        if outcome.startswith('Ф1'):
            return settle_ah(home - away, line, odds)
        return settle_ah(away - home, -line, odds)
    goals = home if market == 'tt1' else away if market == 'tt2' else home + away
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
        self.pin_fair = {}       # id матча odds.ru -> честные цены Pinnacle с его сайта

    def snapshot(self):
        with self.lock:
            now = time.time()
            # пока прямая линия конторы жива, её цены с odds.ru не показываются вовсе: они отстают
            # (21.11: odds.ru 2.85 при 2.50 на сайте PARI), а матчи, которые не удалось сопоставить, всё равно не сверены
            alive = {n for n, f in self.status['feeds'].items() if n != 'Pinnacle' and f.get('last_ok')
                     and now - f['last_ok'] < 90}
            vals = [v for v in self.values.values() if v['bookmaker'] not in alive]
            vals += list(self.direct_values.values())
            vals.sort(key=lambda v: -v['ev'])
            rows = []
            for v in vals:
                m = self.matches.get(v['match_id'], {})
                if m and m.get('start', 0) < now + 60:
                    continue
                rows.append(dict(v, age=int(now - v['updated']), held=int(now - v['first_seen']),
                                 match=v.get('bk_title') or m.get('title', ''), league=m.get('league', ''),
                                 start=m.get('start_str', ''), start_ts=m.get('start', 0), url=m.get('url', ''),
                                 source=v.get('source', 'odds.ru'),
                                 pin_age=int(now - v['pin_ts']) if v.get('pin_ts') else None,
                                 bet=bet_info(dict(v, match=v.get('bk_title') or m.get('title', '')))[0],
                                 where=bet_info(dict(v, match=v.get('bk_title') or m.get('title', '')))[1],
                                 kind=bet_kind(event_of(v))[0], kc=bet_kind(event_of(v))[1],
                                 view=bet_view(event_of(v), v.get('outcome')),
                                 chance=round(chance_rel(v['odds'], v['fair'], v.get('p_win'), v.get('p_push'))[0], 4),
                                 rel=round(chance_rel(v['odds'], v['fair'], v.get('p_win'), v.get('p_push'))[1], 4)))
            tracked = len(self.matches)
            fresh = sum(1 for m in self.matches.values() if m.get('last_update') and now - m['last_update'] < 300)
            near = [now - m['last_update'] for m in self.matches.values()
                    if m.get('last_update') and 0 < m.get('start', 0) - now < 3 * 3600 and not m.get('no_pin')]
            st = dict(self.status, tracked=tracked, fresh=fresh, now=now_str(),
                      near=len(near), near_age=int(sum(near) / len(near)) if near else None,
                      near_max=int(max(near)) if near else None)
            marg = {}
            for (bk, market), (sm, n) in self.margins.items():
                marg.setdefault(bk, {})[MARKET_NAMES.get(market, market)] = [round(100 * sm / n, 1), n]
        return {'values': rows, 'status': st, 'margins': marg, 'mine': MY_BOOKMAKERS}


def now_str():
    return datetime.datetime.now(MSK).strftime('%d.%m %H:%M:%S')


STATE = State()
MY_BOOKMAKERS = []
STATS_DB = None
COLLECTOR = None     # работающий сборщик (для строки о Sofascore в окне и отчёта)
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
    for col in ('home_en', 'away_en'):
        try:
            con.execute(f'ALTER TABLE matches ADD COLUMN {col} TEXT')
        except sqlite3.OperationalError:
            pass
    # статистика сыгранных матчей (football-data.co.uk): счёт тайма, угловые, карточки, фолы, удары
    con.execute('CREATE TABLE IF NOT EXISTS stats (div TEXT, date TEXT, home TEXT, away TEXT, fthg INT, ftag INT,'
                ' hthg INT, htag INT, hc INT, ac INT, hy INT, ay INT, hf INT, af INT, hs INT, as_ INT, hst INT, ast INT,'
                ' PRIMARY KEY (div, date, home, away))')
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
    for t in ('cand', 'paper2'):
        try:
            con.execute(f'ALTER TABLE {t} ADD COLUMN fam TEXT')
        except sqlite3.OperationalError:
            pass                               # столбец уже есть
    for col in ('tsec', 'tdir', 'tupd'):        # таймер матча из лайва Фонбета (timerSeconds/Direction/UpdateTimestampMsec)
        try:
            con.execute(f'ALTER TABLE bk_scores ADD COLUMN {col} REAL')
        except sqlite3.OperationalError:
            pass
    try:                                       # страница матча у конторы — кнопка «к конторе» у идущего матча
        con.execute('ALTER TABLE paper2 ADD COLUMN bk_url TEXT')
    except sqlite3.OperationalError:
        pass
    for t in ('cand', 'paper2'):               # -84: когда снята цена закрытия Pinnacle (насколько она свежая к началу)
        try:
            con.execute(f'ALTER TABLE {t} ADD COLUMN close_ts REAL')
        except sqlite3.OperationalError:
            pass
    for col in ('res_h', 'res_a'):             # фактический счёт, по которому рассчитана ставка (голы/тайм/угловые)
        try:
            con.execute(f'ALTER TABLE paper2 ADD COLUMN {col} INT')
        except sqlite3.OperationalError:
            pass
    # счёт из лайва Фонбета/PARI (eventMiscs): матч, первый тайм, угловые — расчёт ставок любой лиги
    con.execute('CREATE TABLE IF NOT EXISTS bk_events (event_id INT PRIMARY KEY, match_id INT)')
    con.execute('CREATE TABLE IF NOT EXISTS bk_scores (match_id INT, part TEXT, s1 INT, s2 INT, comment TEXT,'
                ' ts REAL, tsec REAL, tdir REAL, tupd REAL, PRIMARY KEY (match_id, part))')
    # Sofascore / FotMob: счёт основного времени, тайм, угловые — запасной источник для расчёта
    con.execute('CREATE TABLE IF NOT EXISTS ext_scores (match_id INT PRIMARY KEY, src TEXT, ext_id TEXT, ft1 INT,'
                ' ft2 INT, ht1 INT, ht2 INT, c1 INT, c2 INT, done INT DEFAULT 0, tries INT DEFAULT 0, last_try REAL)')
    con.execute('CREATE TABLE IF NOT EXISTS sofa_link (match_id INT PRIMARY KEY, url TEXT, tries INT, last_try REAL)')
    # счёт и угловые идущих матчей с FotMob — когда у Фонбета в лайве угловых нет (владелец 22.11: «на FotMob вижу, в программе нет»)
    con.execute('CREATE TABLE IF NOT EXISTS ext_live (match_id INT PRIMARY KEY, ft1 INT, ft2 INT, c1 INT, c2 INT, ts REAL)')
    if 'fin' not in [r[1] for r in con.execute('PRAGMA table_info(ext_live)')]:
        con.execute('ALTER TABLE ext_live ADD COLUMN fin INT')     # -63: FotMob считает матч оконченным
    con.execute('CREATE INDEX IF NOT EXISTS pin_idx ON pin (match_id, market, ts)')
    con.execute('DELETE FROM pin WHERE ts < ?', (time.time() - 4 * 86400,))   # цены старше 4 дней не нужны
    con.commit()
    migrate_old_paper(con)
    return con


def pick_for_strategies(rows):
    """rows — строки «ставка в конторе»; возвращает [(способ, строка)]: по одной на событие и источник цены"""
    groups = {}
    for v in rows:
        pre, base = split_fam(event_of(v))
        if base not in SETTLEABLE:
            continue                           # первый тайм и угловые рассчитываются по лайву конторы или football-data
        groups.setdefault((v['match_id'], event_group(event_of(v)), v['src']), []).append(v)
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

PAGE = r"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Ставки — можно ставить сейчас</title>
<style>
*{box-sizing:border-box}
body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#0f1419;color:#e6e6e6;-webkit-text-size-adjust:100%;text-size-adjust:100%}
header{position:sticky;top:0;z-index:40;padding:12px 20px;background:#151c24;border-bottom:1px solid #253040;display:flex;gap:18px;align-items:center;flex-wrap:wrap}
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
.var>div:first-child{min-width:0}
.bl{white-space:nowrap;overflow:hidden;font-size:16px}.var.best .bl{font-size:18px}.bl .bet,.bl .odd{font-size:1em}
.star{color:#f2c230;font-size:12px;font-weight:700;margin-right:4px}
.kind{display:inline-block;font-size:13px;font-weight:800;padding:2px 8px;border-radius:5px;margin-bottom:3px;color:#111;background:#4cd18a}
.kind.h1{background:#5ab0ff}.kind.c{background:#f2c230}
.ch{font-size:20px;font-weight:800;color:#fff;text-align:right;white-space:nowrap}
.ch small{font-size:11px;color:#8696a6;font-weight:400;display:block;text-align:right}
.var .ev{font-size:15px;text-align:right}
.var .need{grid-column:1/4;margin-top:0;font-size:12px}
.var:not(.best){opacity:.85}
.bet{font-size:18px;font-weight:700}
.odd{font-size:18px;font-weight:800;color:#fff;margin-left:10px}.kf{font-size:.7em;font-weight:600;color:#8b98a5;margin-right:3px}
.ev{font-size:20px;font-weight:800;color:#5fd38d;white-space:nowrap}
.m{font-size:14px;margin-top:4px}
.m a{color:#cfe1ff;text-decoration:none}
.sm{font-size:12px;color:#8696a6;margin-top:3px}
.need{font-size:13px;margin-top:6px;color:#cfd8e3}
.src{font-size:12px;margin-top:3px}
.src.ok{color:#5fd38d}.src.warn{color:#d8a657}
.empty{padding:6px 14px 16px;color:#7d8b99;font-size:13px}
.sec{display:flex;align-items:center;gap:12px;background:#1b2430;border-radius:10px;padding:10px 14px;margin:14px 0 10px;cursor:pointer;user-select:none}
.sec:hover{background:#212c3a}.sec .bkn{min-width:26px;text-align:center;font-size:15px;font-weight:800;color:#fff;background:var(--c);border-radius:6px;padding:2px 7px}.sec .ar{color:#8b98a5;width:16px}.sec .kind{font-size:14px;margin:0;padding:3px 10px;min-width:96px;text-align:center;box-sizing:border-box}.sec .sn{color:#aab4be;font-size:14px}.sec .sn b{color:#fff}
.top{display:flex;justify-content:space-between;align-items:flex-start;gap:10px}.tl{min-width:0}
.mh .th{color:#9be15d}.mh .ta{color:#c69cff}.mh .td{color:#6b7785}
.lgl{display:flex;gap:6px;align-items:center;margin-top:4px;flex-wrap:wrap}
.lgl .cty{font-size:11px;font-weight:800;color:#0f1419;background:#9fb3c8;border-radius:4px;padding:1px 6px;text-transform:uppercase;letter-spacing:.3px}
.lgl .cty:empty{display:none}.lgl .lgn{font-size:13px;font-weight:700;color:#e6e6e6}
.mo{display:grid;grid-template-columns:repeat(3,auto);gap:2px 10px;font-size:12px;color:#8b98a5;padding:4px 8px;background:#141920;border-radius:6px;white-space:nowrap}
.mo b{color:#e6e6e6}.mo .h b{color:#9be15d}.mo .a b{color:#c69cff}
.bet{background:#232a34;border-radius:8px;padding:6px 10px 8px;margin-top:10px;border:1px solid #2e3744}
.mkt{font-size:11px;color:#7fd1b9;font-weight:700;text-transform:uppercase;letter-spacing:.3px}
a.btn{display:flex;justify-content:space-between;align-items:center;gap:10px;background:#353c48;border-radius:6px;padding:8px 12px;margin-top:6px;border-left:4px solid #5d6876;text-decoration:none;color:#e6e6e6}
a.btn:hover{background:#3d4553}a.btn.h{border-left-color:#9be15d}a.btn.a{border-left-color:#c69cff}a.btn.best{box-shadow:0 0 0 2px #f2c230 inset}
a.btn .nm{font-size:15px;white-space:nowrap;overflow:hidden;min-width:0;text-decoration:underline;text-decoration-color:#ffffff33;text-underline-offset:3px}
a.btn.h .nm{color:#9be15d}a.btn.a .nm{color:#c69cff}a.btn .od{font-size:16px;font-weight:800;flex:none}
.info{display:flex;flex-wrap:wrap;gap:2px 12px;font-size:12px;color:#9aa6b2;margin:5px 2px 0}.info b{color:#e6e6e6}.info .evx{color:#5fd38d;font-weight:800}
.okm{color:#5fd38d;font-weight:800;font-size:14px}
/* -77 (владелец 22.11: «обведи цифры чёрной рамкой, чтобы читались лучше»): белый текст на цветных плашках — с чёрным контуром */
.sec .bkn,.livebtn,.bkbtn{text-shadow:-1px -1px 0 #000,1px -1px 0 #000,-1px 1px 0 #000,1px 1px 0 #000,0 0 2px #000}.bkbtn{white-space:nowrap}
.lvr td{border:none!important;background:none!important;padding:0 0 4px!important;text-align:center}.livebtn{display:inline-block;margin-left:40px;vertical-align:2px;font-size:13px;line-height:18px;background:#e5484d;color:#fff;font-weight:700;padding:3px 12px;border-radius:12px;cursor:pointer;text-decoration:none!important}.livebtn.off{background:#3a4250;color:#9aa4b2;cursor:default}
.updon{display:inline-block;background:#c9a400;color:#111;padding:7px 14px;border-radius:6px;font-size:14px;animation:updb 1.2s ease-in-out infinite}@keyframes updb{50%{opacity:.6}}
.updok{display:inline-block;background:#2f7d4f;color:#fff;padding:7px 14px;border-radius:6px;font-size:14px}
.ptab .sh{display:none}
/* -79: вёрстка под телефон (владелец 22.11) */
@media(max-width:700px){
 header{padding:8px 10px;gap:8px}header h1{font-size:18px}main{padding:8px!important}
 .sec{flex-wrap:wrap;gap:6px}.sec .kind{min-width:auto}
 .pp{padding:10px!important}.pp h2{font-size:15px}
 .pp .ptab th,.pp .ptab td{padding:6px 3px;font-size:13px}.pp .ptab th{font-size:10px}.ptab tr.sub td:first-child{padding-left:14px}
 .ptab .gn{display:none}.ptab .lg{display:none}.ptab .sh{display:inline}.pp .ptab td{font-size:13px}.ptab td:last-child{white-space:nowrap;font-size:12px}
 .ptab tr.sub td:first-child{font-size:12px}.ptab .num{min-width:14px;padding:1px 3px}.ptab tr.grp .kind.ks{min-width:0;font-size:11px;padding:2px 6px}
 #pop{padding:0}.mbox{max-height:100vh;height:100vh;border-radius:0}
 .mt tr:first-child{display:none}.mt tr{display:block;border-bottom:1px solid #2a3542;padding:6px 4px}
 .mt td{display:inline-block;border:0!important;padding:2px 6px!important;vertical-align:middle}
 .mt td:first-child,.mt td.bcell,.mt td.rcell{display:block;width:auto;max-width:none}.mt tr.mg td{display:block}
 .bet .bl{font-size:14px}.mo{font-size:11px}
 .pp{padding:8px!important}.pp .ptab th,.pp .ptab td{padding:5px 2px}.ptab .chev{width:12px}
 .ptab tr.sub td:first-child{padding-left:8px;white-space:nowrap}.ptab tr.grp td:first-child{white-space:nowrap}
 .ptab tr.grp .kind.ks{font-size:10px;padding:2px 4px;min-width:0!important}
 .ptab th{width:auto!important}
 header{position:static}.livebtn{margin-left:8px}header h1{font-size:16px}header .st{font-size:11px}
}
/* -80: телефон — три колонки контор, короткие карточки */
.mcols{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:5px;align-items:start;margin-bottom:6px}
.mcol{min-width:0}
.mch{font-size:13px;font-weight:800;color:var(--c);border-bottom:3px solid var(--c);padding:0 2px 3px;margin-bottom:5px;white-space:nowrap;overflow:hidden}
.mem{font-size:11px;color:#6b7785;padding:4px 2px}
.mc{background:#1a232d;border-radius:7px;padding:6px 5px 5px;margin-bottom:5px}.mc.stale{opacity:.55}
.mtm{display:block;text-decoration:none;font-size:12px;font-weight:700;line-height:15px}
.mtm span{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.mtm .th{color:#9be15d}.mtm .ta{color:#c69cff}
.mw{font-size:10px;color:#8696a6;margin:1px 0 2px}
.mcol a.bet.mb{display:block;background:#353c48;border-radius:6px;padding:3px 5px 4px;margin:4px 0 0;border:0;border-left:3px solid #5d6876;text-decoration:none;color:#e6e6e6;font-size:inherit;font-weight:400}
.mcol a.bet.mb.h{border-left-color:#9be15d}.mcol a.bet.mb.a{border-left-color:#c69cff}.mcol a.bet.mb.best{box-shadow:0 0 0 2px #f2c230 inset}
.mcol a.bet.mb.nbet{box-shadow:0 0 0 2px #ffd400 inset,0 0 8px #ffd40088}
.mk{font-size:9px;font-weight:800;color:#7fd1b9;letter-spacing:.2px;white-space:nowrap;overflow:hidden}.mk .star{font-size:10px;margin:0}
.mr{display:flex;justify-content:space-between;align-items:baseline;gap:4px}
.mbt{font-size:14px;font-weight:700;white-space:nowrap;overflow:hidden;min-width:0}.mod{flex:none}.mb.h .mbt{color:#9be15d}.mb.a .mbt{color:#c69cff}.mod{font-size:14px;font-weight:800;color:#fff}
.mi{display:flex;gap:4px;align-items:center;font-size:11px;margin-top:1px}.mi .evx{color:#5fd38d;font-weight:800}.mi .chp{padding:0 4px;font-size:10px}
td.chg,tr.chg>td{background:#ffd40026!important;box-shadow:inset 0 0 0 2px #ffd400aa!important;animation:chgf 1.2s ease-in-out infinite}@keyframes chgf{50%{background:#ffd40059!important}}
.bet.nbet{border:2px solid #ffd400;box-shadow:0 0 12px #ffd40055}.newb2{font-size:11px;font-weight:800;color:#111;background:#ffd400;border-radius:4px;padding:1px 6px;animation:blink 1.2s ease-in-out infinite}
.ptab .num{cursor:pointer;display:inline-block;min-width:22px;padding:1px 6px;border-radius:5px;text-decoration:underline;text-decoration-color:#ffffff40;text-underline-offset:3px}.ptab .num:hover{background:#3a4a5e}
.fact{font-size:12px;color:#aab4be;margin-top:2px}.livem{color:#ff6b6b;font-weight:700;font-size:13px}.fact b{color:#fff}
#pop{display:none;position:fixed;inset:0;background:#000a;z-index:50;align-items:flex-start;justify-content:center;padding:40px 16px}
.mbox{background:#131a22;border:1px solid #2e3744;border-radius:12px;max-width:1100px;width:100%;max-height:85vh;display:flex;flex-direction:column}
.mhd{display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border-bottom:1px solid #2a3542;font-size:16px}
.mx{cursor:pointer;font-size:20px;color:#8b98a5;padding:0 6px}.mx:hover{color:#fff}.mbody{overflow:auto;padding:6px 12px 12px}
.mt{width:100%;border-collapse:collapse;font-size:14px}.mt th{font-size:12px;color:#8b98a5;text-align:left;padding:6px 8px;border-bottom:1px solid #2a3542}
.mt td{padding:7px 8px;border-bottom:1px solid #1e2732;vertical-align:top}.mt .th{color:#9be15d;font-weight:600}.mt .ta{color:#c69cff;font-weight:600}
.mt tr.mg td{background:#1b2430;padding:6px 8px;border-bottom:none}.lft{color:#ffd400;font-weight:700;font-size:13px}
.bt{font-weight:700}.mlink{text-decoration:underline;text-decoration-color:#ffffff40;text-underline-offset:3px}
.mt td.bcell{white-space:nowrap}.mt td.rcell{width:120px;max-width:140px;font-size:13px}.mt .bkbtn{margin-left:0}
a.bkbtn,span.bkbtn{display:inline-block;margin-left:6px;font-size:11px;font-weight:800;color:#fff;background:var(--c);border-radius:5px;padding:1px 7px;text-decoration:none;vertical-align:1px}.bt.h{color:#9be15d}.bt.a{color:#c69cff}
a.rbtn{display:inline-block;background:#2b6cb0;color:#fff;font-weight:700;border-radius:8px;padding:8px 14px;text-decoration:none}a.rbtn:hover{background:#3182ce}
.info .hich{background:#ffd400;color:#111;border-radius:5px;padding:0 6px;font-weight:700}.info .hich b{color:#111}
.info .loch{background:#e5484d;color:#fff;border-radius:5px;padding:0 6px;font-weight:700}.info .loch b{color:#fff}
.info .midch{background:#2f3d4f;color:#c9d6e3;border-radius:5px;padding:0 6px}
.chp{border-radius:5px;padding:1px 7px;font-weight:700}.chp.hich{background:#ffd400;color:#111}.chp.loch{background:#e5484d;color:#fff}.chp.midch{background:#2f3d4f;color:#c9d6e3}.bad2{color:#ffb454;font-weight:700}
.newb{font-size:12px;font-weight:800;color:#111;background:#ffd400;border-radius:6px;padding:3px 9px;animation:blink 1.2s ease-in-out infinite}
@keyframes blink{50%{opacity:.45}}
.pp{background:#131a22;border-radius:10px;padding:12px 16px;margin-bottom:16px;overflow-x:auto}
.pp h2{font-size:16px;margin:0 0 6px}
.big{font-size:15px}
.pos{color:#5fd38d}.neg{color:#ff6b6b}.mu{color:#6b7785}
.ptab{width:100%;border-collapse:collapse;font-size:15px;margin-top:6px}
.pp .ptab th{font-size:12px;color:#8b98a5;font-weight:600;text-align:center;padding:6px 8px;border-bottom:1px solid #2a3542}
.pp .ptab td{font-size:15px;padding:8px 8px;text-align:center}
.ptab th:first-child,.ptab td:first-child{text-align:left}.ptab td:last-child{text-align:right;font-weight:700}.ptab th:last-child{text-align:right}
.ptab tr.grp td{background:#1e2834;font-weight:700;cursor:pointer;border-top:1px solid #2f3b49}.ptab tr.grp:hover td{background:#243040}
.ptab .chev{display:inline-block;width:18px;color:#8b98a5;font-size:13px}.ptab .gn{font-size:12px;color:#8b98a5;font-weight:400}
.pp .ptab tr.sub td{background:#141b23;font-size:14px}.ptab tr.sub td:first-child{padding-left:34px;color:#cdd5dd}
.ptab td.w{color:#5fd38d;font-weight:700}.ptab td.l{color:#ff6b6b;font-weight:700}.ptab td.p{color:#c9d1d9}
.ptab td:nth-child(3),.ptab td:nth-child(4),.ptab td:nth-child(5),.ptab th:nth-child(3),.ptab th:nth-child(4),.ptab th:nth-child(5){box-shadow:inset 0 0 0 999px rgba(90,176,255,.06)}
.ptab td:nth-child(2),.ptab th:nth-child(2),.ptab td:nth-child(3),.ptab th:nth-child(3),.ptab td:nth-child(6),.ptab th:nth-child(6),.ptab td:nth-child(8),.ptab th:nth-child(8){border-left:2px solid #34414f}
/* -87 (владелец 22.11: «эти поля сделать уже»): колонки исходов уже, вид ставки забирает остальное; «Расчёт» — жёлтым */
.ptab th:nth-child(2){width:110px}.ptab th:nth-child(3),.ptab th:nth-child(4),.ptab th:nth-child(5){width:105px}.ptab th:nth-child(6),.ptab th:nth-child(7){width:85px}.ptab th:nth-child(8){width:120px}
.ptab td.stl{color:#ffd400;font-weight:700}
.ptab tr.taxr td:nth-child(2){border-left:2px solid #34414f}.ptab tr.taxr td:nth-child(3){border-left:2px solid #34414f;box-shadow:none}
.pp .ptab tr.tot td{border-top:2px solid #3a4756;font-weight:800;font-size:16px;background:#1b2430}
.pp .ptab tr.taxr td{background:#161d26;font-size:14px;color:#aab4be;border-top:1px dashed #34414f}.pp .ptab tr.taxr td.taxn{text-align:left;font-size:12px;color:#7d8b99}.pp .ptab tr.taxr td:last-child{font-size:15px}
.kind.ks{font-size:11px;padding:2px 7px;margin:0;vertical-align:1px;color:#111}
.ptab tr.grp .kind.ks{min-width:78px;text-align:center;box-sizing:border-box;display:inline-block}
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
<div id="pop"></div><main><div id="paper"></div><div id="cols"></div>
<details><summary>Подробнее: работа программы, маржа контор, разведка, Telegram</summary>
<p><a class="rbtn" href="/api/report" download>Скачать отчёт для разработки</a> <span class="st">— файл otchet_….zip появится в «Загрузках»; пришлите его в чат Claude</span></p>
<p class="st">Telegram: <span id="tgst">—</span><span id="tgform"> · ключ бота из @BotFather: <input id="tgkey" style="width:340px">
<button class="lbtn" onclick="tgc()">Подключить Telegram</button></span></p>
<p class="st">Вход с телефона: <span id="phst">—</span><span id="phform"> · пароль (от 10 знаков): <input id="phpass" type="password" style="width:200px">
<button class="lbtn" onclick="phset()">Сохранить пароль</button> <span id="phmsg"></span></span></p><div id="more"></div></details></main>
<script>
const PAGE_VERSION='__VERSION__';
const COLORS={'Фонбет':'#e80024','PARI':'#00ad9b','Винлайн':'#fa6400'};   // цвета с сайтов контор (снимки разведки 21.11)
function fmt(s){if(s==null)return '—';if(s<60)return s+' с';if(s<3600)return Math.floor(s/60)+' мин';return Math.floor(s/3600)+' ч '+Math.floor(s%3600/60)+' мин'}
function when(ts){const d=new Date(ts*1000),n=new Date();const hm=d.toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit',timeZone:'Europe/Moscow'});
 const dd=d.toLocaleDateString('ru-RU',{timeZone:'Europe/Moscow'}),nd=n.toLocaleDateString('ru-RU',{timeZone:'Europe/Moscow'});
 const left=Math.round((ts*1000-n)/60000);const l=left<60?('через '+left+' мин'):('через '+Math.floor(left/60)+' ч '+left%60+' мин');
 return (dd===nd?'сегодня ':dd.slice(0,5)+' ')+hm+' · '+l}
function betText(v){const t=(v.match||'').split(' — ');const mn=v.market_name||'';const i=mn.indexOf(': ');
 const pre=i>=0?mn.slice(0,i)+': ':'';const base=i>=0?mn.slice(i+2):mn;
 if(base==='1Х2'){if(v.outcome==='П1')return pre+'Победа: '+(t[0]||'хозяева');if(v.outcome==='П2')return pre+'Победа: '+(t[1]||'гости');return pre+'Ничья'}
 const f=v.outcome.match(/Ф([12]) \(([-+\d.]+)\)/);if(f)return pre+'Фора '+(f[1]==='1'?(t[0]||'хозяев'):(t[1]||'гостей'))+' '+f[2];
 const m=v.outcome.match(/(Больше|Меньше) \(([\d.]+)\)/);
 if(m){const bm=m[1]==='Больше'?'больше ':'меньше ';const what=pre==='Угловые: '?'Угловые ':'Голы ';const p2=pre==='Угловые: '?'':pre;
  if(base==='Инд. тотал хозяев')return p2+what+(t[0]||'хозяев')+' '+bm+m[2];
  if(base==='Инд. тотал гостей')return p2+what+(t[1]||'гостей')+' '+bm+m[2];return pre+'Тотал '+bm+m[2]}
 return mn+': '+v.outcome}
// у каждой ставки: ✓ — кф с сайта конторы и цена Pinnacle свежие; ⚠ — что именно не так
function okMark(v){const p=[];
 if(v.source!=='сайт')p.push('кф с odds.ru — сверить');else if(v.age>180)p.push('кф не обновлялся '+fmt(v.age));
 if(v.pin_age==null)p.push('нет цены Pinnacle');else if(v.pin_age>180)p.push('Pinnacle '+fmt(v.pin_age)+' назад');
 return p.length?'<span class="bad2">⚠ '+p.join(' · ')+'</span>':'<span class="okm" title="кф с сайта конторы и цена Pinnacle свежие">✓</span>'}
// -70 (владелец 22.11: «нажимаю на кнопку — не понимаю, запустилось обновление или нет»): сразу после нажатия — жёлтая
// мигающая надпись с секундомером; пока программа перезапускается, надпись остаётся; после — 20 с зелёное «✓ Обновлено».
let UPDT=0;try{UPDT=+localStorage.getItem('updt')||0}catch(e){}
function startUpdate(v){UPDT=Date.now();try{localStorage.setItem('updt',UPDT);localStorage.setItem('updto',v)}catch(e){}
 showUpdating();post('/api/update')}
function showUpdating(){const u=document.getElementById('upd');const sec=Math.round((Date.now()-UPDT)/1000);
 u.innerHTML='<span class="updon" title="программа перезапускается, окно обновится само (обычно до минуты)">⏳ Обновляюсь… '+sec+' с</span>'}
async function tick(){
 const updating=UPDT&&Date.now()-UPDT<5*60000;
 if(updating)showUpdating();
 try{
  const r=await fetch('/api/state',{cache:'no-store'});const d=await r.json();const s=d.status;
  if(s.version!==PAGE_VERSION){try{if(UPDT)localStorage.setItem('updok',s.version);localStorage.removeItem('updt')}catch(e){}location.reload();return}
  const u=document.getElementById('upd');
  let okv=null;try{okv=localStorage.getItem('updok')}catch(e){}
  if(okv&&okv===s.version){u.innerHTML='<span class="updok">✓ Обновлено</span>';
   setTimeout(()=>{try{localStorage.removeItem('updok')}catch(e){}},20000)}
  else if(s.restarting||updating)showUpdating();
  else if(s.update_available)u.innerHTML='<button class="ubtn" onclick="startUpdate(\''+s.update_available+'\')">Обновить до версии '+s.update_available+'</button>';
  else u.innerHTML='<span class="ver">версия '+s.version+'</span> <button class="lbtn" onclick="post(\'/api/check_update\');this.textContent=\'проверяю…\'">проверить обновления</button>';
  if(!s.restarting&&!updating&&UPDT){UPDT=0;try{localStorage.removeItem('updt')}catch(e){}}
  let st='обновлено '+s.now+' · матчей в работе '+s.tracked;
  const pf=s.feeds&&s.feeds['Pinnacle'];
  if(pf&&pf.last_ok&&(Date.now()/1000-pf.last_ok)<120)st+=' · <span class="pos">честная цена: Pinnacle с его сайта, сопоставлено матчей '+pf.matched+'</span>';
  else if(!pf||(!pf.last_ok&&!pf.error))st+=' · Pinnacle: подключаюсь…';
  else st+=' · <span class="bad">Pinnacle не отвечает'+(pf&&pf.error?': '+pf.error:'')+' — проверьте, включён ли VPN</span>';
  if(s.errors.length)st+=' · <span class="bad">ошибка: '+s.errors[s.errors.length-1]+'</span>';
  document.getElementById('st').innerHTML=st;
  const thr=parseFloat(document.getElementById('thr').value||0)/100, mx=parseFloat(document.getElementById('mx').value||99);
  const rows=d.values.filter(v=>v.ev>=thr&&v.odds<=mx&&d.mine.includes(v.bookmaker));
  let h='';
  const ORD=['Фонбет','PARI','Винлайн'],oi=b=>{const i=ORD.indexOf(b);return i<0?9:i};   // Фонбет и PARI — рядом (владелец 21.11)
  const bkCols=[...d.mine].sort((a,c)=>oi(a)-oi(c));
  const main=v=>/^(1x2|total|ah|tt1|tt2|match_winner|total_points)$/.test(v.market||'')?1:0;
  const vw=v=>v.view||['m','',v.market_name||'',9];
  // ★ лучший — как раньше: в матче у конторы лучшая по надёжности среди ставок бумаги
  const best=new Set();const byBM={};for(const v of rows)(byBM[v.bookmaker+'|'+v.match_id]=byBM[v.bookmaker+'|'+v.match_id]||[]).push(v);
  for(const vs of Object.values(byBM)){vs.sort((x,y)=>(main(y)-main(x))||(y.rel-x.rel));if(vs.length>1&&main(vs[0]))best.add(vs[0])}
  const esc=t=>String(t==null?'':t).replace(/&/g,'&amp;').replace(/</g,'&lt;');
  const SECS=[['m','МАТЧ'],['h1','1-Й ТАЙМ'],['c','УГЛОВЫЕ']];
  for(const [sk,sn] of SECS){
   const srows=rows.filter(v=>vw(v)[0]===sk);const closed=!!SCOL[sk];
   const keys=srows.map(v=>v.bookmaker+'|'+v.match_id+'|'+v.market_name+'|'+v.outcome);
   if(!closed){                                     // раздел открыт: чего не было среди увиденных — «НОВАЯ» на 10 мин
    if(SEEN[sk])for(const k of keys)if(!SEEN[sk].includes(k)&&!NEWK[k])NEWK[k]=Date.now();
    SEEN[sk]=keys}
   const fresh=closed&&keys.some(k=>!(SEEN[sk]||[]).includes(k));
   h+='<div class="sec" onclick="scol(\''+sk+'\')"><span class="ar">'+(closed?'▸':'▾')+'</span><span class="kind '+sk+'">'+sn+'</span><span class="sn">доступно ставок:</span>'+bkCols.map(b=>'<span class="bkn" style="--c:'+(COLORS[b]||'#7fb6ff')+'" title="'+b+'">'+srows.filter(v=>v.bookmaker===b).length+'</span>').join('')+(closed?'<span class="sn">свёрнуто</span>':'')+(fresh?'<span class="newb">НОВОЕ</span>':'')+'</div>';
   if(closed)continue;
   const PH=isPhone();
   h+=PH?'<div class="mcols">':'<div class="cols">';
   for(const b of bkCols){
    const c=COLORS[b]||'#7fb6ff';const rs=srows.filter(v=>v.bookmaker===b);
    const byM={};for(const v of rs)(byM[v.match_id]=byM[v.match_id]||[]).push(v);
    if(PH){h+=phoneCol(b,c,rs,byM,best,s.feeds[b]);continue}
    // -62 (владелец 22.11: «порядок по их появлению: появилась — осталась сверху»): свежие сверху — и карточки, и ставки в них
    // (held — сколько секунд ставка держится; после перезапуска программы у всех одинаково — тогда по надёжности)
    const hcmp=(a,b)=>Math.abs(a-b)<5?0:a-b;
    const cards=Object.values(byM).map(vs=>vs.sort((x,y)=>hcmp(x.held||0,y.held||0)||(vw(x)[3]-vw(y)[3])||(y.rel-x.rel))).sort((x,y)=>hcmp(Math.min(...x.map(v=>v.held||0)),Math.min(...y.map(v=>v.held||0)))||(Math.max(...y.map(v=>v.rel))-Math.max(...x.map(v=>v.rel))));
    const f=s.feeds[b];let feed;
    const pins=rs.map(v=>v.pin_age).filter(x=>x!=null),ages=rs.map(v=>v.age);
    const chk=(ages.length?' · проверены '+fmt(Math.max(...ages))+' назад':'')+(pins.length?' · Pinnacle до '+fmt(Math.max(...pins))+' назад':'');
    if(f&&f.last_ok&&(Date.now()/1000-f.last_ok)<90)feed='<div class="feed ok">✓ цены прямо с сайта конторы'+chk+'</div>';
    else feed='<div class="feed warn">цены с odds.ru, могут отставать — сверить на сайте конторы'+(f&&f.error?'<br>прямая линия не работает: '+esc(f.error):'')+'</div>';
    h+='<div class="col" style="--c:'+c+'"><div class="colh"><span class="bk">'+b+'</span><span class="cnt">'+(cards.length?cards.length+' матч.':'')+'</span></div>'+feed;
    if(!cards.length)h+='<div class="empty">Сейчас подходящих ставок нет</div>';
    for(const vs of cards){
     const v0=vs[0];const direct=v0.source==='сайт';
     const age=Math.max(...vs.map(v=>v.age));const pa=vs.map(v=>v.pin_age).filter(x=>x!=null);const pin=pa.length?Math.max(...pa):null;
     const old=age>180||(pin!=null&&pin>180);
     const tm=(v0.match||'').split(' — ');const url=v0.bk_url||(v0.url+'bet/');
     const lg=(v0.league||'').split(': ');
     const mo=v0.mo||[];const o=(k,lab,cl)=>mo[k]?'<span class="'+cl+'">'+lab+' <b>'+Number(mo[k]).toFixed(2)+'</b></span>':'<span class="'+cl+'">'+lab+' <b>—</b></span>';
     h+='<div class="card'+(old?' stale':'')+'"><div class="top"><div class="tl"><div class="mh"><a href="'+url+'" target="_blank"><span class="th">'+esc(tm[0])+'</span> <span class="td">—</span> <span class="ta">'+esc(tm[tm.length-1])+'</span></a></div>'
      +'<div class="lgl"><span class="cty">'+esc(lg.length>1?lg[0]:'')+'</span>'+(lg.length>1?'<span class="lgn">'+esc(lg.slice(1).join(': '))+'</span>':'<span class="lgn">'+esc(lg[0])+'</span>')+'</div>'
      +'<div class="sm">'+when(v0.start_ts)+'</div></div>'
      +(mo.some(x=>x)?'<div class="mo">'+o(0,'П1','h')+o(1,'Х','')+o(2,'П2','a')+(mo[3]||mo[4]||mo[5]?o(3,'1Х','h')+o(4,'12','')+o(5,'Х2','a'):'')+'</div>':'')+'</div>';
     for(const v of vs){
      const [,side,title]=vw(v);const star=best.has(v);
      const nw=isNew(v);
      h+='<div class="bet'+(nw?' nbet':'')+'"'+(nw?' data-nk="'+esc(nkey(v)).replace(/"/g,'&quot;')+'"':'')+'><div class="mkt">'+(nw?'<span class="newb2">НОВАЯ</span> ':'')+esc(title)+(star?' <span class="star">★ лучший</span>':'')+'</div>'
       +'<a class="btn '+side+(star?' best':'')+'" href="'+url+'" target="_blank" title="открыть матч на сайте конторы"><span class="nm">'+esc(v.bet||betText(v))+'</span><span class="od">'+Number(v.odds).toFixed(2)+'</span></a>'
       +'<div class="info"><span class="'+(v.chance>=0.55?'hich':(v.chance<0.40?'loch':'midch'))+'" title="шанс: до 40% — красная, 40–55% — спокойная, от 55% — жёлтая">шанс <b>'+Math.round(v.chance*100)+'%</b></span><span class="evx">+'+(v.ev*100).toFixed(1)+'%</span><span>брать от <b>'+(v.p_win?(1+thr-(v.p_push||0))/v.p_win:v.fair*(1+thr)).toFixed(2)+'</b></span><span>честная '+v.fair.toFixed(2)+'</span>'+okMark(v)+'</div></div>'}
     h+='</div>'}
    h+='</div>'}
   h+='</div>'}
  for(const k in NEWK)if(Date.now()-NEWK[k]>600000||(NEWV[k]&&Date.now()-NEWV[k]>3000))delete NEWK[k];
  for(const k in NEWV)if(!NEWK[k]&&Date.now()-NEWV[k]>600000)delete NEWV[k];
  try{localStorage.setItem('seen',JSON.stringify(SEEN));localStorage.setItem('newk',JSON.stringify(NEWK));localStorage.setItem('newv',JSON.stringify(NEWV))}catch(e){}
  document.getElementById('cols').innerHTML=h;watchNew();
  // ставка — одной строкой: длинная уменьшается, пока не поместится
  for(const b of document.querySelectorAll('.bl,.btn .nm,.mcol .mbt,.mcol .mtm span')){let f=parseFloat(getComputedStyle(b).fontSize);while(b.scrollWidth>b.clientWidth+1&&f>11){f-=0.5;b.style.fontSize=f+'px'}}
  renderPaper(d.paper);
  let m='<p class="st">'+[ 'матчей в работе '+s.tracked+' (обновлены за 5 мин: '+s.fresh+')','список матчей обновлён '+(s.events_updated||'—'),s.cycle_info,(s.near?'Pinnacle по матчам ближайших 3 ч ('+s.near+'): в среднем '+fmt(s.near_age)+' назад, самый старый '+fmt(s.near_max):''),(s.avg_request?'ответ odds.ru в среднем '+s.avg_request+' с':'')].filter(x=>x).join(' · ')+'</p>';
  if(s.errors.length)m+='<p class="st">последние ошибки:<br>'+s.errors.join('<br>')+'</p>';
  const sf=d.paper&&d.paper.sofa;if(sf)m+='<p class="st">Ссылки на статистику (FotMob / Sofascore): найдено '+sf.found+' из '+sf.need+' матчей с бумажными ставками, не нашлось '+sf.notfound+(sf.noname?', без английских названий (искать не по чему) '+sf.noname:'')+(sf.error?' · <span class="bad">Sofascore: '+sf.error+'</span>':'')+'</p>';
  if(s.nbk&&s.nbk.length)m+='<p class="st">Проверка контор (пускает ли сайт программу): '+s.nbk.map(x=>'<b>'+x[0]+'</b> — '+x[1]).join(' · ')+'</p>';
  const sx=s.stats;m+='<p class="st">Статистика матчей (football-data): '+(sx?(sx.rows?('матчей в базе '+sx.rows):'')+(sx.error?' <span class="bad">не все лиги скачались: '+sx.error+'</span>':''):'загружается…')+'</p>';
  const ph=s.prohod||{},pe=document.getElementById('phst');
  pe.innerHTML=ph.sost==='работает'?'<span class="pos">работает</span> · ссылку пришлёт бот по команде /site'+(ph.link?' · <span class="mu">'+ph.link+'</span>':'')+' · <a href="#" onclick="document.getElementById(\'phform\').style.display=\'\';return false">сменить пароль</a>'
   :((ph.sost||'выключен')+(ph.why?' — '+ph.why:''));
  if(ph.sost==='работает'&&!PHEDIT)document.getElementById('phform').style.display='none';
  const tg=s.telegram||{};const te=document.getElementById('tgst');
  te.innerHTML=tg.ok===true?'<span class="pos">'+tg.text+'</span>':(tg.ok===false?'<span class="bad">'+tg.text+'</span>':(tg.text||'не подключён'));
  document.getElementById('tgform').style.display=(tg.ok===true||(tg.text||'').startsWith('проверяю')||(tg.text||'').startsWith('ключ подходит'))?'none':'';
  m+=s.razvedka?'<p class="st">Разведка контор: '+s.razvedka+'</p>':'<p><button class="lbtn" onclick="post(\'/api/razvedka\')">Разведка контор (≈4 мин)</button></p>';
  const bks=Object.keys(d.margins||{}).sort((a,b)=>(d.mine.includes(b)-d.mine.includes(a))||a.localeCompare(b));
  if(bks.length){m+='<table><tr><th>Маржа контор (с запуска программы)</th><th>1Х2</th><th>Тоталы</th></tr>';
   for(const b of bks){const x=d.margins[b];const c=y=>y?y[0]+'% <span class="st">('+y[1]+')</span>':'—';m+='<tr><td>'+(d.mine.includes(b)?'<b>'+b+'</b>':b)+'</td><td>'+c(x['1Х2'])+'</td><td>'+c(x['Тотал'])+'</td></tr>'}
   m+='</table>'}
  document.getElementById('more').innerHTML=m;
 }catch(e){document.getElementById('st').innerHTML=UPDT?'<span class="st">программа перезапускается после обновления — окно вернётся само</span>':'<span class="bad">нет связи с программой: она перезапускается или закрыта (чёрное окно Stavki)</span>'}
}
// -80 (владелец 22.11): на телефоне конторы — тремя колонками, карточки короче и ближе к квадрату:
// команды, начало, вид ставки, ставка, кф, перевес, шанс. Нажатие на ставку — матч на сайте конторы.
const isPhone=()=>window.matchMedia&&matchMedia('(max-width:700px)').matches;
function whenS(ts){const d=new Date(ts*1000),n=new Date();const left=Math.round((ts*1000-n)/60000);
 if(left<120)return 'через '+left+' мин';
 const hm=d.toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit',timeZone:'Europe/Moscow'});
 const dd=d.toLocaleDateString('ru-RU',{timeZone:'Europe/Moscow'}),nd=n.toLocaleDateString('ru-RU',{timeZone:'Europe/Moscow'});
 return (dd===nd?'':dd.slice(0,5)+' ')+hm}
const shortBet=o=>String(o||'').replace(/^Больше \(([-\d.]+)\)$/,'Б $1').replace(/^Меньше \(([-\d.]+)\)$/,'М $1');
function phoneCol(b,c,rs,byM,best,f){
 const esc=t=>String(t==null?'':t).replace(/&/g,'&amp;').replace(/</g,'&lt;');
 const vw=v=>v.view||['m','',v.market_name||'',9];
 const hcmp=(a,b)=>Math.abs(a-b)<5?0:a-b;
 const cards=Object.values(byM).map(vs=>vs.sort((x,y)=>hcmp(x.held||0,y.held||0)||(vw(x)[3]-vw(y)[3])||(y.rel-x.rel))).sort((x,y)=>hcmp(Math.min(...x.map(v=>v.held||0)),Math.min(...y.map(v=>v.held||0)))||(Math.max(...y.map(v=>v.rel))-Math.max(...x.map(v=>v.rel))));
 const live=f&&f.last_ok&&(Date.now()/1000-f.last_ok)<90;
 let h='<div class="mcol" style="--c:'+c+'"><div class="mch">'+b+(live?'':' <span class="bad2" title="цены с odds.ru, могут отставать — сверить на сайте конторы">⚠</span>')+'</div>';
 if(!cards.length)h+='<div class="mem">нет ставок</div>';
 const KN=['ИСХОД','ТОТАЛ','ФОРА','ИНД. ТОТАЛ','ИНД. ТОТАЛ'];
 for(const vs of cards){
  const v0=vs[0];const tm=(v0.match||'').split(' — ');const url=v0.bk_url||(v0.url+'bet/');
  const age=Math.max(...vs.map(v=>v.age));const pa=vs.map(v=>v.pin_age).filter(x=>x!=null);const pin=pa.length?Math.max(...pa):null;
  const old=age>180||(pin!=null&&pin>180);
  h+='<div class="mc'+(old?' stale':'')+'"><a class="mtm" href="'+url+'" target="_blank"><span class="th">'+esc(tm[0])+'</span><span class="ta">'+esc(tm[tm.length-1])+'</span></a><div class="mw">'+whenS(v0.start_ts)+'</div>';
  for(const v of vs){
   const [,side,,ord]=vw(v);const star=best.has(v);const nw=isNew(v);const ok=okMark(v);
   h+='<a class="bet mb '+side+(star?' best':'')+(nw?' nbet':'')+'" href="'+url+'" target="_blank"'+(nw?' data-nk="'+esc(nkey(v)).replace(/"/g,'&quot;')+'"':'')+' title="'+esc(v.bet||betText(v))+'">'
    +'<div class="mk">'+(KN[ord]||esc(vw(v)[2]))+(star?' <span class="star">★</span>':'')+'</div>'
    +'<div class="mr"><span class="mbt">'+esc(shortBet(v.outcome))+'</span><span class="mod">'+Number(v.odds).toFixed(2)+'</span></div>'
    +'<div class="mi"><span class="evx">+'+(v.ev*100).toFixed(1)+'%</span><span class="chp '+(v.chance>=0.55?'hich':(v.chance<0.40?'loch':'midch'))+'">'+Math.round(v.chance*100)+'%</span>'+(ok.indexOf('⚠')>=0?'<span class="bad2" title="'+esc(ok.replace(/<[^>]+>/g,''))+'">⚠</span>':'')+'</div></a>'}
  h+='</div>'}
 return h+'</div>'}
function sg(x,suf){if(x==null)return '—';return '<span class="'+(x>0?'pos':(x<0?'neg':''))+'">'+(x>0?'+':'')+x+(suf||'')+'</span>'}
let SEEN={};try{SEEN=JSON.parse(localStorage.getItem('seen')||'{}')}catch(e){}
let NEWK={};try{NEWK=JSON.parse(localStorage.getItem('newk')||'{}')}catch(e){}
// -61 (владелец 22.11: «я её увидел — пусть через 3 секунды пропадает»): NEWV — когда «НОВАЯ» впервые была на экране
// (карточка видна хотя бы наполовину и вкладка открыта); через 3 с после этого подсветка снимается
let NEWV={};try{NEWV=JSON.parse(localStorage.getItem('newv')||'{}')}catch(e){}
const nkey=v=>v.bookmaker+'|'+v.match_id+'|'+v.market_name+'|'+v.outcome;
const isNew=v=>{const k=nkey(v);return !!NEWK[k]&&!(NEWV[k]&&Date.now()-NEWV[k]>3000)};
function dropNew(k){delete NEWK[k];try{localStorage.setItem('newk',JSON.stringify(NEWK))}catch(e){}
 for(const el of document.querySelectorAll('.bet.nbet')){if(el.dataset.nk!==k)continue;el.classList.remove('nbet');const t=el.querySelector('.newb2');if(t)t.remove()}}
let NOBS=null;
function watchNew(){
 if(NOBS)NOBS.disconnect();if(!('IntersectionObserver' in window))return;
 NOBS=new IntersectionObserver(es=>{for(const e of es){if(!e.isIntersecting||document.visibilityState!=='visible')continue;
  const k=e.target.dataset.nk;if(!k)continue;
  if(!NEWV[k]){NEWV[k]=Date.now();try{localStorage.setItem('newv',JSON.stringify(NEWV))}catch(x){}}
  setTimeout(()=>dropNew(k),Math.max(0,3000-(Date.now()-NEWV[k])));NOBS.unobserve(e.target)}},{threshold:0.5});
 for(const el of document.querySelectorAll('.bet.nbet'))NOBS.observe(el)}
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')watchNew()});
// -80 (владелец 22.11: «когда с телефона открываю — всё в свёрнутом виде, что надо, разверну»): на телефоне при каждом
// открытии страницы разделы и группы таблицы свёрнуты; развёрнутое держится, пока страница открыта
const PHONE0=isPhone();
let SCOL={};try{SCOL=PHONE0?{m:true,h1:true,c:true}:JSON.parse(localStorage.getItem('scol')||'{}')}catch(e){}
function scol(k){SCOL[k]=!SCOL[k];if(!PHONE0)try{localStorage.setItem('scol',JSON.stringify(SCOL))}catch(e){}tick()}
let PCOL={};try{PCOL=PHONE0?{}:JSON.parse(localStorage.getItem('pcol')||'{}')}catch(e){}
const pclosed=g=>(g in PCOL)?!!PCOL[g]:PHONE0;
function pcol(g){PCOL[g]=!pclosed(g);if(!PHONE0)try{localStorage.setItem('pcol',JSON.stringify(PCOL))}catch(e){}renderPaper(LASTP)}
let LASTP=null;
const ST_NAME={'all':'все','выигрыш':'выиграно','проигрыш':'проиграно','возврат':'возврат','open':'ждут матча или идут','live':'матчи идут сейчас','settle':'матч окончен, ждут расчёта'};
// -60 (владелец 22.11: «ставка проиграла уже, я так полагаю» — угловые 5:1 при М 4.5): тоталы и инд. тоталы
// только растут — если счёт уже больше линии, «Б» выиграна, «М» проиграна целиком (для любых линий, и с возвратом)
// -60/-63/-69: тоталы и инд. тоталы только растут. Для «Больше» нынешний счёт — худший исход, для «Меньше» — лучший.
// Линии с возвратом (целые, четвертные) считаются по половинкам. -69 (владелец 22.11: 1-й тайм Б 1 при 0:1 —
// «тут уже не проиграл»): «✓ уже не проиграна» / «выиграть уже нельзя»; в 1-м тайме, пока он идёт, счёт тайма = счёт матча.
function decided(b){
 if(b.status!=='open'||!b.live||!b.oc||b.start_ts>Date.now()/1000)return '';
 const lv=b.live,t=lv.timer,k=b.part==='УГЛОВЫЕ'?'c':(b.part==='1-Й ТАЙМ'?'h1':'ft');
 let sc=lv[k];
 if(!sc&&k==='h1'&&lv.ft&&t&&t.tsec!=null&&!t.ht&&t.tsec<3600)sc=lv.ft;      // идёт 1-й тайм (до перерыва)
 if(!sc)return '';
 const m=/\(([-\d.]+)\)/.exec(b.oc);if(!m)return '';const line=parseFloat(m[1]);
 const n=b.base==='total'?sc[0]+sc[1]:(b.base==='tt1'?sc[0]:(b.base==='tt2'?sc[1]:null));
 if(n==null)return '';
 const over=b.oc.startsWith('Больше');
 const parts=(Math.round(Math.abs(line)*4)%2===1)?[line-0.25,line+0.25]:[line];
 let r=parts.map(L=>n>L?1:(n===L?0:-1));if(!over)r=r.map(v=>-v);
 const all=v=>r.every(x=>x===v),has=v=>r.includes(v),sub=x=>'<div class="mu sm">'+x+'</div>',now='сейчас '+n+', линия '+line;
 const fin=lv.fin||(k==='h1'&&!!lv.h1);
 if(fin){const tail=', расчёт скоро';
  if(all(1))return '<span class="pos">✓ выиграна</span>'+sub(now+tail);
  if(all(-1))return '<span class="neg">✗ проиграна</span>'+sub(now+tail);
  if(all(0))return '<span>↩ возврат</span>'+sub(now+tail);
  return (has(1)?'<span class="pos">✓ полвыигрыша</span>':'<span class="neg">✗ полпроигрыша</span>')+sub('половина — возврат · '+now+tail)}
 if(over){
  if(all(1))return '<span class="pos">✓ уже выиграна</span>'+sub(n+' больше '+line);
  if(!has(-1))return '<span class="pos">✓ уже не проиграна</span>'+sub((has(1)?'минимум полвыигрыша':'минимум возврат')+' · '+now);
  return ''}
 if(all(-1))return '<span class="neg">✗ уже проиграна</span>'+sub(n+' больше '+line);
 if(!has(1))return '<span class="neg">выиграть уже нельзя</span>'+sub((has(-1)?'максимум полвозврата':'максимум возврат')+' · '+now);
 return '';
}
let POPSEL=null;
// -71 (владелец 22.11: «над „Сделано“ — цифра, по ней окно только со ставками, где матчи идут сейчас»)
function isLiveBet(b){const now=Date.now()/1000;if(b.status!=='open'||b.start_ts>now)return false;
 const lv=b.live||{},t=lv.timer;if(lv.fin)return false;
 if(t&&t.tsec!=null)return !(!t.tdir&&t.tsec>=5400);
 return now-b.start_ts<135*60}
// -87 (владелец 22.11: «после „Ждут“ — колонка „Расчёт“, туда все ставки, которые ждут расчёт»): матч уже окончен
// (не до матча и не идёт — как в isLiveBet), а итога ещё нет
function isSettleBet(b){return b.status==='open'&&b.start_ts<=Date.now()/1000&&!isLiveBet(b)}
function settleOf(p,part,name){return (p.bets||[]).filter(b=>isSettleBet(b)&&(part==='*'||b.part===part)&&(name==='*'||b.name===name)).length}
function popBets(sel){
 POPSEL=sel;
 const [part,name,st]=sel.split('|');const p=LASTP;if(!p||!p.bets)return;
 const L=p.bets.filter(b=>(part==='*'||b.part===part)&&(name==='*'||b.name===name)&&(st==='all'||(st==='live'?isLiveBet(b):st==='settle'?isSettleBet(b):st==='open'?(b.status==='open'&&!isSettleBet(b)):b.status===st)));
 const e=t=>String(t==null?'':t).replace(/&/g,'&amp;').replace(/</g,'&lt;');
 let h='<div class="mbox"><div class="mhd"><b>'+(part==='*'?'Все ставки':e(part)+(name==='*'?'':' · '+e(name)))+' — '+ST_NAME[st]+' ('+L.length+')</b><span class="mx" onclick="closePop()">✕</span></div><div class="mbody"><table class="mt"><tr><th>Матч</th><th>Ставка</th><th>Контора</th><th>Кф</th><th>Перевес</th><th>Шанс</th><th>Начало</th><th>Итог</th></tr>';
 // группы МАТЧ / 1-Й ТАЙМ / УГЛОВЫЕ; ждущие — ближайший матч сверху, сыгранные — последний сверху
 const now=Date.now()/1000,GR=['МАТЧ','1-Й ТАЙМ','УГЛОВЫЕ'];
 L.sort((x,y)=>(GR.indexOf(x.part)-GR.indexOf(y.part))||((x.status==='open')-(y.status==='open'))*-1||(x.status==='open'?x.start_ts-y.start_ts:y.start_ts-x.start_ts));
 let gp=null;
 for(const b of L){const tm=(b.title||'').split(' — ');
  if(b.part!==gp){gp=b.part;const n=L.filter(x=>x.part===gp).length;h+='<tr class="mg"><td colspan="8"><span class="kind ks '+({'МАТЧ':'m','1-Й ТАЙМ':'h1','УГЛОВЫЕ':'c'}[gp]||'m')+'">'+e(gp)+'</span> <span class="mu">'+n+'</span></td></tr>'}
  const dt=new Date(b.start_ts*1000).toLocaleString('ru-RU',{timeZone:'Europe/Moscow',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
  let left;
  if(b.start_ts>now)left='<div class="lft">через '+fmtLeft(b.start_ts-now)+'</div>';
  else if(b.status==='open'){const mins=Math.floor((now-b.start_ts)/60);
   if(mins<135||(b.live&&b.live.timer)){const lv=b.live||{},k=b.part==='УГЛОВЫЕ'?'c':(b.part==='1-Й ТАЙМ'&&lv.h1?'h1':'ft'),sc=lv[k];
    left='<div class="livem">● '+(lv.fin?'матч окончен':matchClock(lv.timer,mins))+'</div>'+(sc?'<div class="fact">'+({'c':'угловые','h1':'1-й тайм','ft':'счёт'}[k])+' <span class="th">'+sc[0]+'</span> : <span class="ta">'+sc[1]+'</span> сейчас</div>':'')}
   else left='<div class="mu sm">закончился, ждём результат</div>'}
  else left='<div class="mu sm">сыгран</div>';
  let res=b.status==='open'?(decided(b)||'<span class="mu">'+(b.start_ts>now?'ждём матч':'ждём результат')+'</span>'):(b.status==='выигрыш'?'<span class="pos">✓ выигрыш '+(b.profit_rub>0?'+':'')+b.profit_rub+' ₽</span>':(b.status==='проигрыш'?'<span class="neg">✗ проигрыш '+b.profit_rub+' ₽</span>':'<span>↩ возврат 0 ₽</span>'));
  if(b.res){const [rh,ra]=b.res,lab={'МАТЧ':'счёт','1-Й ТАЙМ':'1-й тайм','УГЛОВЫЕ':'угловые'}[b.part]||'счёт';
   const hh=b.base==='tt1'?'<b>'+rh+'</b>':rh,aa=b.base==='tt2'?'<b>'+ra+'</b>':ra;
   const tot=(b.base==='total')?' · всего <b>'+(rh+ra)+'</b>':'';
   res+='<div class="fact">'+lab+' <span class="th">'+hh+'</span> : <span class="ta">'+aa+'</span>'+tot+'</div>'}
  const isLive=b.status==='open'&&b.start_ts<=now&&(now-b.start_ts)<3*3600;
  const nm='<span class="th">'+e(tm[0])+'</span> — <span class="ta">'+e(tm[tm.length-1])+'</span>';
  h+='<tr'+(isChg('b:'+b.id)?' class="chg" data-ck="b:'+b.id+'"':'')+'><td>'+(b.url?'<a class="mlink" href="'+e(b.url)+'" target="_blank" title="'+(b.sofa?'статистика матча на '+(b.url.indexOf('fotmob')>0?'FotMob':'Sofascore'):'страница матча на odds.ru (на FotMob и Sofascore матч ещё не найден)')+'">'+nm+'</a>':nm)
   +'<div class="sm">'+e(b.league)+'</div></td><td class="bcell"><span class="kind ks '+({'МАТЧ':'m','1-Й ТАЙМ':'h1','УГЛОВЫЕ':'c'}[b.part]||'m')+'">'+e(b.part)+'</span> <span class="bt '+b.side+'">'+e(b.bet)+'</span></td><td>'
   +(b.bk_url?'<a class="bkbtn" style="--c:'+(COLORS[b.bk]||'#7fb6ff')+'" href="'+e(b.bk_url)+'" target="_blank" title="открыть матч у конторы">'+e(b.bk)+' ↗</a>':'<span class="bkbtn" style="--c:'+(COLORS[b.bk]||'#7fb6ff')+'">'+e(b.bk)+'</span>')+'</td><td><b>'+Number(b.odds).toFixed(2)+'</b></td><td class="pos">+'+(b.ev*100).toFixed(1)+'%</td><td>'+(b.chance!=null?'<span class="chp '+(b.chance>=0.55?'hich':(b.chance<0.40?'loch':'midch'))+'">'+Math.round(b.chance*100)+'%</span>':'—')+'</td><td>'+dt+left+'</td><td class="rcell">'+res+'</td></tr>'}
 if(!L.length)h+='<tr><td colspan="8" class="mu">нет ставок</td></tr>';
 document.getElementById('pop').innerHTML=h+'</table></div></div>';document.getElementById('pop').style.display='flex';watchChg()}
// минута матча по таймеру Фонбета (проверено 21.11 по 6 матчам: идущий таймер — секунды с «нулевой» точки
// timerUpdateTimestamp; стоящий на 45:00 — перерыв); нет таймера — минуты от начала по расписанию
function matchClock(t,mins){
 if(!t||t.tsec==null)return 'идёт · '+mins+' мин от начала';
 if(!t.tdir){if(t.tsec>=5400)return 'матч окончен';if(t.tsec>=2700&&t.ht)return 'перерыв';return 'таймер стоит · '+Math.floor(t.tsec/60)+'-я минута'}
 const sec=t.tsec+(Date.now()-(t.tupd||Date.now()))/1000,m=Math.floor(sec/60);   // как часы на сайте конторы: 30:56 → 30
 // -76 (владелец 22.11: у PARI 1-й тайм 45:23, у нас «2-й тайм · 46-я минута»): 2-й тайм — только по отметке перерыва (ht);
 // без неё до 60-й минуты таймера — добавленное время 1-го тайма
 const half=(t.ht||m>=60)?'2-й тайм':'1-й тайм';
 return half+' · '+(half==='1-й тайм'&&m>45?'45+'+(m-45):(m>90?'90+'+(m-90):m))+'-я минута'}
function fmtLeft(x){x=Math.round(x/60);const d=Math.floor(x/1440),h=Math.floor(x%1440/60),m=x%60;
 return (d?d+' д ':'')+(d||h?h+' ч ':'')+m+' мин'}
function closePop(){document.getElementById('pop').style.display='none'}
document.addEventListener('click',ev=>{const t=ev.target.closest('[data-pop]');if(t){popBets(t.dataset.pop);return}
 if(ev.target.id==='pop')closePop()});
document.addEventListener('keydown',ev=>{if(ev.key==='Escape')closePop()});
// -65 (владелец 22.11: «когда цифра меняется — пусть подсвечивается: новая ставка, смена статуса; и в раскрывающемся так же»):
// PV — прошлые значения ячеек, PB — прошлые статусы ставок; изменилось — CHG[ключ]=когда. Подсветка снимается через 3 с
// после того, как ячейка/строка впервые видна на экране (как «НОВАЯ»), или через 10 мин, если так и не показалась.
let PV=null,PB=null,CHG={},CHV={};
try{PV=JSON.parse(localStorage.getItem('pv')||'null');PB=JSON.parse(localStorage.getItem('pb')||'null');CHG=JSON.parse(localStorage.getItem('pchg')||'{}');CHV=JSON.parse(localStorage.getItem('pchv')||'{}')}catch(e){}
const isChg=k=>!!CHG[k]&&!(CHV[k]&&Date.now()-CHV[k]>3000);
function saveChg(){try{localStorage.setItem('pv',JSON.stringify(PV));localStorage.setItem('pb',JSON.stringify(PB));localStorage.setItem('pchg',JSON.stringify(CHG));localStorage.setItem('pchv',JSON.stringify(CHV))}catch(e){}}
function dropChg(k){delete CHG[k];saveChg();for(const el of document.querySelectorAll('.chg[data-ck]'))if(el.dataset.ck===k)el.classList.remove('chg')}
let COBS=null;
function watchChg(){
 if(COBS)COBS.disconnect();if(!('IntersectionObserver' in window))return;
 COBS=new IntersectionObserver(es=>{for(const e of es){if(!e.isIntersecting||document.visibilityState!=='visible')continue;
  const k=e.target.dataset.ck;if(!k)continue;if(!CHV[k]){CHV[k]=Date.now();saveChg()}
  setTimeout(()=>dropChg(k),Math.max(0,3000-(Date.now()-CHV[k])));COBS.unobserve(e.target)}},{threshold:0.5});
 for(const el of document.querySelectorAll('.chg[data-ck]'))COBS.observe(el)}
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')watchChg()});
function trackChg(p){
 const now=Date.now(),cur={},first=PV===null;
 const put=(sel,g)=>{cur[sel+'|all']=g.n||0;cur[sel+'|выигрыш']=g.w||0;cur[sel+'|проигрыш']=g.l||0;cur[sel+'|возврат']=g.push||0;const [pa,na]=sel.split('|'),se=settleOf(p,pa,na);cur[sel+'|open']=(g.n||0)-(g.done||0)-se;cur[sel+'|settle']=se;cur[sel+'|итог']=g.done?Math.round(g.profit_rub||0):null};
 const groups={};for(const g of p.simple||[]){put(g.part+'|'+g.name,g);const G=groups[g.part]=groups[g.part]||{n:0,w:0,l:0,push:0,done:0,profit_rub:0};for(const k in G)G[k]+=g[k]||0}
 for(const part in groups)put(part+'|*',groups[part]);
 if(p.simple_total)put('*|*',p.simple_total);
 if(!first)for(const k in cur)if(k in PV&&PV[k]!==cur[k]&&!CHG['c:'+k]){CHG['c:'+k]=now;delete CHV['c:'+k]}
 PV=cur;
 const bs={};for(const b of p.bets||[])bs[b.id]=b.status;
 if(PB!==null)for(const id in bs)if(PB[id]!==bs[id]&&!CHG['b:'+id]){CHG['b:'+id]=now;delete CHV['b:'+id]}
 PB=bs;
 for(const k in CHG)if(now-CHG[k]>600000||(CHV[k]&&now-CHV[k]>3000))delete CHG[k];
 for(const k in CHV)if(!CHG[k]&&now-CHV[k]>600000)delete CHV[k];
 saveChg();
}
// -81 (владелец 22.11, снимок с телефона: «не влезла таблица» — у него крупнее шрифт и двузначные числа): на телефоне
// таблица, если шире места, уменьшается целиком (zoom), пока не влезет — при любом размере шрифта в браузере
function fitTable(el){if(!isPhone())return;const t=el.querySelector('.ptab');if(!t)return;
 t.style.zoom='';const p=t.parentElement,cs=getComputedStyle(p);
 const w=p.clientWidth-parseFloat(cs.paddingLeft)-parseFloat(cs.paddingRight);
 if(t.scrollWidth>w+1)t.style.zoom=Math.max(0.55,(w-1)/t.scrollWidth).toFixed(3)}
window.addEventListener('resize',()=>{const el=document.getElementById('paper');if(el)fitTable(el)});
// -80: короткие названия видов в таблице на телефоне — чтобы таблица влезала целиком
const SHN={'Тотал голов':'Тотал','Инд. тотал хозяев':'Инд. хоз.','Инд. тотал гостей':'Инд. гост.','1-Й ТАЙМ':'1 ТАЙМ'};
function renderPaper(p){
 LASTP=p;
 const el=document.getElementById('paper');if(!p||p.error){el.innerHTML=p&&p.error?'<div class="pp st">бумага: '+p.error+'</div>':'';return}
 trackChg(p);
 const z=x=>x?x:'·';
 const ck=(sel,k)=>{const key='c:'+sel+'|'+k;return isChg(key)?' chg" data-ck="'+key.replace(/"/g,'&quot;'):''};
 const c=(v,cl,sel,k)=>'<td class="'+cl+(v?' clk':'')+ck(sel,k)+'">'+(v?'<span class="num" data-pop="'+sel+'|'+k+'">'+(cl==='n'?v:z(v))+'</span>':(cl==='n'?v:z(v)))+'</td>';
 const cells=(g,sel)=>{const [pa,na]=sel.split('|'),se=settleOf(p,pa,na);return c(g.n,'n',sel,'all')+c(g.w,'w',sel,'выигрыш')+c(g.l,'l',sel,'проигрыш')+c(g.push,'p',sel,'возврат')+c(g.n-g.done-se,'',sel,'open')+c(se,'stl',sel,'settle')+'<td class="'+ck(sel,'итог').replace(/^ /,'')+'">'+(g.done?sg(g.profit_rub,'<span class="lg"> ₽</span>'):'<span class="mu">—</span>')+'</td>'};
 let h='<div class="pp"><h2>Ставки на бумаге · по '+p.stake_rub+' ₽, одна ставка на событие</h2>';
 if(!p.simple||!p.simple.length){el.innerHTML=h+'<div class="st">пока ни одной ставки</div></div>';return}
 const nl=(p.bets||[]).filter(isLiveBet).length;
 h=h.replace('</h2>',' '+(nl?'<span class="livebtn num" data-pop="*|*|live" title="ставки на матчи, которые идут сейчас">● '+nl+'</span>':'<span class="livebtn off" title="сейчас ни один матч с нашей ставкой не идёт">● 0</span>')+'</h2>');
 h+='<table class="ptab"><tr><th><span class="lg">Вид ставки</span><span class="sh">Вид</span></th><th><span class="lg">Сделано</span><span class="sh">Всего</span></th><th><span class="lg">✓ Выиграно</span><span class="sh">✓</span></th><th><span class="lg">✗ Проиграно</span><span class="sh">✗</span></th><th><span class="lg">↩ Возврат</span><span class="sh">↩</span></th><th>Ждут</th><th><span class="lg">Расчёт</span><span class="sh">Расч.</span></th><th><span class="lg">Итог</span><span class="sh">₽</span></th></tr>';
 const groups=[];for(const g of p.simple){let G=groups.find(x=>x.part===g.part);if(!G){G={part:g.part,kc:g.kc,rows:[]};groups.push(G)}G.rows.push(g)}
 for(const G of groups){
  const s={n:0,w:0,l:0,push:0,done:0,profit_rub:0};for(const r of G.rows)for(const k in s)s[k]+=r[k]||0;
  const closed=pclosed(G.part);
  h+='<tr class="grp" onclick="if(!event.target.closest(\'[data-pop]\'))pcol(\''+G.part+'\')"><td><span class="chev">'+(closed?'▸':'▾')+'</span><span class="kind ks '+G.kc+'">'+G.part+'</span> <span class="gn">'+G.rows.length+' вид'+(G.rows.length==1?'':(G.rows.length<5?'а':'ов'))+'</span></td>'+cells(s,G.part+'|*')+'</tr>';
  if(!closed)for(const r of G.rows){const nm=r.name||r.val;const sn=SHN[nm];h+='<tr class="sub"><td>'+(sn?'<span class="lg">'+nm+'</span><span class="sh">'+sn+'</span>':nm)+'</td>'+cells(r,G.part+'|'+r.name)+'</tr>'}
 }
 h+='<tr class="tot"><td>Всего</td>'+cells(p.simple_total,'*|*')+'</tr>';
 const T=p.simple_total;if(T&&T.done)h+='<tr class="taxr"><td><span class="lg">после налога 13%</span><span class="sh">после налога</span></td><td colspan="6" class="taxn"><span class="lg">13% с каждого выигрыша, проигрыши не вычитаются</span><span class="sh">13% с выигрышей</span></td><td>'+sg(T.profit_tax_rub,'<span class="lg"> ₽</span>')+'</td></tr>';
 h+='</table>';
 if(p.nodata)h+='<div class="st">ещё '+p.nodata+' не рассчитать: нигде не нашёлся счёт — в итог не входят</div>';
 el.innerHTML=h+'</div>';
 fitTable(el);
 const pe=document.getElementById('pop');
 if(pe&&pe.style.display==='flex'&&POPSEL){const mb=pe.querySelector('.mbody'),sc=mb?mb.scrollTop:0;popBets(POPSEL);const mb2=pe.querySelector('.mbody');if(mb2)mb2.scrollTop=sc}
 watchChg();
}



let PHEDIT=false;
async function phset(){const p=document.getElementById('phpass').value;const m=document.getElementById('phmsg');
 try{const r=await fetch('/api/phone_pass',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({p})});const d=await r.json();
  m.innerHTML=d.ok?'<span class="pos">сохранён — через минуту бот пришлёт ссылку по команде /site</span>':'<span class="bad">'+(d.why||'не сохранился')+'</span>';
  if(d.ok)document.getElementById('phpass').value=''}catch(e){m.textContent='не сохранился'}}
async function tgc(){const k=document.getElementById('tgkey').value.trim();if(!k)return;
 try{await fetch('/api/telegram',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:k})})}catch(e){}}
async function post(u){try{await fetch(u,{method:'POST'})}catch(e){}}
tick();setInterval(tick,3000);
</script></body></html>"""


# ================================================================ Сайт с телефона (-79, владелец 22.11: «чтобы я с телефона
# мог открывать этот сайт, сделать под смартфон вёрстку»). Как в программе для роликов: бесплатный проход TryCloudflare —
# программа cloudflared (официальные выпуски Cloudflare на GitHub) стучится наружу, Cloudflare даёт ссылку
# https://…trycloudflare.com, бот присылает её на слово «сайт». По проходу страница видна интернету, поэтому пускает
# только пароль (не короче 10 знаков; на самом ноутбуке пароль не спрашивается). Пароль хранится только как отпечаток.
CF_URL = 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe'
CF_LINK = re.compile(r'https://[a-z0-9-]+\.trycloudflare\.com')
MIN_PASS = 10
CFG = {}


def pass_hash(pw, salt):
    import hashlib
    return hashlib.pbkdf2_hmac('sha256', pw.encode('utf-8'), salt.encode('utf-8'), 200000).hex()


def session_token():
    """жетон входа выводится из отпечатка пароля: сменили пароль — все старые входы недействительны"""
    import hmac
    import hashlib
    h = CFG.get('phone_pass_hash') or ''
    return hmac.new(h.encode(), b'stavki-session', hashlib.sha256).hexdigest() if h else ''


class Prohod:
    def __init__(self, cfg):
        self.cfg, self.proc, self.link, self.why = cfg, None, '', ''
        self.pid_file = HERE / 'prohod.pid'
        self.fails = 0
        threading.Thread(target=self.loop, daemon=True).start()

    def set(self, sost, why=''):
        self.why = why
        with STATE.lock:
            STATE.status['prohod'] = {'sost': sost, 'link': self.link, 'why': why,
                                      'pass_set': bool(self.cfg.get('phone_pass_hash'))}

    def exe(self):
        return HERE / 'vneshnie' / ('cloudflared.exe' if os.name == 'nt' else 'cloudflared')

    def ensure_exe(self):
        f = self.exe()
        if f.exists() and f.stat().st_size > 1_000_000:
            return f
        if os.name != 'nt':
            raise RuntimeError('проход сделан только для Windows')
        self.set('загрузка', 'скачиваю программу прохода с GitHub Cloudflare (~55 МБ, один раз)…')
        f.parent.mkdir(exist_ok=True)
        tmp = f.with_suffix('.part')
        with urllib.request.urlopen(urllib.request.Request(CF_URL, headers={'User-Agent': 'stavki'}), timeout=300) as r, \
                open(tmp, 'wb') as out:
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                out.write(b)
        tmp.replace(f)
        return f

    def kill_old(self):
        try:
            pid = int(self.pid_file.read_text())
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(pid), '/F'], capture_output=True, timeout=10)
        except Exception:
            pass

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.kill()
            except Exception:
                pass
        self.proc, self.link = None, ''

    def start(self):
        f = self.ensure_exe()
        self.kill_old()
        flags = 0x08000000 if os.name == 'nt' else 0          # CREATE_NO_WINDOW — без чёрного окна
        self.proc = subprocess.Popen([str(f), 'tunnel', '--no-autoupdate', '--url', f"http://127.0.0.1:{self.cfg['port']}"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=flags)
        try:
            self.pid_file.write_text(str(self.proc.pid))
        except Exception:
            pass
        proc = self.proc

        def read():
            for raw in proc.stderr:
                m = CF_LINK.search(raw.decode('utf-8', 'replace'))
                if m and proc is self.proc:
                    self.link = m.group(0)
                    self.set('работает')
                    log('проход для телефона: ' + self.link)
        threading.Thread(target=read, daemon=True).start()
        self.set('запуск', 'жду ссылку от Cloudflare…')

    def alive(self):
        """ссылка отвечает из интернета (раз в 5 мин)"""
        try:
            with urllib.request.urlopen(self.link + '/api/ping', timeout=20) as r:
                return r.status == 200
        except Exception:
            return False

    def loop(self):
        import atexit
        atexit.register(self.stop)
        pauses, k, last_check, dead = [10, 30, 120, 600], 0, 0, 0
        while True:
            time.sleep(5)
            try:
                ok_pass = bool(self.cfg.get('phone_pass_hash'))
                if not ok_pass:
                    if self.proc:
                        self.stop()
                    self.set('выключен', f'задайте пароль для входа с телефона (не короче {MIN_PASS} знаков)')
                    continue
                if self.proc is None or self.proc.poll() is not None:
                    if self.proc is not None:
                        self.set('перезапуск', f'проход оборвался — поднимаю снова через {pauses[min(k, 3)]} с')
                        time.sleep(pauses[min(k, 3)])
                        k += 1
                    self.start()
                    last_check, dead = time.time(), 0
                    continue
                if self.link and time.time() - last_check > 300:
                    last_check = time.time()
                    if self.alive():
                        dead, k = 0, 0
                    else:
                        dead += 1
                        if dead >= 3:                      # ссылка умерла, а процесс жив — поднять новый
                            self.stop()
                            dead = 0
            except Exception as e:
                self.set('ошибка', str(e).splitlines()[0][:160])
                time.sleep(60)


PROHOD = None
LOGIN_FAILS = []

LOGIN_PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ставки — вход</title><style>body{background:#0f1419;color:#e6edf3;font-family:system-ui,sans-serif;display:flex;
align-items:center;justify-content:center;min-height:100vh;margin:0}form{background:#151c24;padding:24px;border-radius:12px;
width:min(340px,90vw)}input{width:100%;box-sizing:border-box;font-size:18px;padding:10px;margin:12px 0;border-radius:8px;
border:1px solid #2e3744;background:#0f1419;color:#fff}button{width:100%;font-size:18px;padding:10px;border:0;border-radius:8px;
background:#2f7d4f;color:#fff}.e{color:#ff6b6b}</style></head><body><form method="post" action="/login">
<b>Ставки</b><div>Пароль для входа с телефона</div><input type="password" name="p" autofocus>__ERR__<button>Войти</button></form></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def remote(self):
        """пришёл через проход Cloudflare (с телефона), а не с этого ноутбука"""
        return bool(self.headers.get('Cf-Connecting-Ip') or self.headers.get('Cf-Ray'))

    def authed(self):
        if not self.remote():
            return True
        tok = session_token()
        if not tok:
            return False
        import hmac
        for part in (self.headers.get('Cookie') or '').split(';'):
            k, _, v = part.strip().partition('=')
            if k == 'stk' and hmac.compare_digest(v, tok):
                return True
        return False

    def send_body(self, code, body, ctype, extra=()):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Cache-Control', 'no-store')
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def login_page(self, err=''):
        self.send_body(200, LOGIN_PAGE.replace('__ERR__', f'<div class="e">{err}</div>' if err else '').encode('utf-8'),
                       'text/html; charset=utf-8')

    def do_GET(self):
        if self.path.startswith('/api/ping'):
            return self.send_body(200, b'ok', 'text/plain')
        if not self.authed():
            if self.path.startswith('/api/'):
                return self.send_body(401, b'{"error": "login"}', 'application/json')
            return self.login_page()
        if self.path.startswith('/api/report'):
            try:
                body = build_report(STATS_DB)
            except Exception as e:
                body = ('отчёт не собрался: ' + str(e)[:300]).encode('utf-8')
                self.send_response(500)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.end_headers()
                self.wfile.write(body)
                return
            name = 'otchet_' + datetime.datetime.now(MSK).strftime('%Y%m%d_%H%M') + '.zip'
            self.send_response(200)
            self.send_header('Content-Type', 'application/zip')
            self.send_header('Content-Disposition', f'attachment; filename="{name}"')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)
            return
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
        if self.path.startswith('/login'):
            now = time.time()
            LOGIN_FAILS[:] = [t for t in LOGIN_FAILS if now - t < 900]
            if len(LOGIN_FAILS) >= 8:
                return self.login_page('Слишком много неверных попыток — подождите 15 минут.')
            try:
                n = int(self.headers.get('Content-Length') or 0)
                pw = urllib.parse.parse_qs(self.rfile.read(min(n, 2000)).decode('utf-8')).get('p', [''])[0]
            except Exception:
                pw = ''
            h, salt = CFG.get('phone_pass_hash'), CFG.get('phone_pass_salt', '')
            import hmac
            if h and pw and hmac.compare_digest(pass_hash(pw, salt), h):
                return self.send_body(303, b'', 'text/plain', (
                    ('Location', '/'),
                    ('Set-Cookie', f'stk={session_token()}; Path=/; Max-Age=2592000; HttpOnly; Secure; SameSite=Lax')))
            LOGIN_FAILS.append(now)
            return self.login_page('Неверный пароль.')
        if not self.authed():
            return self.send_body(401, b'{"error": "login"}', 'application/json')
        if self.remote() and (self.path.startswith('/api/telegram') or self.path.startswith('/api/phone_pass')):
            return self.send_body(403, b'{"error": "only from the laptop"}', 'application/json')
        if self.path.startswith('/api/phone_pass'):
            try:
                n = int(self.headers.get('Content-Length') or 0)
                pw = json.loads(self.rfile.read(n).decode('utf-8') or '{}').get('p', '')
            except Exception:
                pw = ''
            if len(pw) < MIN_PASS:
                return self.send_body(200, json.dumps({'ok': False, 'why': f'нужно не меньше {MIN_PASS} знаков'},
                                                      ensure_ascii=False).encode('utf-8'), 'application/json')
            salt = os.urandom(16).hex()
            CFG['phone_pass_salt'], CFG['phone_pass_hash'] = salt, pass_hash(pw, salt)
            save_config_keys({'phone_pass_salt': salt, 'phone_pass_hash': CFG['phone_pass_hash']})
            log('задан пароль для входа с телефона')
            return self.send_body(200, b'{"ok": true}', 'application/json')
        if self.path.startswith('/api/check_update'):
            with STATE.lock:
                STATE.status['check_now'] = True
            body = b'{"ok": true}'
        elif self.path.startswith('/api/telegram'):
            try:
                n = int(self.headers.get('Content-Length') or 0)
                token = json.loads(self.rfile.read(n).decode('utf-8') or '{}').get('token', '')
            except Exception:
                token = ''
            if token and TG:
                threading.Thread(target=TG.connect, args=(token,), daemon=True).start()
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

BUSY_STATUSES = (429, 502, 503, 504, -1)

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


ERRLOG = []        # (источник или None, когда, текст) — ошибка пропадает, когда её источник снова заработал


def _errors_publish():
    now = time.time()
    ERRLOG[:] = [e for e in ERRLOG if e[0] is not None or now - e[1] < 900][-20:]   # без источника — живёт 15 мин
    STATE.status['errors'] = [e[2] for e in ERRLOG][-5:]


def add_error(msg, key=None):
    log('ОШИБКА: ' + msg)
    with STATE.lock:
        ERRLOG[:] = [e for e in ERRLOG if not (key is not None and e[0] == key)]   # от одного источника — последняя
        ERRLOG.append((key, time.time(), f'{now_str()} {msg}'))
        _errors_publish()


def clear_error(key):
    """источник снова работает — его ошибка больше не актуальна (владелец 21.11)"""
    with STATE.lock:
        if any(e[0] == key for e in ERRLOG) or ERRLOG:
            ERRLOG[:] = [e for e in ERRLOG if e[0] != key]
            _errors_publish()


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
        if 'Винлайн' in MY_BOOKMAKERS:
            self.feeds.append(WinlineFeed())
        self.pin = PinnacleFeed()
        self.pin_start_try = 0
        self.stats_teams = (0, set())      # (когда собран, команды текущего сезона)
        self.bk_known = dict(con.execute('SELECT event_id, match_id FROM bk_events').fetchall())
        self.ext = ExtStats()
        con.execute("DELETE FROM sofa_link WHERE url = ''")      # не нашлись при прошлом запуске — искать заново
        con.commit()
        self.ext_last = 0
        self.covered_cache = {}
        # odds.ru отвечает 502, когда запросов сразу слишком много: размер пакета подстраивается сам
        self.batch_cur = cfg['batch_matches']
        self.extra_pause = 0.0
        self.ok_streak = 0
        self.busy_log = []          # время каждого ответа «сервер занят» (502/503/504/429)

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
                add_error(f'{f.name}: сайт не открылся: {str(e).splitlines()[0][:120]}', f.name)
        self.start_pin()

    def start_pin(self):
        self.pin_start_try = time.time()
        try:
            if self.pin.page is not None:
                try:
                    self.pin.page.close()
                except Exception:
                    pass
                self.pin.page = None
            self.pin.fails = 0
            self.pin.start(self.browser)
            with STATE.lock:
                STATE.status['feeds']['Pinnacle'] = {'last_ok': None, 'events': 0, 'matched': 0, 'error': ''}
        except Exception as e:
            self.pin.page = None
            self.pin.mode = None
            self.pin.last_error = str(e).splitlines()[0][:160]
            with STATE.lock:
                STATE.status['feeds']['Pinnacle'] = {'last_ok': None, 'error': self.pin.last_error}
            add_error('Pinnacle: ' + self.pin.last_error, 'Pinnacle')

    def poll_pin(self):
        if self.pin.mode is None:
            if time.time() - self.pin_start_try > 300:
                self.start_pin()
            return
        if self.pin.mode == 'thread':
            with self.pin.lock:
                changed, self.pin.pending = list(self.pin.pending), set()
            self.pin_apply(changed)
            return
        if self.pin.page is None:
            if time.time() - self.pin_start_try > 300:
                self.start_pin()
            return
        with STATE.lock:
            matches = dict(STATE.matches)
        try:
            changed = self.pin.poll(matches, k=1)
        except Exception as e:
            self.pin.fails += 1
            self.pin.last_error = str(e).splitlines()[0][:160]
            with STATE.lock:
                STATE.status['feeds'].setdefault('Pinnacle', {}).update(error=self.pin.last_error)
            if self.pin.fails in (1, 5) or self.pin.fails % 20 == 0:
                add_error('Pinnacle: ' + self.pin.last_error, 'Pinnacle')
            if self.pin.fails % 10 == 0:
                self.start_pin()
            return
        self.pin_apply(changed)

    def pin_apply(self, changed):
        now = time.time()
        with self.pin.lock, STATE.lock:
            for mid in changed:
                if mid in self.pin.fair:
                    STATE.pin_fair[mid] = self.pin.fair[mid]
            for mid in self.pin.removed:
                STATE.pin_fair.pop(mid, None)
            self.pin.removed = []
            for mid in [mid for mid in STATE.pin_fair if mid not in STATE.matches
                        or not any(pin_fresh(STATE.matches[mid]['start'], v[2], now) for v in STATE.pin_fair[mid].values())]:
                STATE.pin_fair.pop(mid)
            near = [m for m in STATE.matches.values() if m['id'] in STATE.pin_fair]
            STATE.status['feeds']['Pinnacle'] = {
                'last_ok': self.pin.last_ok, 'events': len(self.pin.regular), 'matched': len(STATE.pin_fair),
                'leagues': len(self.pin.leagues), 'mode': self.pin.mode,
                'error': self.pin.last_error if self.pin.fails else ''}
            # -84 (пункт 3, проверка отчёта 22.11 10:00): цена закрытия пишется не чаще раза в минуту на матч, а изменение
            # внутри этой минуты раньше терялось совсем — если оно было последним до начала, CLV считался по старой цене.
            # Теперь изменение ждёт своей минуты и записывается, даже если новых изменений больше не было.
            unw = self.pin.__dict__.setdefault('pin_unwritten', {})
            for mid in changed:
                if mid in self.pin.fair:
                    unw[mid] = (unw.get(mid, (now, now))[0], now)        # (первое незаписанное изменение, последнее)
            rows = {}
            for mid, (t0, t1) in list(unw.items()):
                if now - self.pin.pin_written.get(mid, 0) < 60:
                    continue
                unw.pop(mid, None)
                if mid in self.pin.fair:
                    rows[mid] = (t1, self.pin.compact(mid, t0 - 120))
        for mid, (t1, comp) in rows.items():
            self.pin.pin_written[mid] = now
            for market, rr in comp.items():
                if rr:                             # время записи — когда цена такой стала (важно у самого начала матча)
                    self.con.execute('INSERT INTO pin VALUES (?,?,?,?)',
                                     (t1, mid, market, json.dumps(rr, ensure_ascii=False)))
        if changed:
            self.con.commit()

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
            (HERE / 'restart_update.flag').write_text(str(time.time()))     # -78: после обновления не слать «запущена»
        except Exception:
            pass
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
                    clear_error('odds.ru результаты')
                    for lg in data.get('leagues', []):
                        for ev in lg.get('events', []):
                            if (ev.get('status') or {}).get('name') == 'completed':
                                self.con.execute('INSERT OR REPLACE INTO results VALUES (?,?,?,?)',
                                                 (ev['id'], int(ev['home']['score']), int(ev['away']['score']), time.time()))
                except Exception as e:
                    add_error(f'результаты за {d.isoformat()}: {str(e).splitlines()[0][:100]}', 'odds.ru результаты')
                continue
            try:
                data = self.get_json(f'/next-api/sports/events/ru/?sport=football&status=all&date={d.isoformat()}&source=default')
            except Exception as e:
                add_error(f'список матчей на {d.isoformat()}: {str(e).splitlines()[0][:120]}', 'odds.ru список ' + d.isoformat())
                continue
            ok_dates += 1
            clear_error('odds.ru список ' + d.isoformat())
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
                    found[ev['id']]['home_en'], found[ev['id']]['away_en'] = en_names_of(ev)
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
            cur.execute('INSERT OR REPLACE INTO matches (match_id, title, league, start_ts, url, home_en, away_en)'
                        ' VALUES (?,?,?,?,?,?,?)',
                        (m['id'], m['title'], m['league'], m['start'], m['url'], m.get('home_en'), m.get('away_en')))
        self.con.commit()
        self.last_events = time.time()
        log(f'матчей в ближайшие {self.cfg["hours_ahead"]} ч: {len(found)}')

    # --- какой матч обновлять следующим
    def interval_for(self, m, now):
        left = m['start'] - now
        base = 45 if left < 3 * 3600 else 120 if left < 12 * 3600 else 400
        if m.get('no_pin', 0) >= 2 and m['id'] not in STATE.pin_fair:   # нет честной цены — заглядываем редко
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

    def stats_covered(self, m):
        """обе команды матча есть в статистике сезона → тайм и угловые можно рассчитать"""
        if not m or not m.get('home_en'):
            return False
        mid = m['id']
        if mid in self.covered_cache:
            return self.covered_cache[mid]
        ts, teams = self.stats_teams
        if time.time() - ts > 3600:
            since = (datetime.datetime.now(MSK) - datetime.timedelta(days=200)).strftime('%Y-%m-%d')
            teams = {r[0] for r in self.con.execute('SELECT home FROM stats WHERE date >= ? UNION SELECT away FROM stats'
                                                    ' WHERE date >= ?', (since, since))}
            self.stats_teams = (time.time(), teams)
            self.covered_cache = {}
        ok = any(en_sim(m['home_en'], t) >= 0.8 for t in teams) and any(en_sim(m['away_en'], t) >= 0.8 for t in teams)
        self.covered_cache[mid] = ok
        return ok

    def stats_result(self, mid, start_ts):
        """сыгранный матч в статистике → словарь с полями таблицы stats или None"""
        row = self.con.execute('SELECT home_en, away_en FROM matches WHERE match_id=?', (mid,)).fetchone()
        if not row or not row[0]:
            return None
        day = datetime.datetime.fromtimestamp(start_ts, MSK).date()
        days = [(day + datetime.timedelta(days=k)).isoformat() for k in (-1, 0, 1)]
        cols = ['home', 'away', 'fthg', 'ftag', 'hthg', 'htag', 'hc', 'ac']
        best, best_s = None, 0
        for r in self.con.execute(f"SELECT {', '.join(cols)} FROM stats WHERE date IN (?,?,?)", days):
            d = dict(zip(cols, r))
            sc = (en_sim(row[0], d['home']) + en_sim(row[1], d['away'])) / 2
            if min(en_sim(row[0], d['home']), en_sim(row[1], d['away'])) >= 0.6 and sc > best_s:
                best, best_s = d, sc
        return best if best_s >= 0.75 else None

    def record_paper(self):
        now = time.time()
        rows = []
        for v in STATE.snapshot()['values']:
            if v['bookmaker'] not in MY_BOOKMAKERS or v['ev'] <= 0:
                continue
            if not v.get('start_ts') or v['start_ts'] < now + 60:
                continue
            v = dict(v, src='сайт' if v.get('source') == 'сайт' else 'odds.ru')
            fam = event_of(v)
            if v.get('line') is None:
                v['line'] = line_of(v['outcome']) if not fam.endswith('1x2') else None
            if not fam.endswith('1x2') and v['line'] is None:
                continue
            if split_fam(fam)[0]:
                with STATE.lock:
                    mm = STATE.matches.get(v['match_id'])
                v['stats_ok'] = self.stats_covered(mm)
            rows.append(v)
        cur = self.con.cursor()
        added = 0
        try:
            for code, v in pick_for_strategies(rows):
                cur.execute('INSERT OR IGNORE INTO paper2 (created, match_id, title, league, start_ts, strategy, event,'
                            ' src, bookmaker, market_name, outcome, line, odds, fair, ev, rel, pin_age, fam, bk_url) VALUES'
                            ' (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                            (now, v['match_id'], v['match'], v['league'], v['start_ts'], code,
                             event_group(event_of(v)), v['src'],
                             v['bookmaker'], v['market_name'], v['outcome'], v['line'], v['odds'], v['fair'],
                             v['ev'], v['rel'], v.get('pin_age'), event_of(v), v.get('bk_url')))
                added += cur.rowcount
                if cur.rowcount and code == 'Б' and v['src'] == 'сайт' and TG:
                    TG.send(tg_text(v, code))
            for v in rows:
                if v['ev'] >= CAND_MIN_EV and v['odds'] <= 4.0:
                    cur.execute('INSERT OR IGNORE INTO cand (match_id, bookmaker, src, market_name, outcome, line,'
                                ' start_ts, first_seen, odds, fair, ev, pin_age, fam) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                (v['match_id'], v['bookmaker'], v['src'], v['market_name'], v['outcome'], v['line'],
                                 v['start_ts'], now, v['odds'], v['fair'], v['ev'], v.get('pin_age'), event_of(v)))
        except Exception as e:
            add_error('бумажная ставка: ' + str(e)[:100])
        self.con.commit()
        if added:
            log(f'бумажных ставок записано: {added}')

    def closing_fair(self, match_id, market, outcome, line, start_ts, odds=None):
        """последняя цена Pinnacle до начала → (честная цена, CLV = перевес нашей цены против неё)"""
        self.close_ts = None
        row = self.con.execute('SELECT raw, ts FROM pin WHERE match_id=? AND market=? AND ts<=? ORDER BY ts DESC LIMIT 1',
                               (match_id, db_market(market), start_ts)).fetchone()
        if not row:
            return None, None
        self.close_ts = row[1]
        try:
            fair, side, ln = {}, None, line
            for names, po in json.loads(row[0]):
                try:
                    po = [float(x) for x in po]
                    if any(x <= 1 for x in po):
                        continue
                except (TypeError, ValueError):
                    continue
                l = None if split_fam(market)[1] == '1x2' else line_of(names[0])
                fair[(market, l)] = (fair_power(po), po, 0)
                if outcome in names:
                    side = names.index(outcome)
                    ln = l
            if side is None:
                return None, None
            r = true_ev(fair, market, ln, side, odds or 2.0)
            if r is None:
                return None, None
            ev, pw, pu = r
            cf = round((1 - pu) / pw, 3) if pw > 0 else None
            return cf, (ev if odds else None)
        except Exception:
            return None, None

    def score_for(self, fam, mid, start_ts):
        """(хозяева, гости) для расчёта: основное время, 1-й тайм или угловые; None — пока неизвестно"""
        pre = split_fam(fam)[0]
        if not pre:
            r = self.con.execute('SELECT COALESCE(x.ft1, r.home), COALESCE(x.ft2, r.away) FROM (SELECT ? AS m) q'
                                 ' LEFT JOIN results r ON r.match_id = q.m'
                                 ' LEFT JOIN ext_scores x ON x.match_id = q.m AND x.done = 1', (mid,)).fetchone()
            return tuple(r) if r and r[0] is not None and r[1] is not None else None
        for d in (self.stats_result(mid, start_ts), self.bk_result(mid, start_ts), self.ext_result(mid)):
            if d:
                h, a = (d['hthg'], d['htag']) if pre == 'h1_' else (d['hc'], d['ac'])
                if h is not None and a is not None:
                    return h, a
        return None

    def settle_paper(self):
        # у уже рассчитанных ставок без записанного счёта — дописать (для окна «что там было»)
        for pid, fam, mid, st in self.con.execute(
                "SELECT id, COALESCE(fam, event), match_id, start_ts FROM paper2 WHERE status IN"
                " ('выигрыш','проигрыш','возврат') AND res_h IS NULL LIMIT 200").fetchall():
            sc = self.score_for(fam, mid, st)
            if sc:
                self.con.execute('UPDATE paper2 SET res_h=?, res_a=? WHERE id=?', (sc[0], sc[1], pid))
        rows = self.con.execute("SELECT p.id, COALESCE(p.fam, p.event), p.outcome, p.line, p.odds, p.match_id, p.start_ts,"
                                " COALESCE(x.ft1, r.home), COALESCE(x.ft2, r.away) FROM paper2 p"
                                " LEFT JOIN results r ON r.match_id = p.match_id"
                                " LEFT JOIN ext_scores x ON x.match_id = p.match_id AND x.done = 1"
                                " WHERE p.status='open' AND COALESCE(p.fam, p.event) NOT LIKE 'h1!_%' ESCAPE '!'"
                                " AND COALESCE(p.fam, p.event) NOT LIKE 'c!_%' ESCAPE '!'"
                                " AND (x.ft1 IS NOT NULL OR (r.home IS NOT NULL AND p.start_ts < ?))",
                                (time.time() - 6 * 3600,)).fetchall()
        for pid, fam, outcome, line, odds, mid, start_ts in self.con.execute(
                "SELECT id, fam, outcome, line, odds, match_id, start_ts FROM paper2 WHERE status='open'"
                " AND (fam LIKE 'h1!_%' ESCAPE '!' OR fam LIKE 'c!_%' ESCAPE '!') AND start_ts < ?",
                (time.time() - 50 * 60,)).fetchall():      # с -49: не ждать 3 ч — каждый источник сам знает, окончателен ли счёт
            pre, base = split_fam(fam)
            h = a = None
            for d in (self.stats_result(mid, start_ts), self.bk_result(mid, start_ts), self.ext_result(mid)):
                if d:
                    h, a = (d['hthg'], d['htag']) if pre == 'h1_' else (d['hc'], d['ac'])
                    if h is not None and a is not None:
                        break
            if h is None or a is None:
                continue
            rows.append((pid, base, outcome, line, odds, mid, start_ts, h, a))
        n = 0
        fam_of = dict(self.con.execute("SELECT id, COALESCE(fam, event) FROM paper2 WHERE status='open'").fetchall())
        for pid, event, outcome, line, odds, mid, start_ts, home, away in rows:
            pr = settle_one(event, outcome, line, odds, home, away)
            st = 'выигрыш' if pr > 0 else ('проигрыш' if pr < 0 else 'возврат')
            cf, clv = self.closing_fair(mid, fam_of.get(pid, event), outcome, line, start_ts, odds)
            self.con.execute('UPDATE paper2 SET status=?, profit=?, closing_fair=?, clv=?, settled=?, res_h=?, res_a=?,'
                             ' close_ts=? WHERE id=?', (st, pr, cf, clv, time.time(), home, away,
                                                        self.close_ts if cf else None, pid))
            n += 1
        self.con.execute("UPDATE paper2 SET status='нет данных', settled=? WHERE status='open' AND start_ts < ?",
                         (time.time(), time.time() - 2 * 86400))
        # журнал CLV: после начала матча последняя цена Pinnacle до старта уже известна
        for mid, bk, mname, outcome, line, start_ts, odds, fam in self.con.execute(
                'SELECT match_id, bookmaker, market_name, outcome, line, start_ts, odds, fam FROM cand'
                ' WHERE done=0 AND start_ts < ?', (time.time() - 120,)).fetchall():
            fam = fam or ('1x2' if mname == '1Х2' else 'total')
            cf, clv = self.closing_fair(mid, fam, outcome, line, start_ts, odds)
            self.con.execute('UPDATE cand SET closing_fair=?, clv=?, done=1, close_ts=? WHERE match_id=? AND bookmaker=?'
                             ' AND market_name=? AND outcome=?',
                             (cf, clv, self.close_ts if cf else None, mid, bk, mname, outcome))
        self.con.commit()
        if n:
            log(f'рассчитано бумажных ставок: {n}')

    def poll_feeds(self):
        self.poll_pin()
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
                if f.fails in (3, 10) or f.fails % 20 == 0:     # единичный обрыв связи — не ошибка, следующий опрос через 5 с
                    add_error(f'{f.name} (прямая линия): {str(e).splitlines()[0][:150]}', f.name)
                if f.fails % 10 == 0:
                    f.version = None          # начать заново с полного снимка
                continue
            clear_error(f.name)
            try:
                self.save_scores(f)
            except Exception as e:
                add_error(f'{f.name}: счёт из лайва — {str(e)[:100]}', f.name + ' счёт')
            else:
                clear_error(f.name + ' счёт')
            self.direct_values_for(f)

    def save_scores(self, f):
        """счёт идущих матчей с сайта конторы → bk_scores (раз в 30 с); ts — когда матч последний раз был в лайве"""
        now = time.time()
        if now - getattr(f, 'scores_ts', 0) < 30:
            return
        f.scores_ts = now
        for eid, mid in list(f.match_map.items()):
            if mid and self.bk_known.get(eid) != mid:
                self.con.execute('INSERT OR REPLACE INTO bk_events VALUES (?,?)', (eid, mid))
                self.bk_known[eid] = mid
        corners = {e['parentId']: e['id'] for e in f.events.values()
                   if e.get('parentId') and e.get('name') == 'угловые'}

        def two(m):
            return m and isinstance(m.get('score1'), int) and isinstance(m.get('score2'), int)
        for e in list(f.events.values()):
            if e.get('level') != 1 or e.get('place') != 'live':
                continue
            mid = self.bk_known.get(e['id'])
            m = f.miscs.get(e['id'])
            if not mid or not two(m):
                continue
            rows = [('ft', m['score1'], m['score2'], m.get('comment'))]
            hm = re.match(r'\s*\((\d+)-(\d+)\)', m.get('comment') or '')
            if hm:                             # «(1-0)» появляется после перерыва — счёт первого тайма
                rows.append(('h1', int(hm.group(1)), int(hm.group(2)), None))
            c = f.miscs.get(corners.get(e['id']))
            if two(c):
                rows.append(('c', c['score1'], c['score2'], c.get('comment')))
            for part, s1, s2, cm in rows:
                self.con.execute('INSERT INTO bk_scores (match_id, part, s1, s2, comment, ts) VALUES (?,?,?,?,?,?)'
                                 ' ON CONFLICT (match_id, part) DO UPDATE SET s1=excluded.s1, s2=excluded.s2,'
                                 ' comment=excluded.comment, ts=excluded.ts', (mid, part, s1, s2, cm, now))
            if isinstance(m.get('timerSeconds'), (int, float)):
                self.con.execute('UPDATE bk_scores SET tsec=?, tdir=?, tupd=? WHERE match_id=? AND part=?',
                                 (m['timerSeconds'], m.get('timerDirection'), m.get('timerUpdateTimestampMsec'), mid, 'ft'))
        self.con.commit()

    def fotmob_live_step(self):
        """идущие матчи с открытыми бумажными ставками: счёт и угловые с FotMob (matchDetails), раз в 8 с один матч,
        каждый матч не чаще раза в 90 с"""
        now = time.time()
        if now - getattr(self, 'fml_last', 0) < 8 or self.browser is None:
            return
        self.fml_last = now
        row = self.con.execute(
            "SELECT p.match_id, l.url, m.home_en, m.away_en FROM paper2 p JOIN sofa_link l ON l.match_id = p.match_id"
            " JOIN matches m ON m.match_id = p.match_id LEFT JOIN ext_live x ON x.match_id = p.match_id"
            " WHERE p.status='open' AND p.start_ts < ? AND p.start_ts > ? AND l.url LIKE '%fotmob.com/match/%'"
            " AND (x.ts IS NULL OR x.ts < ?) GROUP BY p.match_id ORDER BY COALESCE(x.ts, 0) LIMIT 1",
            (now, now - 150 * 60, now - 90)).fetchone()
        if not row or self.ext.page(self.browser, 'fotmob', 'https://www.fotmob.com/') is None:
            return
        mid, url, he, ae = row
        fid = url.rstrip('/').split('/')[-1]
        j = self.ext.get('fotmob', f'https://www.fotmob.com/api/data/matchDetails?matchId={fid}') or {}
        teams = (j.get('header') or {}).get('teams') or []
        if len(teams) != 2:
            return
        # -63 (владелец 22.11: FotMob «Завершен», а у нас «идёт · 124 мин»): матч окончен — так и писать, а итог
        # с FotMob запросить сразу, не дожидаясь очередной 5-минутной попытки
        fin = 1 if (((j.get('header') or {}).get('status') or {}).get('finished')) else 0
        if fin:
            self.con.execute('UPDATE ext_scores SET last_try=0 WHERE match_id=? AND done=0', (mid,))
            self.ext_last = 0
        same = self.ext.pair(teams[0].get('name', ''), teams[1].get('name', ''), he or '', ae or '')
        if same is None:
            # хозяева неизвестны (нет английских названий) — не пишем: перевёрнутые угловые испортят инд. тотал
            self.con.execute('INSERT OR REPLACE INTO ext_live (match_id, ft1, ft2, c1, c2, ts, fin) VALUES (?,NULL,NULL,NULL,NULL,?,?)',
                             (mid, now, fin))
            self.con.commit()
            return
        ft = [teams[0].get('score'), teams[1].get('score')]
        c = None
        for g in ((((j.get('content') or {}).get('stats') or {}).get('Periods') or {}).get('All') or {}).get('stats') or []:
            for it in g.get('stats') or []:
                if it.get('key') == 'corners' and isinstance(it.get('stats'), list) and len(it['stats']) == 2:
                    c = list(it['stats'])
        if same is False:
            ft, c = ft[::-1], (c[::-1] if c else None)
        self.con.execute('INSERT OR REPLACE INTO ext_live (match_id, ft1, ft2, c1, c2, ts, fin) VALUES (?,?,?,?,?,?,?)',
                         (mid, ft[0], ft[1], c[0] if c else None, c[1] if c else None, now, fin))
        self.con.commit()

    def sofa_link_step(self):
        """страницы матчей со статистикой для окна «что там было». С -56 (владелец 22.11: «долго ищет»): раз в 15 с ВСЕ
        ненайденные матчи сразу сверяются со списками дней FotMob (один запрос на день, кэш 30 мин); Sofascore — запасной,
        по одному матчу за раз и только если FotMob матч не нашёл."""
        now = time.time()
        if now - getattr(self, 'sofa_last', 0) < 15 or self.browser is None:
            return
        self.sofa_last = now
        rows = []
        for mid, st, he, ae, url, lg in self.con.execute(
                "SELECT p.match_id, MIN(p.start_ts), m.home_en, m.away_en, m.url, MAX(p.league) FROM paper2 p"
                " LEFT JOIN matches m ON m.match_id = p.match_id"
                " LEFT JOIN sofa_link l ON l.match_id = p.match_id WHERE p.strategy='Б'"
                " AND (l.match_id IS NULL OR (l.url = '' AND l.tries < 3 AND l.last_try < ?))"
                " GROUP BY p.match_id ORDER BY ABS(MIN(p.start_ts) - ?) LIMIT 300", (now - 3600, now)):
            he, ae = en_names_any(he, ae, url)
            if he and is_women(lg) and not (en_tokens(he)[1] & {'w', 'women'}):
                # 22.11: «Мельбурн Виктори — Перт Глори», лига «Женская W-лига» — в адресе odds.ru пометки нет,
                # на FotMob «Melbourne Victory (W)»; без пометки en_sim даёт 0
                he, ae = he + '-w', ae + '-w'
            if he:
                rows.append((mid, st, he, ae))
        if not rows:
            return
        ext = self.ext
        fm_ok = ext.page(self.browser, 'fotmob', 'https://www.fotmob.com/') is not None
        miss = []
        for mid, st, he, ae in rows:
            m = ext.find_fotmob(he, ae, st)[0] if fm_ok else None
            if m and m.get('id'):
                self.save_link(mid, f"https://www.fotmob.com/match/{m['id']}", now)
            else:
                miss.append((mid, st, he, ae))
        sofa_ok = miss and ext.page(self.browser, 'sofascore', 'https://www.sofascore.com/ru/football') is not None
        if sofa_ok:
            mid, st, he, ae = miss.pop(0)
            e, _ = ext.find_sofa(he, ae, st)
            if e and e.get('slug') and e.get('customId'):
                self.save_link(mid, f"https://www.sofascore.com/ru/football/match/{e['slug']}/{e['customId']}", now)
            else:
                self.save_link(mid, '', now)
        if fm_ok:
            # Sofascore не пускает (или не открылся) — промах FotMob считается попыткой
            for mid, *_ in (miss if not sofa_ok or getattr(ext, 'blocked', {}).get('sofascore', 0) > now else []):
                self.save_link(mid, '', now)
        self.con.commit()

    def save_link(self, mid, url, now):
        self.con.execute('INSERT INTO sofa_link VALUES (?,?,1,?) ON CONFLICT (match_id) DO UPDATE SET url=excluded.url,'
                         ' tries=tries+1, last_try=excluded.last_try', (mid, url, now))

    def ext_step(self):
        """один сыгранный матч с открытой бумажной ставкой → Sofascore/FotMob (раз в 10 с). С -61 (владелец 22.11: «опять
        долго ждёт результат»): с 105-й минуты от начала, пока матч не окончен — каждые 5 мин (до 40 попыток), а не раз в 30 мин"""
        now = time.time()
        if now - self.ext_last < 10 or self.browser is None:
            return
        self.ext_last = now
        row = self.con.execute(
            "SELECT p.match_id, p.start_ts, m.home_en, m.away_en, p.league FROM paper2 p JOIN matches m ON m.match_id = p.match_id"
            " LEFT JOIN ext_scores x ON x.match_id = p.match_id WHERE p.status='open' AND p.start_ts < ?"
            " AND m.home_en IS NOT NULL AND (x.match_id IS NULL OR (x.done=0 AND x.tries < 40 AND x.last_try < ?))"
            " ORDER BY p.start_ts LIMIT 1", (now - 105 * 60, now - 300)).fetchone()
        if not row:
            return
        mid, start_ts, home_en, away_en, lg = row
        if is_women(lg) and not (en_tokens(home_en)[1] & {'w', 'women'}):
            # -78 (владелец 22.11: Мельбурн Виктори (ж) — FotMob «окончен», а расчёта нет): как в поиске ссылок (-59),
            # в адресе odds.ru пометки «женщины» нет, а на FotMob «(W)» — без неё матч не находился и итог не приходил
            home_en, away_en = home_en + '-w', away_en + '-w'
        d = self.ext.lookup(self.browser, home_en, away_en, start_ts)
        ft, ht, c = d.get('ft'), d.get('ht'), d.get('c')
        self.con.execute('INSERT INTO ext_scores (match_id, src, ext_id, ft1, ft2, ht1, ht2, c1, c2, done, tries, last_try)'
                         ' VALUES (?,?,?,?,?,?,?,?,?,?,1,?) ON CONFLICT (match_id) DO UPDATE SET src=excluded.src,'
                         ' ext_id=excluded.ext_id, ft1=excluded.ft1, ft2=excluded.ft2, ht1=excluded.ht1, ht2=excluded.ht2,'
                         ' c1=excluded.c1, c2=excluded.c2, done=excluded.done, tries=tries+1, last_try=excluded.last_try',
                         (mid, d.get('src'), d.get('ext_id'), *(ft or (None, None)), *(ht or (None, None)),
                          *(c or (None, None)), 1 if ft else 0, now))
        self.con.commit()
        if ft:
            self.settle_paper()                  # -61: итог пришёл — рассчитать сразу, не ждать обновления списка

    def ext_result(self, mid):
        r = self.con.execute('SELECT ft1, ft2, ht1, ht2, c1, c2 FROM ext_scores WHERE match_id=? AND done=1',
                             (mid,)).fetchone()
        if not r:
            return None
        return {'fthg': r[0], 'ftag': r[1], 'hthg': r[2], 'htag': r[3], 'hc': r[4], 'ac': r[5]}

    def bk_result(self, mid, start_ts):
        """тайм и угловые из лайва конторы; угловые — только если матч видели в лайве до ~90-й минуты
        и голы там совпали с итоговым счётом odds.ru"""
        sc = {p: (a, b, ts) for p, a, b, ts in
              self.con.execute('SELECT part, s1, s2, ts FROM bk_scores WHERE match_id=?', (mid,))}
        res = self.con.execute('SELECT home, away FROM results WHERE match_id=?', (mid,)).fetchone()
        if not res:
            # -82 (владелец 22.11: угловые Чоннам — Ансан «ждём результат», а ставки на голы того же времени уже рассчитаны):
            # итог матча для сверки голов — не только с odds.ru (он бывает с опозданием или не бывает), но и с FotMob/Sofascore
            res = self.con.execute('SELECT ft1, ft2 FROM ext_scores WHERE match_id=? AND done=1 AND ft1 IS NOT NULL',
                                   (mid,)).fetchone()
        d = {'hthg': None, 'htag': None, 'hc': None, 'ac': None}
        if 'h1' in sc and (not res or (sc['h1'][0] <= res[0] and sc['h1'][1] <= res[1])):
            d['hthg'], d['htag'] = sc['h1'][:2]
        if res and 'c' in sc and 'ft' in sc and tuple(sc['ft'][:2]) == tuple(res) \
                and sc['c'][2] >= start_ts + 105 * 60:
            d['hc'], d['ac'] = sc['c'][:2]
        return d

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
            fair = fair_for(mid, odds_data.get(mid, {}))
            if not fair:
                continue
            for key, bo in f.odds_of(ev['id']).items():
                if key not in fair:
                    continue
                p, po, pts = fair[key]
                if len(bo) != len(p):
                    continue
                names = outcome_names(key[0], key[1])
                market_name = market_label(key[0])
                for i, odd in enumerate(bo):
                    r = true_ev(fair, key[0], key[1], i, odd)
                    if r is None:                  # у Pinnacle нет соседних линий — возврат не оценить, пропуск
                        continue
                    ev_, p_win, p_push = r
                    if ev_ <= 0 or p_win <= 0:
                        continue
                    outcome = names[i]
                    k = ('direct', f.name, mid, market_name, outcome)
                    new[k] = {'bookmaker': f.name, 'match_id': mid, 'market': key[0], 'line': key[1],
                              'market_name': market_name,
                              'outcome': outcome, 'odds': odd, 'fair': round((1 - p_push) / p_win, 3),
                              'p_win': p_win, 'p_push': p_push, 'pin_odds': po[i],
                              'ev': ev_, 'source': 'сайт', 'pin_ts': pts, 'odds_ts': f.touched.get(ev['id'], f.last_full),
                              'bk_url': f.event_url(ev),
                              'bk_title': f"{ev.get('team1', '')} — {ev.get('team2', '')}" if ev.get('team1') else None,
                              'mo': (f.match_odds(ev) if hasattr(f, 'match_odds') else
                                     [(f.factors.get(ev['id'], {}).get(c) or {}).get('v') for c in F_MATCH_ODDS])}
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
                if mid in self.pin.fair_league:
                    continue
                mm = STATE.matches.get(mid)
                if mm:
                    mm['last_update'] = 0
            STATE.direct_cover[f.name] = cover
            STATE.status['feeds'][f.name] = {'last_ok': f.last_ok, 'events': len(evs), 'matched': matched,
                                             'host': f.host, 'error': '', 'fails': 0}
        for mid in set(urgent):
            self.pin.hurry(mid)

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
        busy = [u for u in urls if by_url[u].get('status') in BUSY_STATUSES]
        if busy:                                    # один повтор через пару секунд, уже без толпы запросов
            self.busy_log += [time.time()] * len(busy)
            time.sleep(2)
            for u, r in zip(busy, self.get_many(busy)):
                by_url[u] = r
        errors = 0
        last_err = ''
        now = time.time()
        for m in ms:
            datas = {}
            for mk in self.cfg['markets']:
                u = self.match_url(m['id'], mk)
                if by_url[u].get('status') == 404:       # матча на odds.ru уже нет (перенесён, начался) — не ошибка
                    continue
                try:
                    datas[mk] = self.parse_api(by_url[u], u)
                except Exception as e:
                    errors += 1
                    last_err = str(e).splitlines()[0][:200]
            self.apply_match(m, datas)
            if not datas:                           # ничего не получили — вернуть матч в очередь через ~15 с
                with STATE.lock:
                    mm = STATE.matches.get(m['id'])
                    if mm:
                        mm['last_update'] = now - self.interval_for(mm, now) + 15
        self.con.commit()
        still_busy = sum(1 for u in busy if by_url[u].get('status') in BUSY_STATUSES)
        if still_busy:
            self.batch_cur = max(2, self.batch_cur // 2)
            self.extra_pause = min(5.0, self.extra_pause + 1.0)
            self.ok_streak = 0
        elif not errors:
            self.ok_streak += 1
            if self.ok_streak >= 10:
                self.ok_streak = 0
                self.batch_cur = min(self.cfg['batch_matches'], self.batch_cur + 1)
                self.extra_pause = max(0.0, self.extra_pause - 0.5)
        self.busy_log = [t for t in self.busy_log if now - t < 600]
        if errors:
            add_error(f'{errors} из {len(urls)} запросов не удались (после повтора): {last_err}', 'odds.ru пакет')
        else:
            clear_error('odds.ru пакет')
        return errors, len(urls)

    def apply_match(self, m, datas):
        mid = m['id']
        new_vals = {}
        any_pin = False
        marg = []
        fair_ext = fair_for(mid, {}) or None
        for market, data in datas.items():
            vals, pin_rows = values_from_rates(data, fair_ext=fair_ext, market=market)
            pin_rows = pin_rows or (1 if fair_ext else 0)
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
                if compact:
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
                try:
                    self.ext_step()
                    self.sofa_link_step()
                    self.fotmob_live_step()
                    try:
                        if getattr(self, 'bb', None) is None:
                            self.bb = BasketMeasure(self.con)
                            self.hk = HockeyMeasure(self.con)
                        fb = next((x for x in self.feeds if x.name == 'Фонбет'), None)
                        pn = self.pin if getattr(self.pin, 'headers', None) else None
                        for sm in (self.bb, self.hk):
                            try:
                                sm.step(fb, pn)
                            except Exception as e:
                                sm.err = 'шаг: ' + str(e).splitlines()[0][:150]
                    except Exception as e:
                        add_error('замер баскетбола/хоккея: ' + str(e).splitlines()[0][:120], 'замер')
                    try:
                        if getattr(self, 'watch', None) is None:
                            self.watch = Watchdog(TG, self.con)
                        self.watch.step()
                    except Exception as e:
                        add_error('сообщения о работе (Telegram): ' + str(e).splitlines()[0][:120], 'watch')
                    # -83: разведка контор — по одной за раз (иначе цикл стоит минутами): первая через 5 мин после запуска,
                    # дальше раз в 3 мин; весь круг — раз в 12 ч; не пустившие больше не пробуются
                    if getattr(self, 'nbk_queue', None) is None:
                        self.nbk_queue, self.nbk_ts, self.nbk_round = list(NEW_BK_SITES), time.time() - 180 + 300, time.time()
                        self.new_bk = {'made': None, 'sites': []}
                    if not self.nbk_queue and time.time() - self.nbk_round > 12 * 3600:
                        shut = {x['bk'] for x in self.new_bk['sites'] if 'не пускает' in x.get('verdict', '')}
                        self.nbk_queue, self.nbk_round = [x for x in NEW_BK_SITES if x[0] not in shut], time.time()
                    if self.nbk_queue and time.time() - self.nbk_ts > 180 and self.browser is not None:
                        self.nbk_ts = time.time()
                        site = self.nbk_queue.pop(0)
                        try:
                            r = new_bk_recon(self.browser, wait_ms=25000, sites=[site])['sites']
                        except Exception as e:
                            r = [{'bk': site[0], 'home': site[1], 'error': str(e).splitlines()[0][:200], 'verdict': 'ошибка разведки'}]
                        self.new_bk['sites'] = [x for x in self.new_bk['sites'] if x['bk'] != site[0]] + r
                        self.new_bk['made'] = now_str()
                        with STATE.lock:
                            STATE.status['nbk'] = [[x['bk'], x.get('verdict', '')] for x in self.new_bk['sites']]
                    # -85 (пункт 3, Совет: «правила угловых не сверены»): правила контор прочитать один раз — через 15 мин
                    # после запуска, по одной странице раз в 3 мин (сайты Фонбета/PARI/Винлайна программу пускают)
                    if getattr(self, 'rules_q', None) is None:
                        self.rules_q, self.rules_ts, self.rules = list(RULES_PAGES), time.time() + 720, []
                    if self.rules_q and time.time() - self.rules_ts > 180 and self.browser is not None:
                        self.rules_ts = time.time()
                        self.rules.append(rules_recon(self.browser, *self.rules_q.pop(0)))
                    # -86: страницы матчей у открывшихся контор — через 6 мин после запуска, по одной раз в 3 мин
                    if getattr(self, 'evr_q', None) is None:
                        self.evr_q, self.evr_ts, self.evr = list(EVENT_RECON_SITES), time.time() + 180 - 90, []
                    if self.evr_q and time.time() - self.evr_ts > 180 and self.browser is not None:
                        self.evr_ts = time.time()
                        self.evr.append(bk_event_recon(self.browser, *self.evr_q.pop(0)))
                    if time.time() - getattr(self, 'bksr_ts', 0) > 3 * 3600 and self.browser is not None:
                        try:
                            r = bk_stats_recon(self.browser, self.con)
                            if r is not None:                 # нашёлся идущий матч — следующая разведка через 3 ч
                                self.bk_stats = r
                                # сайт показал проверку «вы не робот» — больше не ходим (обход защиты не делаем)
                                self.bksr_ts = time.time() + (10 ** 9 if r.get('blocked') else 0)
                            else:
                                self.bksr_ts = time.time() - 3 * 3600 + 600     # идущего матча нет — проверить через 10 мин
                        except Exception as e:
                            self.bk_stats = {'error': str(e).splitlines()[0][:200]}
                            self.bksr_ts = time.time()
                    wl = next((x for x in self.feeds if x.name == 'Винлайн'), None)
                    if wl is not None and wl.page is not None and wl.line.pm_events:
                        if getattr(self, 'wlr_ts', None) is None:
                            self.wlr_ts = time.time() - 6 * 3600 + 600     # первая разведка — через 10 мин, потом раз в 6 ч
                        if time.time() - self.wlr_ts > 6 * 3600:
                            self.wlr_ts = time.time()
                            try:
                                self.wl_recon = winline_event_recon(self.browser, wl)
                            except Exception as e:
                                self.wl_recon = {'error': str(e).splitlines()[0][:200]}
                    if getattr(self, 'recon_ts', None) is None:
                        self.recon_ts = time.time() - 1500          # первая разведка видов спорта — через 5 мин после запуска
                    if time.time() - self.recon_ts > 1800:
                        self.recon_ts = time.time()
                        self.recon_data = dict(sports_recon(self), made=now_str())
                except Exception as e:
                    add_error('статистика матчей (Sofascore/FotMob): ' + str(e).splitlines()[0][:120], 'ext')
                else:
                    clear_error('ext')
                ms = self.pick_batch(self.batch_cur)
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
                time.sleep(self.cfg['pause_between_requests'] + self.extra_pause)
                if time.time() - t_cycle > 60:
                    with STATE.lock:
                        STATE.status['cycle_info'] = (f'обновлено матчей за минуту: {n_cycle} · пакет {self.batch_cur}'
                                                      f' · «сервер занят» за 10 мин: {len(self.busy_log)}')
                        STATE.status['last_ok'] = now_str()
                    t_cycle, n_cycle = time.time(), 0
                fails = 0
                clear_error('цикл')
            except Exception as e:
                fails += 1
                add_error(str(e).splitlines()[0][:200], 'цикл')
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


def paper_kind_name(fam):
    pre, base = split_fam(fam or '')
    return {'1x2': 'Исход', 'ah': 'Фора', 'total': 'Тотал' if pre == 'c_' else 'Тотал голов',
            'tt1': 'Инд. тотал хозяев', 'tt2': 'Инд. тотал гостей'}.get(base, market_label(fam or '—'))


def paper_stats(con, stake_rub):
    def agg(where, args=()):
        r = con.execute('SELECT COUNT(*), SUM(status!="open"), SUM(status="выигрыш"), SUM(status="проигрыш"),'
                        ' SUM(status="возврат"), SUM(COALESCE(profit,0)), AVG(ev), AVG(clv), COUNT(clv), AVG(odds),'
                        ' SUM(CASE WHEN profit > 0 THEN profit * ? ELSE COALESCE(profit, 0) END)'
                        ' FROM paper2 WHERE status != "нет данных" AND ' + where, (1 - NDFL_RATE,) + tuple(args)).fetchone()
        n, done, w, l, push, prof, ev, clv, nclv, odds, prof_tax = r
        done, w, l = done or 0, w or 0, l or 0
        return {'n': n or 0, 'done': done, 'w': w, 'l': l, 'push': push or 0,
                'winpct': round(100 * w / (w + l)) if w + l else None,
                'profit_rub': round((prof or 0) * stake_rub),
                # -85 (владелец 22.11 «а как визуально это будет выглядеть?» — строка «после налога» под «Всего»):
                # 13% с чистого выигрыша каждой выигравшей ставки, проигрыши налог не уменьшают; льготу 4000 ₽ в год не учитываем
                'profit_tax_rub': round((prof_tax or 0) * stake_rub),
                'roi': round(100 * (prof or 0) / done, 1) if done else None,
                'ev': round(100 * ev, 1) if ev is not None else None,
                'odds': round(odds, 2) if odds else None,
                'clv': round(100 * clv, 1) if clv is not None else None, 'nclv': nclv or 0}
    out = {'stake_rub': stake_rub, 'strategies': [], 'cand': [], 'last': [], 'cuts': [], 'simple': []}
    # то, что видит владелец: способ Б, цены с сайта конторы — по видам ставок
    for (fam,) in con.execute("SELECT DISTINCT COALESCE(fam, event) FROM paper2 WHERE strategy='Б' AND src='сайт'"):
        a = agg("strategy='Б' AND src='сайт' AND COALESCE(fam, event) = ?", (fam,))
        if a['n']:
            pre, base = split_fam(fam or '')
            name = paper_kind_name(fam)
            out['simple'].append(dict(a, val=market_label(fam) if fam else '—', name=name,
                                      part={'': 'МАТЧ', 'h1_': '1-Й ТАЙМ', 'c_': 'УГЛОВЫЕ'}.get(pre, ''),
                                      kc={'': 'm', 'h1_': 'h1', 'c_': 'c'}.get(pre, 'm'),
                                      order=({'': 0, 'h1_': 1, 'c_': 2}.get(pre, 3),
                                             ['1x2', 'total', 'ah', 'tt1', 'tt2'].index(base)
                                             if base in ('1x2', 'total', 'ah', 'tt1', 'tt2') else 9)))
    # группы как на сайте Фонбета: МАТЧ, 1-Й ТАЙМ, УГЛОВЫЕ; внутри — Исход, Тотал, Фора, Инд. тоталы
    out['simple'].sort(key=lambda r: r['order'])
    out['simple_total'] = agg("strategy='Б' AND src='сайт'")
    # сами ставки — для окна «что там было» по нажатию на цифру в таблице (владелец 21.11)
    out['bets'] = []
    live = {}                                  # счёт идущих матчей из лайва Фонбета/PARI (свежее 3 мин)
    for lmid, part, a1, a2, cm, tsec, tdir, tupd in con.execute(
            'SELECT match_id, part, s1, s2, comment, tsec, tdir, tupd FROM bk_scores WHERE ts > ?', (time.time() - 180,)):
        live.setdefault(lmid, {})[part] = [a1, a2]
        if part == 'ft':
            live[lmid]['timer'] = {'tsec': tsec, 'tdir': tdir, 'tupd': tupd, 'ht': bool(re.match(r'\s*\(\d+-\d+\)', cm or ''))}
    for lmid, f1, f2, c1, c2, fin in con.execute('SELECT match_id, ft1, ft2, c1, c2, fin FROM ext_live WHERE ts > ?',
                                                  (time.time() - 300,)):
        if f1 is None and c1 is None and not fin:
            continue
        d = live.setdefault(lmid, {})
        if fin:
            d['fin'] = 1
        if 'c' not in d and c1 is not None and c2 is not None:
            d['c'] = [c1, c2]                  # угловых нет в лайве конторы — берём FotMob
        if 'ft' not in d and f1 is not None and f2 is not None:
            d['ft'] = [f1, f2]
    murl = dict(con.execute('SELECT match_id, url FROM matches'))
    surl = dict(con.execute("SELECT match_id, url FROM sofa_link WHERE url != ''"))
    for pid, mid, title, lg, st, bk, fam, oc, odds, ev, status, profit, rh, ra, bku, fair in con.execute(
            "SELECT id, match_id, title, league, start_ts, bookmaker, COALESCE(fam, event), outcome, odds, ev, status,"
            " profit, res_h, res_a, bk_url, fair"
            " FROM paper2 WHERE strategy='Б' AND src='сайт' AND status != 'нет данных' ORDER BY start_ts DESC"):
        pre = split_fam(fam or '')[0]
        out['bets'].append({'id': pid, 'title': title, 'league': lg, 'start_ts': st, 'bk': bk,
                            'part': {'': 'МАТЧ', 'h1_': '1-Й ТАЙМ', 'c_': 'УГЛОВЫЕ'}.get(pre, ''),
                            'name': paper_kind_name(fam), 'side': bet_view(fam or 'total', oc)[1],
                            'bet': bet_info({'match': title or '', 'market': fam, 'outcome': oc, 'market_name': ''})[0],
                            'odds': odds, 'ev': ev, 'status': status, 'oc': oc, 'res': [rh, ra] if rh is not None else None,
                            'base': split_fam(fam or '')[1], 'live': live.get(mid) if status == 'open' else None,
                            'chance': (ev / (odds - fair)) if (ev and odds and fair and odds > fair) else None,
                            'url': surl.get(mid) or murl.get(mid) or '', 'sofa': mid in surl, 'bk_url': bku or '',
                            'profit_rub': None if status == 'open' else round((profit or 0) * stake_rub)})
    sl = con.execute("SELECT SUM(url != ''), SUM(url = ''), COUNT(*) FROM sofa_link").fetchone()
    need = con.execute("SELECT COUNT(DISTINCT match_id) FROM paper2 WHERE strategy='Б'").fetchone()[0]
    noname = sum(1 for he, ae, u in con.execute(
        "SELECT m.home_en, m.away_en, m.url FROM (SELECT DISTINCT match_id FROM paper2 WHERE strategy='Б') p"
        " LEFT JOIN matches m ON m.match_id = p.match_id") if not en_names_any(he, ae, u)[0])
    out['sofa'] = {'found': sl[0] or 0, 'notfound': sl[1] or 0, 'need': need, 'noname': noname,
                   'error': (getattr(COLLECTOR, 'ext', None) and (COLLECTOR.ext.last_error
                                                                   or getattr(COLLECTOR.ext, 'last_http', ''))) or ''}
    out['nodata'] = con.execute("SELECT COUNT(*) FROM paper2 WHERE strategy='Б' AND src='сайт'"
                                " AND status='нет данных'").fetchone()[0]
    # для расчётов программы (владельцу не показываются): разрезы способа Б
    # разрезы основного способа Б (цены с сайта конторы): вид ставки, кф, перевес, за сколько до матча найдена
    cuts = [('Вид ставки', "COALESCE(fam, event)"),
            ('Контора', "bookmaker"),
            ('Лига', "league"),
            ('Свежесть цены Pinnacle', "CASE WHEN pin_age IS NULL THEN '—' WHEN pin_age < 120 THEN 'до 2 мин'"
                                       " WHEN pin_age < 600 THEN '2–10 мин' ELSE 'старше 10 мин' END"),
            ('День недели', "strftime('%w', start_ts + 3 * 3600, 'unixepoch')"),
            ('Коэффициент', "CASE WHEN odds < 1.5 THEN 'до 1.5' WHEN odds < 2 THEN '1.5–2' WHEN odds < 3 THEN '2–3'"
                            " ELSE '3–4' END"),
            ('Перевес', "CASE WHEN ev < 0.07 THEN '5–7%' WHEN ev < 0.10 THEN '7–10%' ELSE 'от 10%' END"),
            ('Найдена до матча', "CASE WHEN start_ts - created < 3600 THEN 'меньше часа'"
                                 " WHEN start_ts - created < 6 * 3600 THEN '1–6 ч' ELSE 'больше 6 ч' END")]
    for title, expr in cuts:
        rows = []
        for (val,) in con.execute(f"SELECT DISTINCT {expr} FROM paper2 WHERE strategy='Б' AND src='сайт'"):
            a = agg(f"strategy='Б' AND src='сайт' AND {expr} = ?", (val,))
            rows.append(dict(a, val=market_label(val) if title == 'Вид ставки' and val else val))
        rows.sort(key=lambda r: -r['n'])
        out['cuts'].append({'title': title, 'rows': rows})
    # журнал CLV по видам ставок (все подходящие ставки с сайта конторы)
    out['cand_fam'] = []
    for fam, n, nd, clv, pos in con.execute("SELECT COALESCE(fam, CASE WHEN market_name='1Х2' THEN '1x2' ELSE 'total' END),"
                                            " COUNT(*), COUNT(clv), AVG(clv), AVG(clv>0) FROM cand WHERE src='сайт'"
                                            " GROUP BY 1 ORDER BY 2 DESC"):
        out['cand_fam'].append({'val': market_label(fam), 'n': n, 'done': nd,
                                'clv': round(100 * clv, 1) if clv is not None else None,
                                'pos': round(100 * pos) if pos is not None else None})
    try:
        out['clv_dedup'] = clv_dedup(con)
    except Exception as e:
        out['clv_dedup'] = {'error': str(e)[:200]}
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


NDFL_RATE = 0.13          # НДФЛ с выигрыша (до 2.4 млн ₽ в год); первые 4000 ₽ выигрыша в год не облагаются — не учитываем


def clv_dedup(con):
    """-85, пункт 4 после Совета (владелец 22.11): проверка по цене Pinnacle перед матчем (CLV) без повторов.
    Только цены с сайта контор. Одна и та же ставка (матч + рынок + исход + линия) у Фонбета и PARI (одна линия)
    и у Винлайна — одна строка, с лучшим кф (владелец ставит одну ставку там, где кф выше). Ставки одного матча
    связаны, поэтому рядом — «по матчам»: сначала среднее внутри матча, потом среднее по матчам.
    «надёжная» — цена закрытия снята не раньше чем за 15 мин до начала (close_ts, с -84); у старых строк — неизвестно.
    Половины A/B (чётный/нечётный номер матча) — чтобы правило подбирать на одной, а проверять на другой."""
    import statistics
    best = {}
    for mid, fam, mname, oc, line, odds, clv, ev, bk, st, first, cts in con.execute(
            "SELECT match_id, fam, market_name, outcome, line, odds, clv, ev, bookmaker, start_ts, first_seen, close_ts"
            " FROM cand WHERE src='сайт' AND clv IS NOT NULL"):
        fam = fam or ('1x2' if mname == '1Х2' else 'total')
        k = (mid, fam, oc, line)
        if k not in best or odds > best[k]['odds']:
            best[k] = {'mid': mid, 'fam': fam, 'odds': odds, 'clv': clv, 'ev': ev, 'bk': bk,
                       # после налога: 13% с чистого выигрыша каждой выигравшей ставки, проигрыши не вычитаются (НК РФ
                       # ст. 214.7 на осень 2026; законопроект 617-9 о зачёте проигрышей ещё не принят). Шанс выигрыша
                       # по цене закрытия ≈ (1 + clv) / кф (возврат не учитывается)
                       'clv_tax': clv - NDFL_RATE * (1 + clv) * (odds - 1) / odds if odds and odds > 1 else clv,
                       'lead': (st - first) / 60 if st and first else None,
                       'close_age': (st - cts) / 60 if st and cts else None}
    rows = list(best.values())

    def summ(xs):
        if not xs:
            return {'n': 0}
        c = [x['clv'] for x in xs]
        bym = {}
        for x in xs:
            bym.setdefault(x['mid'], []).append(x['clv'])
        mm = [sum(v) / len(v) for v in bym.values()]
        return {'n': len(xs), 'matches': len(bym), 'clv': round(100 * sum(c) / len(c), 2),
                'clv_tax': round(100 * sum(x['clv_tax'] for x in xs) / len(xs), 2),
                'median': round(100 * statistics.median(c), 2), 'pos': round(100 * sum(v > 0 for v in c) / len(c)),
                'clv_by_match': round(100 * sum(mm) / len(mm), 2), 'pos_by_match': round(100 * sum(v > 0 for v in mm) / len(mm))}

    def part(x):
        pre = split_fam(x['fam'])[0]
        return {'': 'МАТЧ', 'h1_': '1-Й ТАЙМ', 'c_': 'УГЛОВЫЕ'}.get(pre, pre)

    def group(fn):
        g = {}
        for x in rows:
            g.setdefault(fn(x), []).append(x)
        return {k: summ(v) for k, v in sorted(g.items(), key=lambda kv: str(kv[0]))}
    return {
        'all': summ(rows),
        'reliable_close': summ([x for x in rows if x['close_age'] is not None and x['close_age'] <= 15]),
        'by_part': group(part),
        'by_part_reliable': {k: summ([x for x in rows if part(x) == k and x['close_age'] is not None and x['close_age'] <= 15])
                             for k in ('МАТЧ', '1-Й ТАЙМ', 'УГЛОВЫЕ')},
        'by_kind': group(lambda x: paper_kind_name(x['fam']) and (part(x) + ' · ' + paper_kind_name(x['fam']))),
        'by_bk': group(lambda x: x['bk']),
        'by_lead': group(lambda x: '?' if x['lead'] is None else '<1 ч' if x['lead'] < 60 else '1–3 ч' if x['lead'] < 180
                         else '3–12 ч' if x['lead'] < 720 else '>12 ч'),
        'by_ev': group(lambda x: '3–5%' if x['ev'] < 0.05 else '5–8%' if x['ev'] < 0.08 else '8%+'),
        'halves': {h: {p: summ([x for x in rows if x['mid'] % 2 == i and part(x) == p]) for p in ('МАТЧ', 'УГЛОВЫЕ')}
                   for i, h in ((0, 'A'), (1, 'B'))},
    }


def _no_secrets(x):
    """в отчёт не попадают ключи, токены, номера чатов"""
    if isinstance(x, dict):
        return {k: _no_secrets(v) for k, v in x.items()
                if not any(w in str(k).lower() for w in ('key', 'token', 'chat', 'secret', 'password', 'cookie'))}
    if isinstance(x, list):
        return [_no_secrets(v) for v in x]
    return x


def ExtStatsLastError():
    return getattr(COLLECTOR, 'ext', None) and COLLECTOR.ext.last_error or ''


# ================================================================ Баскетбол: замер вживую, только внутри программы (-66)
# Владелец 22.11: «пусть будет баскетбол, только внутри программы, в интерфейс не добавлять». Журнал bb_cand: каждая
# ставка Фонбета на баскетбол с перевесом ≥3% и кф ≤4 против Pinnacle; цена Pinnacle перед началом → CLV. Только в отчёт.
# Правила: Pinnacle — «Bets on the Game … include all overtimes» (pinnacle.com/en/future/betting-rules). Фонбет: в каталоге
# у баскетбола нет рынков «основное время», исход без ничьей; что тоталы с ОТ — по каталогу и общему правилу, не по
# странице правил конторы (её не нашли) — в отчёте видно, если линии систематически расходятся.
BB_FON_SPORT = 3          # «Баскетбол» в каталоге видов спорта Фонбета (разведка 22.11)
BB_PIN_SPORT = 4          # «Basketball» у Pinnacle (/sports, разведка 22.11)
RU_LAT = dict(zip('абвгдеёжзийклмнопрстуфхцчшщъыьэюя',
                  ['a', 'b', 'v', 'g', 'd', 'e', 'e', 'zh', 'z', 'i', 'i', 'k', 'l', 'm', 'n', 'o', 'p', 'r', 's', 't', 'u',
                   'f', 'h', 'ts', 'ch', 'sh', 'sch', '', 'i', '', 'e', 'iu', 'ia']))


def lat_key(name):
    """название команды → грубое латинское звучание (для сверки «Енисей» и «Enisey», «ЦСКА» и «CSKA»)"""
    t = (name or '').lower().replace('ё', 'е')
    t = ''.join(RU_LAT.get(ch, ch) for ch in t)
    t = re.sub(r'\([^)]*\)', ' ', t)
    for a, b in (('ts', 'c'), ('ck', 'k'), ('x', 'ks'), ('c', 'k'), ('w', 'v'), ('ph', 'f'), ('y', 'i'), ('kh', 'h'),
                 ('j', 'dzh'), ('ou', 'u'), ('ee', 'i'), ('oo', 'u')):
        t = t.replace(a, b)
    t = re.sub(r'[^a-z0-9 ]+', ' ', t)
    drop = {'bk', 'bc', 'kk', 'kb', 'fk', 'pbk', 'basket', 'basketbol', 'basketball', 'klub', 'club', 'the'}
    return ' '.join(w for w in t.split() if w not in drop)


def lat_sim(a, b):
    a, b = lat_key(a), lat_key(b)
    if not a or not b:
        return 0.0
    r = difflib.SequenceMatcher(None, a, b).ratio()
    wa, wb = a.split(), b.split()
    best = max((difflib.SequenceMatcher(None, x, y).ratio() for x in wa for y in wb if len(x) >= 3 and len(y) >= 3),
               default=0.0)
    return max(r, 0.9 * best)


class BasketMeasure:
    """Pinnacle по лигам по очереди + Фонбет из уже идущей прямой линии → журнал <table>. С -67 — для любого вида спорта:
    баскетбол (bb_cand) и хоккей (hk_cand). journal — какие рынки идут в журнал (правила совпадают), остальные — только
    в сверку линий check: средняя разница шансов Фонбета (без маржи) и Pinnacle на одной линии."""
    SPORT, FON_SPORT, PIN_SPORT, TABLE = 'баскетбол', BB_FON_SPORT, BB_PIN_SPORT, 'bb_cand'
    ML_CODES, NO_DRAW = (921, 923), True
    JOURNAL = {'1x2', 'total', 'ah', 'tt1', 'tt2'}
    pin_req = 0

    def __init__(self, con):
        self.con = con
        con.execute(f'CREATE TABLE IF NOT EXISTS {self.TABLE} (fon_id INT, fam TEXT, line REAL, side INT, outcome TEXT,'
                    ' teams TEXT, pin_teams TEXT, league TEXT, start_ts REAL, first_seen REAL, odds REAL, p_win REAL,'
                    ' p_push REAL, ev REAL, close_p REAL, close_push REAL, close_ts REAL, clv REAL,'
                    ' PRIMARY KEY (fon_id, fam, line, side))')
        con.commit()
        self.check = {}          # (id Фонбета, fam, line) -> (шанс Фонбета без маржи, шанс Pinnacle) — последние
        self.periods = collections.Counter()   # какие рынки Pinnacle вообще есть: (type, period, с ничьей?)
        self.leagues, self.leagues_ts, self.last = {}, 0, 0
        self.pin = {}            # id матча Pinnacle -> {home, away, start, league, fair, ts}
        self.map = {}            # id события Фонбета -> (id Pinnacle, перевёрнуты ли хозяева) или None
        self.map_try = {}
        self.log = []            # сопоставления для проверки в отчёте
        self.err = ''

    def poll_pin(self, pin):
        now = time.time()
        if now - BasketMeasure.pin_req < 3:      # не чаще раза в 3 с на все виды спорта вместе — футбольный Pinnacle главнее
            return False
        BasketMeasure.pin_req = now
        if now - self.leagues_ts > 600:
            self.leagues_ts = now
            for lg in pin.get(f'/sports/{self.PIN_SPORT}/leagues?all=false'):
                if lg.get('matchupCount', 0) > 0 and not lg.get('isHidden'):
                    self.leagues.setdefault(lg['id'], {'last': 0, 'next': None})['name'] = lg.get('name', '')

        def due(lg):
            ns = lg.get('next')
            iv = 900 if ns is None or ns - now > 12 * 3600 else (300 if ns - now > 3 * 3600 else 120)
            return now - lg['last'] >= iv
        for lid, lg in sorted(self.leagues.items(), key=lambda kv: kv[1]['last']):
            if not due(lg):
                continue
            lg['last'] = now
            mu = pin.get(f'/leagues/{lid}/matchups')
            mk = pin.get(f'/leagues/{lid}/markets/straight')
            self.ingest(lid, lg, mu, mk)
            return True                     # одна лига за вызов
        return False

    def ingest(self, lid, lg, matchups, markets):
        now, starts = time.time(), []
        for x in matchups or []:
            if x.get('type') != 'matchup' or x.get('isLive') or x.get('parentId'):
                continue
            ps = {q.get('alignment'): q.get('name') for q in x.get('participants') or []}
            try:
                st = datetime.datetime.fromisoformat(x['startTime'].replace('Z', '+00:00')).timestamp()
            except Exception:
                continue
            if not ps.get('home') or not ps.get('away'):
                continue
            self.pin.setdefault(x['id'], {})
            self.pin[x['id']].update(home=ps['home'], away=ps['away'], start=st, league=lg.get('name', ''))
            if st > now:
                starts.append(st)
        lg['next'] = min(starts) if starts else None
        fairs = {}
        for k in markets or []:
            if k.get('matchupId') in self.pin:
                self.periods[(k.get('type'), k.get('period'), any(q.get('designation') == 'draw' for q in k.get('prices') or []))] += 1
            if k.get('status', 'open') != 'open' or k.get('period') != 0 or k.get('matchupId') not in self.pin:
                continue
            pr = {q.get('designation'): q for q in k.get('prices') or []}
            f = fairs.setdefault(k['matchupId'], {})
            try:
                if k['type'] == 'moneyline' and {'home', 'away'} <= set(pr) and 'draw' not in pr:
                    po = [am_to_dec(pr['home']['price']), am_to_dec(pr['away']['price'])]
                    f[('1x2', None)] = (fair_power(po), po, now)        # «1x2» без ничьей: [хозяева, гости]
                elif k['type'] == 'total' and {'over', 'under'} <= set(pr):
                    po = [am_to_dec(pr['over']['price']), am_to_dec(pr['under']['price'])]
                    f[('total', round(float(pr['over']['points']), 2))] = (fair_power(po), po, now)
                elif k['type'] == 'team_total' and {'over', 'under'} <= set(pr) and k.get('side') in ('home', 'away'):
                    po = [am_to_dec(pr['over']['price']), am_to_dec(pr['under']['price'])]
                    f[('tt1' if k['side'] == 'home' else 'tt2', round(float(pr['over']['points']), 2))] = \
                        (fair_power(po), po, now)
                elif k['type'] == 'spread' and {'home', 'away'} <= set(pr):
                    po = [am_to_dec(pr['home']['price']), am_to_dec(pr['away']['price'])]
                    f[('ah', round(float(pr['home']['points']), 2))] = (fair_power(po), po, now)
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                continue
        for pid, f in fairs.items():
            if f:
                self.pin[pid]['fair'], self.pin[pid]['ts'] = f, now
        for pid in [p for p, m in self.pin.items() if m.get('start', now) < now - 6 * 3600]:
            self.pin.pop(pid, None)

    def match(self, ev):
        eid = ev['id']
        if eid in self.map and (self.map[eid] or time.time() - self.map_try.get(eid, 0) < 600):
            return self.map[eid]
        best, best_s = None, 0.0
        for pid, m in self.pin.items():
            if 'start' not in m or abs(m['start'] - ev.get('startTime', 0)) > 15 * 60:
                continue
            for swapped, (h, a) in ((False, (m['home'], m['away'])), (True, (m['away'], m['home']))):
                s1, s2 = lat_sim(ev.get('team1'), h), lat_sim(ev.get('team2'), a)
                sc = (s1 + s2) / 2
                if min(s1, s2) >= 0.45 and sc > best_s:
                    best, best_s = (pid, swapped), sc
        res = best if best_s >= 0.6 else None
        self.map[eid], self.map_try[eid] = res, time.time()
        if res:
            m = self.pin[res[0]]
            self.log = (self.log + [{'fon': f"{ev.get('team1')} — {ev.get('team2')}", 'pin': f"{m['home']} — {m['away']}",
                                     'swapped': res[1], 'score': round(best_s, 2)}])[-200:]
        return res

    def fon_odds(self, fs):
        out = {}
        a, b = fs.get(self.ML_CODES[0], {}).get('v'), fs.get(self.ML_CODES[1], {}).get('v')
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and a > 1 and b > 1 and not (self.NO_DRAW and 922 in fs):
            out[('1x2', None)] = [a, b]
        for fam, plist in (('total', F_TOTALS), ('ah', F_AH), ('tt1', F_TT1), ('tt2', F_TT2)):
            for x, y in plist:
                fx, fy = fs.get(x), fs.get(y)
                if not (fx and fy and isinstance(fx.get('v'), (int, float)) and isinstance(fy.get('v'), (int, float))):
                    continue
                if fx['v'] <= 1 or fy['v'] <= 1 or not isinstance(fx.get('p'), (int, float)):
                    continue
                out[(fam, round(fx['p'] / 100, 2))] = [fx['v'], fy['v']]
        return out

    def step(self, feed, pin):
        """раз в несколько секунд: одна лига Pinnacle; раз в 30 с — сверка всех баскетбольных событий Фонбета"""
        now = time.time()
        if pin is None or feed is None:
            return
        try:
            self.poll_pin(pin)
        except Exception as e:
            self.err = 'Pinnacle: ' + str(e).splitlines()[0][:120]
            return
        if now - self.last < 30:
            return
        self.last = now

        def is_bb(sid):
            sp, hops = feed.sports.get(sid), 0
            while sp and hops < 8:
                if sp.get('id') == self.FON_SPORT:
                    return True
                sp, hops = feed.sports.get(sp.get('parentId')), hops + 1
            return False
        n_ev = n_map = 0
        for ev in list(feed.events.values()):
            if ev.get('level') != 1 or ev.get('place') != 'line' or ev.get('_blocked') or ev.get('startTime', 0) < now + 60 \
                    or not is_bb(ev.get('sportId')):
                continue
            n_ev += 1
            got = self.match(ev)
            if not got:
                continue
            n_map += 1
            pid, swapped = got
            m = self.pin.get(pid) or {}
            fair = m.get('fair')
            if not fair or now - m.get('ts', 0) > 900:
                continue
            if swapped:                      # хозяева Фонбета = гости Pinnacle: развернуть цены
                fl = {}
                for (fam, ln), (p, po, ts) in fair.items():
                    if fam == '1x2':
                        fl[(fam, None)] = ([p[1], p[0]], [po[1], po[0]], ts)
                    elif fam == 'ah':
                        fl[(fam, round(-ln, 2))] = ([p[1], p[0]], [po[1], po[0]], ts)
                    elif fam in ('tt1', 'tt2'):
                        fl[('tt2' if fam == 'tt1' else 'tt1', ln)] = (p, po, ts)
                    else:
                        fl[(fam, ln)] = (p, po, ts)
                fair = fl
            for (fam, ln), odds in self.fon_odds(feed.factors.get(ev['id'], {})).items():
                fp = fair.get((fam, ln))
                if fp and ln is not None or (fp and fam == '1x2'):
                    try:
                        self.check[(ev['id'], fam, ln)] = (fair_power(odds)[0], fp[0][0], ev.get('startTime', 0))
                    except Exception:
                        pass
                if fam not in self.JOURNAL:
                    continue
                for side in (0, 1):
                    r = true_ev(fair, fam, ln, side, odds[side])
                    if r is None:
                        continue
                    ev_, pw, pp = r
                    key = (ev['id'], fam, ln if ln is not None else -999, side)
                    row = self.con.execute(f'SELECT 1 FROM {self.TABLE} WHERE fon_id=? AND fam=? AND line=? AND side=?',
                                           key).fetchone()
                    if row:
                        self.con.execute(f'UPDATE {self.TABLE} SET close_p=?, close_push=?, close_ts=? WHERE fon_id=? AND fam=?'
                                         ' AND line=? AND side=?', (pw, pp, m.get('ts'), *key))
                    elif ev_ >= 0.03 and odds[side] <= 4:
                        oc = (['П1', 'П2'][side] if fam == '1x2' else outcome_names(fam, ln)[side])
                        self.con.execute(f'INSERT INTO {self.TABLE} (fon_id, fam, line, side, outcome, teams, pin_teams, league,'
                                         ' start_ts, first_seen, odds, p_win, p_push, ev, close_p, close_push, close_ts)'
                                         ' VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                         (*key, oc, f"{ev.get('team1')} — {ev.get('team2')}",
                                          f"{m['home']} — {m['away']}", m.get('league'), ev.get('startTime'), now,
                                          odds[side], pw, pp, ev_, pw, pp, m.get('ts')))
        for k in [k for k, v in self.check.items() if v[2] < now - 86400]:
            self.check.pop(k, None)
        self.con.execute(f'UPDATE {self.TABLE} SET clv = odds * close_p + close_push - 1 WHERE clv IS NULL AND start_ts < ?'
                         ' AND close_p IS NOT NULL', (now,))
        self.con.commit()
        self.stat = {'fon_events': n_ev, 'matched': n_map, 'pin_matchups': len(self.pin), 'pin_leagues': len(self.leagues),
                     'made': now_str()}

    def report(self):
        rows = self.con.execute(f'SELECT * FROM {self.TABLE} ORDER BY first_seen').fetchall()
        cols = [c[1] for c in self.con.execute(f'PRAGMA table_info({self.TABLE})')]
        chk = {}
        for (eid, fam, ln), (pf, pp, _st) in self.check.items():
            chk.setdefault(fam, []).append(pf - pp)
        check = {fam: {'n': len(v), 'mean_gap': sum(v) / len(v), 'abs_gap': sum(abs(x) for x in v) / len(v)}
                 for fam, v in chk.items()}
        done = [r for r in rows if r[cols.index('clv')] is not None]
        clv = [r[cols.index('clv')] for r in done]
        return {'sport': self.SPORT, 'stat': getattr(self, 'stat', None), 'error': self.err, 'match_log': self.log[-60:],
                'line_check': check, 'pin_markets': [[*k, v] for k, v in self.periods.most_common(40)],
                'n': len(rows), 'n_closed': len(done), 'clv_mean': (sum(clv) / len(clv)) if clv else None,
                'clv_pos_share': (sum(c > 0 for c in clv) / len(clv)) if clv else None,
                'rows': [dict(zip(cols, r)) for r in rows]}



class HockeyMeasure(BasketMeasure):
    """-67, хоккей. Pinnacle: «Game-period bets include overtime and penalty shootouts», победителю буллитов — один гол
    (pinnacle.com/en/future/betting-rules). Фонбет: «Исходы» 921/922/923 — с ничьей (основное время), «Итоговая победа»
    7035/7036 — без ничьей. В журнал — только итоговая победа против moneyline Pinnacle (правила совпадают по названию).
    Тоталы/форы/инд. тоталы Фонбета — только в сверку линий: если Фонбет считает их по основному времени, его шанс «больше»
    будет заметно ниже, чем у Pinnacle (тот с ОТ и буллитом)."""
    SPORT, FON_SPORT, PIN_SPORT, TABLE = 'хоккей', 2, 19, 'hk_cand'
    ML_CODES, NO_DRAW = (7035, 7036), False
    JOURNAL = {'1x2'}


def winline_event_recon(browser, wl, n=2, wait_ms=15000):
    """-68 (владелец 22.11 «да»: угловые и инд. тоталы Винлайна). Шаг 1 — разведка: открыть в отдельной вкладке страницу
    1–2 популярных футбольных матчей Винлайна, 15 с слушать websocket (сайт сам просит роспись события), записать все
    рынки этого матча (код, название из справочника, линия, кф, как бы их понял WL_MARKETS) и текст страницы — для
    сверки по отчёту. Ничего не нажимает и не отправляет. В окно и бумагу не идёт."""
    now = time.time()
    evs = [e for e in wl.line.football(live=False) if e.get('start_ts') and now + 2 * 3600 < e['start_ts'] < now + 30 * 3600]
    evs.sort(key=lambda e: -(e.get('count_add_line') or 0))
    out = []
    for e in evs[:n]:
        line, q = WinlineLine(), []
        pg = browser.new_page(locale='ru-RU')
        try:
            def on_ws(ws):
                if 'data_ng' in ws.url:
                    ws.on('framereceived', lambda pl: q.append(bytes(pl)) if isinstance(pl, (bytes, bytearray)) else None)
            pg.on('websocket', on_ws)
            pg.goto(e['url'], wait_until='domcontentloaded', timeout=60000)
            pg.wait_for_timeout(wait_ms)
            bad, kinds = 0, collections.Counter()
            for fr in q:
                try:
                    for r in line.feed(fr) or []:
                        kinds[r.get('kind')] += 1
                except Exception:
                    bad += 1
            lines = [L for L in list(line.pm_lines.values()) + list(line.live_lines.values()) if L.get('event_id') == e['id']]
            rows = []
            for L in sorted(lines, key=lambda L: (L['tip'], L['id'])):
                tl = line.tiplines.get(L['tip']) or {}
                m = WL_MARKETS.get(L['tip'])
                key = None
                try:
                    key = market_key(L['tip'], L['koef'], L['favorite'], tl) if m else None
                except Exception:
                    pass
                rows.append({'tip': L['tip'], 'name': tl.get('name') or tl.get('title'), 'koef': L.get('koef'),
                             'fav': L.get('favorite'), 'V': L.get('V'), 'as': [key[0], key[1]] if key else None})
            try:
                text = pg.inner_text('body')[:12000]
            except Exception as x:
                text = 'текст не получен: ' + str(x)[:80]
            out.append({'event': e['id'], 'url': e['url'], 'teams': f"{e['home']} — {e['away']}", 'league': e.get('league'),
                        'frames': len(q), 'bad': bad, 'kinds': dict(kinds), 'n_lines': len(rows), 'lines': rows[:400],
                        'page_text': text})
        except Exception as x:
            out.append({'event': e['id'], 'error': str(x).splitlines()[0][:200]})
        finally:
            try:
                pg.close()
            except Exception:
                pass
    return {'made': now_str(), 'events': out}


# адреса страниц правил — по памяти, не проверены: что открылось — видно в отчёте (final_url, длина текста)
# Фонбет убран (-86): его страница матча показала программе капчу; Фонбет и так заменяем
RULES_PAGES = (('PARI', 'https://pari.ru/rules'), ('Винлайн', 'https://winline.ru/rules'))
RULES_WORDS = r'углов|corner|основное время|дополнительн|овертайм|не пробит|перепод|переигр|трансляци|прерван|источник'


def rules_recon(browser, name, url, wait_ms=8000):
    """-85: текст страницы правил конторы → куски вокруг слов про угловые и время матча (сверка с правилами Pinnacle:
    угловые назначенные, но не поданные — не считаются, перебитый — один, время для угловых не указано).
    Только читает страницу, ничего не нажимает. Только в отчёт."""
    pg = browser.new_page(locale='ru-RU')
    try:
        pg.goto(url, wait_until='domcontentloaded', timeout=60000)
        pg.wait_for_timeout(wait_ms)
        txt = pg.inner_text('body')
        links = pg.eval_on_selector_all('a[href]', 'as => as.map(a => [a.href, (a.innerText || "").trim()])'
                                        '.filter(x => /правил|rules|\\.pdf/i.test(x[0] + x[1])).slice(0, 60)')
        bits = []
        for m in re.finditer(RULES_WORDS, txt, re.I):
            a = max(0, m.start() - 300)
            if bits and a < bits[-1][1]:
                continue
            bits.append((a, m.end() + 500))
        return {'bk': name, 'url': url, 'final_url': pg.url, 'len': len(txt), 'head': txt[:1500],
                'bits': [txt[a:b] for a, b in bits[:40]], 'links': links}
    except Exception as e:
        return {'bk': name, 'url': url, 'error': str(e).splitlines()[0][:200]}
    finally:
        try:
            pg.close()
        except Exception:
            pass


def bk_stats_recon(browser, con, wait_ms=20000):
    """-76 (владелец 22.11: «у PARI есть статистика на этот матч — угловые, карточки, офсайды, — а тут она не появляется»).
    Разведка: открыть отдельной вкладкой страницу ИДУЩЕГО матча у Фонбета/PARI, где у нас открыта ставка, 20 с записывать
    ответы сайта (адрес, начало тела, если в нём есть угловые/статистика) и текст страницы — чтобы найти, откуда виджет
    статистики берёт угловые. Ничего не нажимает. Только в отчёт."""
    now = time.time()
    row = con.execute("SELECT bk_url, title FROM paper2 WHERE status='open' AND bk_url LIKE 'http%' AND bookmaker IN ('Фонбет','PARI')"
                      " AND start_ts < ? AND start_ts > ? ORDER BY (fam LIKE 'c_%') DESC, start_ts DESC LIMIT 1",
                      (now - 10 * 60, now - 100 * 60)).fetchone()
    if not row:
        return None
    url, title = row
    # -86: страница матча на fon.bet показала программе капчу «вы не робот» (отчёт 22.11 10:56). Обходить не делаем;
    # виджет статистики владелец видел на PARI (снимок 22.11: Чоннам — Ансан, угловые 0:0 на 45:23) — номера событий у
    # Фонбета и PARI общие, адрес тот же, меняется только сайт. Если и PARI покажет проверку — разведка останавливается.
    url = re.sub(r'^https?://(www\.)?fon\.bet/', 'https://pari.ru/', url)
    seen, hits = [], []
    pg = browser.new_page(locale='ru-RU')
    try:
        def on_resp(r):
            try:
                u = r.url
                if len(seen) < 300:
                    seen.append(u[:200])
                ct = (r.headers or {}).get('content-type', '')
                if 'json' not in ct and 'text' not in ct:
                    return
                body = r.text()
                low = body[:200000].lower()
                if any(w in low for w in ('corner', 'угл', 'statist', 'yellow', 'offside')) and len(hits) < 40:
                    k = max(0, min(low.find(w) for w in ('corner', 'угл', 'statist', 'yellow', 'offside') if w in low) - 300)
                    hits.append({'url': u[:300], 'len': len(body), 'part': body[k:k + 2500]})
            except Exception:
                pass
        pg.on('response', on_resp)
        ws_urls = []
        pg.on('websocket', lambda ws: ws_urls.append(ws.url[:200]))
        pg.goto(url, wait_until='domcontentloaded', timeout=60000)
        pg.wait_for_timeout(wait_ms)
        try:
            text = pg.inner_text('body')[:8000]
        except Exception as x:
            text = 'текст не получен: ' + str(x)[:80]
        blocked = bool(re.search(r'не с роботом|не робот|пройдите капчу|captcha', text, re.I))
        return {'made': now_str(), 'match': title, 'url': url, 'responses': seen, 'websockets': ws_urls, 'hits': hits,
                'page_text': text, 'blocked': blocked}
    except Exception as x:
        return {'made': now_str(), 'match': title, 'url': url, 'error': str(x).splitlines()[0][:200]}
    finally:
        try:
            pg.close()
        except Exception:
            pass


# -81: команды бота через «/» (имена — только латиница, так требует Telegram); слова «статус»/«сайт» работают как раньше
BOT_COMMANDS = [{'command': 'status', 'description': 'как работает программа: цены, бумага'},
                {'command': 'site', 'description': 'ссылка на сайт программы для телефона'}]


class Watchdog:
    """-78, пункт 1 после Совета (владелец 22.11 «согласен»): программа сама сообщает в Telegram, что жива и что сломалось.
    - при запуске: «🔄 Программа запущена» (так видно и перезапуск после обновления/падения/сна);
    - сводка в 07:30 и 19:30 МСК: работает ли, свежесть Pinnacle и контор, бумага;
    - тревога, если Pinnacle молчит 15 мин («проверьте VPN») или контора — 10 мин; повтор не чаще раза в час;
      «✅ Починилось», когда вернулось;
    - цикл программы стоял > 5 мин (ноутбук спал) — «💤 Программа стояла с … до …»;
    - на /status (или «статус») боту — та же сводка в ответ; /site — ссылка на сайт для телефона.
    Окно не трогает. Не даёт Windows уснуть от бездействия (SetThreadExecutionState), пока программа работает;
    закрытую крышку это не отменяет — это настройка Windows."""
    SUMMARY_AT = ('07:30', '19:30')

    def __init__(self, tg, con):
        self.tg, self.con = tg, con
        self.alarms = {}            # ключ -> время последней тревоги
        self.last_tick = time.time()
        self.last_check = 0
        self.sent_summary = set()
        self.upd_offset = None
        self.last_poll = 0
        self.cmds_set = False
        self.started = time.time()
        flag, by_update = HERE / 'restart_update.flag', False
        try:
            by_update = flag.exists() and time.time() - float(flag.read_text() or 0) < 900
            flag.unlink(missing_ok=True)
        except Exception:
            pass
        if not by_update:                  # перезапуск по кнопке «Обновить» — не сообщение, это владелец сделал сам
            self.tg.send(f'🔄 Программа «Ставки» запущена в {datetime.datetime.now(MSK):%H:%M} (версия {VERSION}).')
        if os.name == 'nt':
            try:
                import ctypes
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)    # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
            except Exception:
                pass

    def problems(self, now):
        out = {}
        with STATE.lock:
            feeds = {k: dict(v) for k, v in (STATE.status.get('feeds') or {}).items()}
        pin = feeds.get('Pinnacle') or {}
        if now - self.started > 900 and (not pin.get('last_ok') or now - pin['last_ok'] > 900):
            out['pin'] = 'Нет свежих цен Pinnacle больше 15 минут — проверьте VPN на ноутбуке.'
        for name in ('PARI', 'Фонбет', 'Винлайн'):
            f = feeds.get(name)
            if f is None:
                continue
            if now - self.started > 600 and (not f.get('last_ok') or now - f['last_ok'] > 600):
                out['feed:' + name] = f'Нет цен {name} больше 10 минут — сайт конторы не отвечает или сменился.'
        return out

    def summary(self, now):
        with STATE.lock:
            feeds = {k: dict(v) for k, v in (STATE.status.get('feeds') or {}).items()}
            tracked = STATE.status.get('tracked')
        lines = [f'✅ Работаю · {datetime.datetime.now(MSK):%d.%m %H:%M}' + (f' · матчей в работе {tracked}' if tracked else '')]
        for name in ('Pinnacle', 'PARI', 'Фонбет', 'Винлайн'):
            f = feeds.get(name)
            if f is None:
                continue
            age = now - f['last_ok'] if f.get('last_ok') else None
            lines.append(f"{'✓' if age is not None and age < 600 else '⚠'} {name}: " +
                         ('нет данных' if age is None else f'обновлён {int(age // 60)} мин назад'))
        try:
            ps = paper_stats(self.con, 100)
            t = ps.get('simple_total') or {}
            live = sum(1 for b in ps.get('bets') or [] if b.get('status') == 'open' and b.get('start_ts', 0) <= now)
            lines.append(f"Бумага: ставок {t.get('n', 0)}, рассчитано {t.get('done', 0)}, итог {t.get('profit_rub', 0):+} ₽"
                         + (f', сейчас идут матчей с нашими ставками: {live}' if live else ''))
        except Exception:
            pass
        return '\n'.join(lines)

    def poll_commands(self, now):
        """сообщение боту «статус» → сводка в ответ (раз в 20 с смотрим новые сообщения)"""
        if not self.tg.ready() or self.tg.connecting or now - self.last_poll < 20:
            return
        self.last_poll = now
        try:
            if not self.cmds_set:      # -81 (владелец 22.11: «сделай через / команды в боте») — меню команд у поля ввода
                r = self.tg.api('setMyCommands', {'commands': BOT_COMMANDS}, timeout=15)
                self.cmds_set = bool(r.get('ok'))
            if self.upd_offset is None:                       # старые сообщения пропускаем
                r = self.tg.api('getUpdates', {'offset': -1, 'timeout': 0}, timeout=15)
                res = r.get('result') or []
                self.upd_offset = (res[-1]['update_id'] + 1) if res else 0
                return
            r = self.tg.api('getUpdates', {'offset': self.upd_offset, 'timeout': 0}, timeout=15)
            for u in r.get('result') or []:
                self.upd_offset = u['update_id'] + 1
                txt = ((u.get('message') or {}).get('text') or '').lower()
                if txt.startswith('/start') or txt.startswith('/help'):
                    self.tg.send('Команды (кнопка «Меню» слева от поля ввода):\n'
                                 + '\n'.join(f"/{c['command']} — {c['description']}" for c in BOT_COMMANDS))
                elif 'статус' in txt or 'status' in txt:
                    self.tg.send(self.summary(now))
                elif 'сайт' in txt or 'ссылк' in txt or 'site' in txt:
                    pr = PROHOD
                    if pr and pr.link:
                        self.tg.send(f'Сайт программы с телефона: {pr.link}\nПароль — тот, что вы задали в «Подробнее». '
                                     'Ссылка меняется после перезапуска программы — тогда снова /site.')
                    else:
                        self.tg.send('Сайт с телефона пока не работает: ' + ((pr and pr.why) or 'проход ещё не поднят') +
                                     '. Пароль задаётся на ноутбуке: «Подробнее» → «Вход с телефона».')
        except Exception:
            pass

    def step(self):
        now = time.time()
        gap = now - self.last_tick
        self.last_tick = now
        if gap > 300:
            a = datetime.datetime.fromtimestamp(now - gap, MSK)
            self.tg.send(f'💤 Программа стояла с {a:%H:%M} до {datetime.datetime.now(MSK):%H:%M} (ноутбук спал или завис) — '
                         'ставки за это время не отслеживались. Сейчас снова работаю.')
        self.poll_commands(now)
        if now - self.last_check < 60:
            return
        self.last_check = now
        hm = datetime.datetime.now(MSK).strftime('%H:%M')
        day = datetime.datetime.now(MSK).strftime('%d.%m')
        for at in self.SUMMARY_AT:
            if at <= hm < at[:3] + '%02d' % (int(at[3:]) + 10) and (day, at) not in self.sent_summary:
                self.sent_summary.add((day, at))
                self.tg.send(self.summary(now))
        cur = self.problems(now)
        for k, msg in cur.items():
            if now - self.alarms.get(k, 0) > 3600:
                self.alarms[k] = now
                self.tg.send('⚠ ' + msg)
        for k in [k for k in self.alarms if k not in cur]:
            self.alarms.pop(k)
            self.tg.send('✅ Починилось: ' + ('цены Pinnacle снова идут.' if k == 'pin' else f'цены {k[5:]} снова идут.'))


# -83 (владелец 22.11: BetBoom и Лига Ставок не пускают программу — защита Qrator; обходить её не делаем; «проверь вообще
# все доступные бк, посмотрим, что открывается»): легальные конторы из списка ФНС (bookmaker-ratings.ru, 22.11) кроме
# уже подключённых (Фонбет, PARI, Винлайн), не пустивших (BetBoom, Лига Ставок), не принимающих ставки (Тенниси с 01.09.2026,
# Спортбет — не онлайн). Адреса сайтов — по памяти, НЕ проверены: что открылось — видно в отчёте (final_url, текст).
# Программа заходит как есть: если сайт закрыт защитой — записываем «не пускает» и дальше не пробуем.
# Итог 22.11 (отчёт 10:56): открылись Мелбет, Олимп, Марафон, Зенит, BETTERY (платформа Фонбета — та же линия, не
# независимая); не пускает Леон; Бет-М — соединение отклонено; Бетсити — пустая страница. С -86 проверяются только
# не проверенные до конца: Балтбет и Бетсити (дольше ждём)
NEW_BK_SITES = (('Балтбет', 'https://baltbet.ru/'), ('Бетсити', 'https://betcity.ru/'))
# -86, пункт 2: открывшиеся независимые конторы — страница одного матча: есть ли угловые, что за цены, откуда данные
EVENT_RECON_SITES = (('Олимп', 'https://www.olimp.bet/line/futbol-1', '/line/futbol-1/'),
                     ('Марафон', 'https://www.marathonbet.ru/su/betting/Football/Russia/Premier+League+-+22433', '/su/betting/Football/'),
                     ('Зенит', 'https://zenit.win/line/football/l_246211_russia-premier-league', '/line/football/'),
                     ('Мелбет', 'https://melbet.ru/ru/sport/pre-match/football', '/ru/sport/pre-match/football/'))


def bk_event_recon(browser, name, line_url, prefix, wait_ms=15000):
    """-86: страница линии футбола → самая «глубокая» ссылка с тем же началом адреса (страница матча) → 15 с записи:
    ответы json (начало и куски вокруг «углов»), кадры websocket, текст страницы (в нём видно рынки и кф).
    Только читает страницы, ничего не нажимает и не ставит. Только в отчёт."""
    from urllib.parse import urlparse
    pg = browser.new_page(locale='ru-RU', viewport={'width': 1400, 'height': 900})
    resp, wss = [], []
    rec = {'bk': name, 'line_url': line_url}
    try:
        pg.goto(line_url, wait_until='domcontentloaded', timeout=60000)
        pg.wait_for_timeout(8000)
        links = pg.eval_on_selector_all('a[href]', 'as => as.map(a => a.href)')
        cand = [h for h in links if urlparse(h).path.startswith(prefix) and '/live' not in h]
        cand.sort(key=lambda h: -len([x for x in urlparse(h).path.split('/') if x]))
        rec['links_found'] = len(cand)
        rec['event_url'] = ev = cand[0] if cand else None
        if not ev:
            rec['line_text'] = pg.inner_text('body')[:3000]
            return rec

        def on_resp(r):
            try:
                ct = (r.headers or {}).get('content-type', '')
                if ('json' in ct or 'text/plain' in ct) and len(resp) < 60:
                    b = r.text()
                    item = {'url': r.url[:300], 'status': r.status, 'len': len(b), 'head': b[:4000]}
                    sn = [b[max(0, m.start() - 150): m.end() + 250] for m in re.finditer(r'углов|corner', b, re.I)][:8]
                    if sn:
                        item['corner_snips'] = sn
                    resp.append(item)
            except Exception:
                pass

        def on_ws(ws):
            w = {'url': ws.url[:300], 'frames': []}
            wss.append(w)

            def fr(pl):
                if len(w['frames']) < 6:
                    w['frames'].append({'bin': len(pl)} if isinstance(pl, (bytes, bytearray)) else {'text': str(pl)[:3000]})
            ws.on('framereceived', fr)
        pg.on('response', on_resp)
        pg.on('websocket', on_ws)
        pg.goto(ev, wait_until='domcontentloaded', timeout=60000)
        pg.wait_for_timeout(wait_ms)
        txt = pg.inner_text('body')
        rec.update(final_url=pg.url, page_text=txt[:8000], corner_mentions=len(re.findall(r'углов', txt, re.I)),
                   responses=resp, websockets=wss)
        return rec
    except Exception as e:
        rec['error'] = str(e).splitlines()[0][:200]
        return rec
    finally:
        try:
            pg.close()
        except Exception:
            pass
BLOCK_MARKS = ('qrator', 'доступ запрещён', 'доступ запрещен', 'заблокирован системой защиты', 'just a moment',
               'checking your browser', 'ddos-guard', 'attention required', 'access denied', 'вы не робот')


def bk_verdict(site):
    """что вышло: не пускает / открылся, есть ли данные о коэффициентах (json или websocket)"""
    if site.get('error'):
        return 'не открылся: ' + site['error'][:80]
    txt = (site.get('page_text') or '').lower()
    urls = ' '.join(r.get('url', '') for r in site.get('responses') or []).lower()
    if any(m in txt for m in BLOCK_MARKS) or '__qrator' in urls or any(str(r.get('status')) in ('401', '403')
                                                                       and r.get('url', '').rstrip('/') == site.get('home', '').rstrip('/')
                                                                       for r in site.get('responses') or []):
        return 'не пускает программу (защита)'
    js = sum(1 for r in site.get('responses') or [] if r.get('len'))
    return f"открылся: ответов с данными {js}, websocket {len(site.get('websockets') or [])}"


def new_bk_recon(browser, wait_ms=25000, sites=None):
    """-78, пункт 2 после Совета (владелец 22.11: оставить PARI, вместо Фонбета — новая независимая контора;
    проверить BetBoom и Лигу Ставок). Разведка: открыть сайт, перейти на футбол, 25 с записывать, откуда страница берёт
    коэффициенты: адреса ответов (json), куски больших ответов, websocket и первые кадры, текст страницы. Ничего не
    нажимает, кроме перехода по ссылке «Футбол». Только в отчёт."""
    out = []
    for name, home in (sites if sites is not None else NEW_BK_SITES):
        resp, wss = [], []
        pg = browser.new_page(locale='ru-RU')
        try:
            def on_resp(r):
                try:
                    ct = (r.headers or {}).get('content-type', '')
                    item = {'url': r.url[:300], 'status': r.status, 'ct': ct[:60]}
                    if ('json' in ct or 'text/plain' in ct) and len(resp) < 150:
                        b = r.text()
                        item['len'] = len(b)
                        if len(b) > 1500:
                            item['head'] = b[:1500]
                    if len(resp) < 300:
                        resp.append(item)
                except Exception:
                    pass

            def on_ws(ws):
                rec = {'url': ws.url[:300], 'frames': []}
                wss.append(rec)

                def fr(pl):
                    if len(rec['frames']) < 8:
                        if isinstance(pl, (bytes, bytearray)):
                            rec['frames'].append({'bin': len(pl), 'b64': base64.b64encode(bytes(pl[:600])).decode()})
                        else:
                            rec['frames'].append({'text': str(pl)[:600]})
                ws.on('framereceived', fr)
            pg.on('response', on_resp)
            pg.on('websocket', on_ws)
            pg.goto(home, wait_until='domcontentloaded', timeout=60000)
            pg.wait_for_timeout(6000)
            links = pg.eval_on_selector_all('a[href]', 'as => as.map(a => [a.href, (a.innerText || "").trim()]).slice(0, 2000)')
            foot = next((h for h, t in links if re.search(r'football|futbol|soccer', h, re.I)), None) or \
                next((h for h, t in links if t.lower() == 'футбол'), None)
            if foot:
                pg.goto(foot, wait_until='domcontentloaded', timeout=60000)
            pg.wait_for_timeout(wait_ms)
            try:
                text = pg.inner_text('body')[:6000]
            except Exception as x:
                text = 'текст не получен: ' + str(x)[:80]
            out.append({'bk': name, 'home': home, 'football_url': foot, 'final_url': pg.url, 'responses': resp,
                        'websockets': wss, 'page_text': text})
            out[-1]['verdict'] = bk_verdict(out[-1])
        except Exception as x:
            out.append({'bk': name, 'home': home, 'error': str(x).splitlines()[0][:200], 'responses': resp[:50]})
            out[-1]['verdict'] = bk_verdict(out[-1])
        finally:
            try:
                pg.close()
            except Exception:
                pass
    return {'made': now_str(), 'sites': out}


def sports_recon(col):
    """-62, пункт «замер других видов спорта» (владелец 22.11 «давай дальше»), шаг 1 — разведка: какие виды спорта и
    рынки есть в линии Фонбета (коды ставок, примеры событий) и у Pinnacle (виды спорта и число матчей). Только в отчёт."""
    out = {}
    try:
        f = next((x for x in col.feeds if x.name == 'Фонбет'), None) or (col.feeds[0] if col.feeds else None)
        if f is not None:
            def top(sid):
                sp, hops = f.sports.get(sid), 0
                while sp and sp.get('parentId') and hops < 8:
                    nxt = f.sports.get(sp['parentId'])
                    if not nxt:
                        break
                    sp, hops = nxt, hops + 1
                return sp or {}
            now, by = time.time(), {}
            for e in list(f.events.values()):
                if e.get('level') != 1 or e.get('place') != 'line' or e.get('_blocked') or e.get('startTime', 0) < now:
                    continue
                t = top(e.get('sportId'))
                by.setdefault((t.get('id'), t.get('name')), []).append(e)
            fon = []
            for (tid, tname), evs in sorted(by.items(), key=lambda kv: -len(kv[1])):
                cnt = collections.Counter()
                for e in evs:
                    cnt.update((f.factors.get(e['id']) or {}).keys())
                smp = []
                for e in evs[:3]:
                    fs = f.factors.get(e['id']) or {}
                    smp.append({'id': e['id'], 'teams': f"{e.get('team1', '')} — {e.get('team2', '')}",
                                'segment': (f.sports.get(e.get('sportId')) or {}).get('name'),
                                'factors': {str(k): [v.get('v'), v.get('p'), v.get('pt')] for k, v in list(fs.items())[:80]},
                                'kids': [k.get('name') for k in f.events.values() if k.get('parentId') == e['id']][:12]})
                fon.append({'sport_id': tid, 'sport': tname, 'events': len(evs), 'top_codes': cnt.most_common(60),
                            'samples': smp})
            out['fonbet'] = fon[:15]
    except Exception as e:
        out['fonbet_error'] = str(e)[:200]
    try:
        out['pinnacle_sports'] = [{'id': x.get('id'), 'name': x.get('name'), 'matchups': x.get('matchupCount')}
                                  for x in col.pin.get('/sports') if x.get('matchupCount')]
    except Exception as e:
        out['pinnacle_error'] = str(e)[:200]
    return out


def build_report(con):
    """«Отчёт для разработки» (владелец 21.11): всё, что программа считает для себя, — одним файлом .zip с report.json.
    Владелец присылает его в чат, разработка смотрит, держится ли перевес вживую."""
    def rows(sql, args=()):
        cur = con.execute(sql, args)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    snap = STATE.snapshot()
    rep = {'version': VERSION, 'made': now_str(), 'made_ts': time.time(),
           'status': _no_secrets(snap.get('status')),
           'values_now': _no_secrets(snap.get('values')),
           'paper_stats': paper_stats(con, STATS_STAKE),
           'paper2': rows('SELECT * FROM paper2 ORDER BY id'),
           'cand': rows('SELECT * FROM cand ORDER BY first_seen'),
           'ext_scores': rows('SELECT * FROM ext_scores'),
           'bk_scores_parts': rows('SELECT part, COUNT(*) AS n FROM bk_scores GROUP BY part'),
           # -82: по матчам с открытыми ставками — что видел лайв конторы и что дал odds.ru (22.11 угловые Чоннам — Ансан
           # «ждём результат», а по отчёту не понять, был ли счёт угловых в лайве PARI)
           'open_bk_scores': rows("SELECT * FROM bk_scores WHERE match_id IN (SELECT match_id FROM paper2 WHERE status='open')"),
           'open_results': rows("SELECT * FROM results WHERE match_id IN (SELECT match_id FROM paper2 WHERE status='open')"),
           'counts': {t: con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
                      for t in ('matches', 'results', 'stats', 'pin', 'bk_events', 'bk_scores')},
           'sofa_link': rows('SELECT * FROM sofa_link'), 'ext_error': ExtStatsLastError(),
           'bet_matches': rows('SELECT * FROM matches WHERE match_id IN (SELECT match_id FROM paper2)'),
           'sofa_log': getattr(getattr(COLLECTOR, 'ext', None), 'sofa_log', []),
           'fm_miss': getattr(getattr(COLLECTOR, 'ext', None), 'fm_miss', [])}
    rep['sports_recon'] = getattr(COLLECTOR, 'recon_data', None)
    rep['winline_event_recon'] = getattr(COLLECTOR, 'wl_recon', None)
    rep['bk_stats_recon'] = getattr(COLLECTOR, 'bk_stats', None)
    rep['rules_recon'] = getattr(COLLECTOR, 'rules', None)
    rep['bk_event_recon'] = getattr(COLLECTOR, 'evr', None)
    rep['new_bk_recon'] = getattr(COLLECTOR, 'new_bk', None)
    # -84, пункт 3: где цена Pinnacle к началу сдвинулась больше чем на 15% — история её цены и с каким матчем Pinnacle
    # он сопоставлен (22.11: Мельбурн Виктори 1.40 → 2.13 — проверить, не чужой ли матч)
    try:
        jumps = rows('SELECT DISTINCT match_id, COALESCE(fam, CASE WHEN market_name = \'1Х2\' THEN \'1x2\' ELSE \'total\' END)'
                     ' AS fam FROM cand WHERE closing_fair > 0 AND fair > 0 AND ABS(fair / closing_fair - 1) > 0.15 LIMIT 40')
        pm = {}
        pin = getattr(COLLECTOR, 'pin', None)
        if pin is not None:
            for pid, mm in list(pin.match_map.items()):
                if mm:
                    r = pin.regular.get(pid) or {}
                    pm[mm[0]] = {'pin_id': pid, 'home': r.get('home'), 'away': r.get('away'), 'swapped': mm[1],
                                 'league': (pin.leagues.get(r.get('league')) or {}).get('name')}
        for j in jumps:
            j['pin_match'] = pm.get(j['match_id'])
            j['history'] = [[t, raw[:600]] for t, raw in con.execute(
                'SELECT ts, raw FROM pin WHERE match_id=? AND market=? ORDER BY ts DESC LIMIT 25',
                (j['match_id'], db_market(j['fam'])))]
        rep['pin_jumps'] = jumps
    except Exception as e:
        rep['pin_jumps'] = {'error': str(e)[:200]}
    for key, attr in (('basketball', 'bb'), ('hockey', 'hk')):
        sm = getattr(COLLECTOR, attr, None)
        if sm is not None:
            try:
                rep[key] = sm.report()
            except Exception as e:
                rep[key] = {'error': str(e)[:200]}    # собирается в потоке программы (браузер — не из окна)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('report.json', json.dumps(rep, ensure_ascii=False, default=str))
    return buf.getvalue()


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
    """Раз в минуту смотрит, есть ли на GitHub версия новее. Если есть — в окне появляется кнопка «Обновить»."""
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
        for _ in range(60):               # раз в минуту или сразу по кнопке
            if STATE.status.get('check_now'):
                STATE.status['check_now'] = False
                break
            time.sleep(1)


# ---------------------------------------------------------------- Telegram (просьба владельца 21.11)

class Telegram:
    """Уведомления о новых ставках основного способа (Б, цена с сайта конторы). Ключ бота и номер чата —
    в config.json; подключение — кнопкой в окне программы."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.q = []
        self.lock = threading.Lock()
        self.connecting = False
        threading.Thread(target=self.loop, daemon=True).start()

    def api(self, method, params, timeout=20):
        token = self.cfg.get('telegram_token', '')
        req = urllib.request.Request(f'https://api.telegram.org/bot{token}/{method}',
                                     data=json.dumps(params).encode('utf-8'),
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8'))

    def ready(self):
        return bool(self.cfg.get('telegram_token') and self.cfg.get('telegram_chat_id'))

    def send(self, text):
        if self.ready():
            with self.lock:
                self.q.append(text)

    def loop(self):
        while True:
            time.sleep(1)
            with self.lock:
                batch, self.q = self.q[:5], self.q[5:]
            for text in batch:
                try:
                    self.api('sendMessage', {'chat_id': self.cfg['telegram_chat_id'], 'text': text,
                                             'disable_web_page_preview': True})
                    set_tg('подключён', ok=True)
                except Exception as e:
                    set_tg('не отправилось: ' + str(e).splitlines()[0][:120], ok=False)
                time.sleep(1)

    def connect(self, token):
        """владелец вставил ключ бота и написал боту что угодно — находим чат и запоминаем"""
        if self.connecting:
            return
        self.connecting = True
        self.cfg['telegram_token'] = token.strip()
        self.cfg['telegram_chat_id'] = ''
        set_tg('проверяю ключ…', ok=None)
        try:
            me = self.api('getMe', {})
            name = (me.get('result') or {}).get('username', '?')
            set_tg(f'ключ подходит (бот @{name}). Откройте этого бота в Telegram и напишите ему «старт» — жду 3 минуты', ok=None)
            t_end = time.time() + 180
            offset = 0
            while time.time() < t_end:
                upd = self.api('getUpdates', {'offset': offset, 'timeout': 20}, timeout=30)
                for u in upd.get('result') or []:
                    offset = u['update_id'] + 1
                    msg = u.get('message') or {}
                    chat = (msg.get('chat') or {}).get('id')
                    if chat:
                        self.cfg['telegram_chat_id'] = chat
                        save_config_keys({'telegram_token': self.cfg['telegram_token'], 'telegram_chat_id': chat})
                        self.api('sendMessage', {'chat_id': chat, 'text': 'Программа «Ставки» подключена. Сюда будут '
                                                 'приходить ставки основного способа, как только они появятся.'})
                        set_tg('подключён', ok=True)
                        log('Telegram подключён')
                        return
            set_tg('боту так и не написали — нажмите «Подключить» ещё раз', ok=False)
        except Exception as e:
            set_tg('ключ не подошёл или Telegram недоступен: ' + str(e).splitlines()[0][:120], ok=False)
        finally:
            self.connecting = False


def set_tg(text, ok):
    with STATE.lock:
        STATE.status['telegram'] = {'text': text, 'ok': ok}


def tg_text(v, code):
    bet, where = bet_info(v)
    bet = f'{bet_kind(event_of(v))[0]}: {bet}'
    start = datetime.datetime.fromtimestamp(v['start_ts'], MSK).strftime('%d.%m %H:%M')
    return (f"{v['bookmaker']}: {bet} — кф {v['odds']}\n{v.get('match', '')}, {start} МСК\n"
            f"шанс ~{round(100 * v['chance'])}% · перевес +{100 * v['ev']:.1f}%\n"
            f"брать, если кф не ниже {((1.05 - (v.get('p_push') or 0)) / v['p_win'] if v.get('p_win') else v['fair'] * 1.05):.2f}"
            + (f"\n{v['bk_url']}" if v.get('bk_url') else ''))


def save_config_keys(upd):
    p = HERE / 'config.json'
    try:
        cur = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
    except Exception:
        cur = {}
    cur.update(upd)
    p.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding='utf-8')


TG = None


# ---------------------------------------------------------------- статистика матчей (football-data.co.uk)

FD_DIVS = ['E0', 'E1', 'E2', 'E3', 'EC', 'SC0', 'SC1', 'SC2', 'SC3', 'D1', 'D2', 'I1', 'I2', 'SP1', 'SP2',
           'F1', 'F2', 'N1', 'B1', 'P1', 'T1', 'G1']
FD_URL = 'https://www.football-data.co.uk/mmz4281/{season}/{div}.csv'
FD_COLS = ['FTHG', 'FTAG', 'HTHG', 'HTAG', 'HC', 'AC', 'HY', 'AY', 'HF', 'AF', 'HS', 'AS', 'HST', 'AST']


def fd_season(dt):
    y = dt.year if dt.month >= 7 else dt.year - 1
    return f'{y % 100:02d}{(y + 1) % 100:02d}'


def fd_parse(text, div):
    """строки CSV football-data → кортежи для таблицы stats (дата — ГГГГ-ММ-ДД)"""
    import csv
    import io
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        try:
            d = r.get('Date') or ''
            dd, mm, yy = d.split('/')
            yy = ('20' + yy) if len(yy) == 2 else yy
            vals = []
            for c in FD_COLS:
                x = (r.get(c) or '').strip()
                vals.append(int(float(x)) if x else None)
            if vals[0] is None or not r.get('HomeTeam'):
                continue
            out.append((div, f'{yy}-{int(mm):02d}-{int(dd):02d}', r['HomeTeam'].strip(), r['AwayTeam'].strip(), *vals))
        except (ValueError, KeyError, AttributeError):
            continue
    return out


def stats_loop():
    """раз в 6 часов скачивает таблицы текущего сезона 22 лиг; своя связь с базой (отдельный поток)"""
    while True:
        con = None
        try:
            con = sqlite3.connect(str(HERE / 'stavki.sqlite3'), timeout=30)
            season = fd_season(datetime.datetime.now(MSK))
            n, errs = 0, []
            for div in FD_DIVS:
                try:
                    req = urllib.request.Request(FD_URL.format(season=season, div=div),
                                                 headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req, timeout=40) as r:
                        raw = r.read()
                    try:
                        text = raw.decode('utf-8-sig')
                    except UnicodeDecodeError:
                        text = raw.decode('latin-1')
                    rows = fd_parse(text, div)
                    con.executemany('INSERT OR REPLACE INTO stats VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', rows)
                    con.commit()
                    n += len(rows)
                except Exception as e:
                    errs.append(f'{div}: {str(e).splitlines()[0][:60]}')
                time.sleep(2)
            total = con.execute('SELECT COUNT(*) FROM stats').fetchone()[0]
            with STATE.lock:
                STATE.status['stats'] = {'last_ok': time.time() if n else None, 'rows': total,
                                         'error': '; '.join(errs[:3]) if errs else ''}
            log(f'статистика матчей: загружено {n} строк из {len(FD_DIVS) - len(errs)} лиг, всего в базе {total}')
        except Exception as e:
            with STATE.lock:
                STATE.status['stats'] = {'last_ok': None, 'rows': 0, 'error': str(e).splitlines()[0][:120]}
        finally:
            if con:
                con.close()
        time.sleep(6 * 3600)


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
    global TG
    TG = Telegram(cfg)
    global CFG, PROHOD
    CFG = cfg
    PROHOD = Prohod(cfg)
    set_tg('подключён' if TG.ready() else 'не подключён', ok=True if TG.ready() else None)
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
    threading.Thread(target=stats_loop, daemon=True).start()
    global COLLECTOR
    COLLECTOR = Collector(cfg, con)
    COLLECTOR.run()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception:
        log('Программа остановилась:\n' + traceback.format_exc())
        input('Нажмите Enter, чтобы закрыть окно')

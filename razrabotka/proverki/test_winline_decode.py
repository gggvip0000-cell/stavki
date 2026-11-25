# -*- coding: utf-8 -*-
"""Сверка winline_decode с записанной разведкой (bet/rw).

Что проверяется:
  1. Все кадры data_ng разбираются без ошибок, разбор доходит ровно до конца каждого сообщения.
  2. Страница линии футбола (line.html, снята в 01:38:56): для каждого из 10 лайв-матчей
     исход/фора/тотал матча и строки «1 тайм»/«2 тайм» совпадают с нашими кф на момент снимка.
  3. Главная (match.html, снята в 01:40:03 после переподключения): мини-карточки футбола —
     исход 1X2 или «Тотал (осн. время)» (кф, линия и список доступных линий), время «Сегодня ЧЧ:ММ»
     и «+N» у прематча.
  4. Матч 17134546 (Даллас — Портленд): полный набор, который видно на странице.
  5. Внутренняя согласованность прематча: знак форы по байту favorite совпадает с фаворитом по 1X2,
     фора 0 совпадает с «ставкой без ничьей», посчитанной из 1X2; кф форы монотонны по линии.
Запуск: python3 test_winline_decode.py   (из любой папки)
"""
import base64
import datetime
import html as H
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import winline_decode as W  # noqa: E402

RW = os.path.join(HERE, 'rw')
MSK = datetime.timezone(datetime.timedelta(hours=3))
LINE_SAVED = datetime.datetime(2026, 11, 22, 1, 38, 56, 500000, tzinfo=MSK).timestamp()
MATCH_SAVED = datetime.datetime(2026, 11, 22, 1, 40, 3, 500000, tzinfo=MSK).timestamp()


def load_frames():
    d = json.load(open(os.path.join(RW, 'ws_frames.json'), encoding='utf-8'))
    return [(f['t'], base64.b64decode(f['b64'])) for f in d
            if 'data_ng' in f['url'] and f['dir'] == 'in' and not f.get('text')]


def states_at(frames, t_cut, around=3.0):
    """Снимки состояния: на момент t_cut и для каждого кадра в окне ±around с (для «гонки» снимка)."""
    L = W.WinlineLine()
    snaps = []
    for t, b in frames:
        if t > t_cut + around:
            break
        L.feed(b)
        if t >= t_cut - around:
            snaps.append((t, {e['id']: e for e in L.football()}))
    main = None
    for t, s in snaps:
        if t <= t_cut:
            main = s
    return main, [s for _, s in snaps]


# ---------------------------------------------------------------- DOM
def clean(h):
    h = re.sub(r'<!--.*?-->', '', h, flags=re.S)
    h = re.sub(r'<svg.*?</svg>', '<svg/>', h, flags=re.S)
    h = re.sub(r'\s_ng(content|host)-[\w-]+=""', '', h)
    return h


def fnum(s):
    s = s.strip()
    return None if s in ('-', '') else float(s)


def dom_line_page():
    h = clean(open(os.path.join(RW, 'line.html'), encoding='utf-8').read())
    out = {}
    parts = re.split(r'<ww-feature-block-event-dsk[^>]*id="eventId-(\d+)"', h)
    for k in range(1, len(parts), 2):
        ev = int(parts[k])
        body = parts[k + 1].split('</ww-feature-block-event-dsk>')[0]
        names = [H.unescape(x).strip() for x in
                 re.findall(r'<div class="name ng-star-inserted">([^<]*)</div>', body)][:2]
        rows = []
        for rb in re.split(r'<div class="card__body[^"]*">', body)[1:]:
            m = re.match(r'\s*<div class="(?:match-row-label|period-name)">([^<]*)</div>', rb)
            label = m.group(1).strip() if m else '?'
            mk = []
            for seg in re.split(r'<ww-feature-event-market-dsk', rb)[1:]:
                seg = seg.split('</ww-feature-event-market-dsk>')[0]
                mk.append([H.unescape(x).strip() for x in re.findall(r'<span[^>]*>([^<]*)</span>', seg)])
            rows.append((label, mk))
        out[ev] = {'names': names, 'rows': rows}
    return out


def dom_mini_cards():
    h = clean(open(os.path.join(RW, 'match.html'), encoding='utf-8').read())
    out = {}
    for m in re.finditer(r'<a href="/stavki/event/(\d+)">(.*?)</footer>', h, flags=re.S):
        ev = int(m.group(1))
        b = m.group(2)
        if ev in out:
            continue
        mid = re.search(r'<div class="coefficient-middle[^"]*">(.*?)<div class="coefficient-middle__selector', b, re.S)
        sel = re.search(r'coefficient-middle__selector[^>]*>(.*?)</ul>', b, re.S)
        out[ev] = {
            'names': [H.unescape(x).strip() for x in re.findall(r'<span class="name[^"]*"[^>]*>\s*([^<]*?)\s*<', b)],
            'coefs': [x.strip() for x in re.findall(r'<span class="button__coef-title">([^<]*)</span>', b)],
            'middle': [x.strip() for x in re.findall(r'<span[^>]*>([^<]*)</span>', mid.group(1))] if mid else [],
            'lines': [float(x) for x in re.findall(r'<span[^>]*>\s*([0-9.]+)\s*</span>', sel.group(1))] if sel else [],
            'footer': [H.unescape(x).strip() for x in re.findall(r'class="footer__time[^"]*">([^<]*)<', b)],
        }
    return out


def parse_handicap_mid(s):
    """'- 2.5 +' -> -2.5 (минус у хозяев), '+ 1.5 -' -> +1.5, '0' -> 0.0."""
    s = s.replace('−', '-').strip()
    m = re.match(r'^([-+])\s*([0-9.]+)\s*([-+])$', s)
    if m:
        return -float(m.group(2)) if m.group(1) == '-' else float(m.group(2))
    return float(s)


# ---------------------------------------------------------------- проверки
class Tally:
    def __init__(self):
        self.ok = 0
        self.fail = []
        self.by = {}

    def check(self, cond, what, fam=None):
        if cond:
            self.ok += 1
            if fam:
                self.by[fam] = self.by.get(fam, 0) + 1
        else:
            self.fail.append(what)


def match_any(snaps, ev, key, want):
    """Есть ли в окне снимков (±3 с вокруг сохранения страницы) ровно такие кф."""
    for s in snaps:
        e = s.get(ev)
        if e and e['markets'].get(key) == want:
            return True
    return False


def test_frames_parse(frames):
    n_msgs = 0
    kinds = {}
    tips = {}
    for t, b in frames:
        recs = W.decode_frame(b, tips)
        n_msgs += 1
        for r in recs:
            kinds[r['kind']] = kinds.get(r['kind'], 0) + 1
    assert kinds.get('tipline', 0) > 800, kinds
    assert kinds.get('pm_line', 0) > 60000, kinds        # два полных снимка прематча по 34411 линий
    assert kinds.get('live_line', 0) > 20000, kinds
    assert kinds.get('pm_event', 0) == 2 * 2616, kinds
    print('  кадров data_ng: %d, записей по видам: %s' % (n_msgs, dict(sorted(kinds.items()))))


def test_line_page(frames, T):
    main, snaps = states_at(frames, LINE_SAVED)
    dom = dom_line_page()
    assert len(dom) == 10, len(dom)
    fam_prefix = {'Матч': '', '1 тайм': 'h1_', '2 тайм': 'h2_'}
    for ev, card in dom.items():
        e = main.get(ev)
        T.check(e is not None, 'line: нет события %d' % ev)
        if e is None:
            continue
        T.check([e['home'], e['away']] == card['names'], 'line %d: команды %s / %s' % (ev, [e['home'], e['away']], card['names']))
        for label, mks in card['rows']:
            pre = fam_prefix[label]
            x12, hcp, tot = mks
            if any(v != '-' for v in x12):
                want = [fnum(v) for v in x12]
                key = (pre + '1x2', None)
                T.check(match_any(snaps, ev, key, want),
                        'line %d %s 1x2: DOM %s, у нас %s' % (ev, label, want, e['markets'].get(key)), pre + '1x2')
            if hcp[1] != '-':
                line = parse_handicap_mid(hcp[1])
                want = [fnum(hcp[0]), fnum(hcp[2])]
                key = (pre + 'ah', line)
                T.check(match_any(snaps, ev, key, want),
                        'line %d %s фора %s: DOM %s, у нас %s' % (ev, label, line, want, e['markets'].get(key)), pre + 'ah')
            if tot[1] != '-':
                line = float(tot[1])
                want = [fnum(tot[2]), fnum(tot[0])]       # на странице слева «М», справа «Б»
                key = (pre + 'total', line)
                T.check(match_any(snaps, ev, key, want),
                        'line %d %s тотал %s: DOM М/Б %s, у нас Б/М %s' % (ev, label, line, want[::-1], e['markets'].get(key)), pre + 'total')


def test_main_page(frames, T):
    main, snaps = states_at(frames, MATCH_SAVED)
    dom = dom_mini_cards()
    n_fb = 0
    for ev, card in dom.items():
        e = main.get(ev)
        if e is None:
            continue            # не футбол (хоккей, киберспорт...) или нет в снимке
        n_fb += 1
        names = [x for x in card['names']]
        T.check(all(n in (e['home'], e['away']) for n in names), 'main %d: команды %s vs %s' % (ev, names, (e['home'], e['away'])))
        foot = card['footer']
        if len(card['coefs']) == 3:
            want = [fnum(v) for v in card['coefs']]
            T.check(match_any(snaps, ev, ('1x2', None), want),
                    'main %d 1x2: DOM %s, у нас %s' % (ev, want, e['markets'].get(('1x2', None))), '1x2 (главная)')
        elif len(card['coefs']) == 2 and 'Тотал (осн. время)' in foot:
            assert card['middle'][0] == 'М' and card['middle'][2] == 'Б', card['middle']
            line = float(card['middle'][1])
            want = [fnum(card['coefs'][1]), fnum(card['coefs'][0])]
            T.check(match_any(snaps, ev, ('total', line), want),
                    'main %d тотал %s: DOM %s, у нас %s' % (ev, line, want, e['markets'].get(('total', line))), 'total (главная)')
            if card['lines']:
                ours = sorted(k[1] for k, v in e['markets'].items() if k[0] == 'total' and v[0] and v[1])
                T.check(any(sorted(k[1] for k, v in s[ev]['markets'].items()
                                   if k[0] == 'total' and v[0] and v[1]) == sorted(card['lines'])
                            for s in snaps if ev in s),
                        'main %d список линий тотала: DOM %s, у нас %s' % (ev, card['lines'], ours), 'список линий тотала')
        if not e['live'] and foot and foot[0].startswith('Сегодня'):
            hhmm = foot[0].split()[-1]
            ours = datetime.datetime.fromtimestamp(e['start_ts'], MSK)
            T.check(ours.strftime('%H:%M') == hhmm and ours.date() == datetime.date(2026, 11, 22),
                    'main %d время: DOM %s, у нас %s' % (ev, foot[0], ours), 'время начала')
            if len(foot) > 1 and foot[1].startswith('+'):
                T.check(int(foot[1][1:]) == e['count_add_line'] - 1,
                        'main %d +N: DOM %s, count_add_line %s' % (ev, foot[1], e['count_add_line']), '+N (число рынков)')
    assert n_fb >= 30, n_fb
    return n_fb


def test_match_17134546(frames, T):
    main, snaps = states_at(frames, LINE_SAVED)
    e = main[17134546]
    assert (e['home'], e['away'], e['league'], e['country']) == ('Даллас', 'Портленд', 'MLS', 'США'), e
    assert e['live'] and e['url'].endswith('/stavki/event/17134546')
    m = e['markets']
    # то, что показано на странице линии футбола для этого матча
    assert m[('1x2', None)] == [None, 12.0, 78.0]          # «- 12.0 78.0»
    assert m[('ah', -2.5)] == [2.95, 1.35]                 # «2.95  - 2.5 +  1.35»
    assert m[('total', 2.5)] == [1.57, 2.40]               # «2.40  2.5  1.57» (М слева, Б справа)
    T.ok += 3
    T.by['17134546'] = 3


def test_prematch_consistency(frames):
    L = W.WinlineLine()
    for t, b in frames:
        if t > LINE_SAVED:
            break
        L.feed(b)
    pm = L.football(live=False)
    assert len(pm) > 1000, len(pm)
    mono_ok = mono_all = 0
    dnb_ok = dnb_all = 0
    for e in pm:
        ah = sorted((line, v) for (fam, line), v in e['markets'].items() if fam == 'ah' and None not in v)
        if len(ah) >= 2:
            # если знак линии по favorite верен, кф хозяев падает с ростом форы хозяев, кф гостей растёт
            mono_all += 1
            mono_ok += all(a[1][0] >= b[1][0] and a[1][1] <= b[1][1] for a, b in zip(ah, ah[1:]))
        x = e['markets'].get(('1x2', None))
        v = e['markets'].get(('ah', 0.0))
        if x and v and None not in x and None not in v:
            dnb_all += 1
            p1, p2 = 1 / x[0], 1 / x[2]
            dnb_home = 1 / v[0] / (1 / v[0] + 1 / v[1])
            dnb_ok += abs(dnb_home - p1 / (p1 + p2)) < 0.04
    print('  прематч: футбольных событий %d; события, где кф форы монотонны по линии (знак по favorite '
          'верен): %d из %d; фора 0 ≈ ставка без ничьей из 1X2 (±4%%): %d из %d'
          % (len(pm), mono_ok, mono_all, dnb_ok, dnb_all))
    assert mono_all > 500 and mono_ok / mono_all > 0.99
    assert dnb_all > 500 and dnb_ok / dnb_all > 0.97


def main():
    frames = load_frames()
    print('1) разбор всех кадров')
    test_frames_parse(frames)
    T = Tally()
    print('2) страница линии футбола (line.html)')
    test_line_page(frames, T)
    print('3) главная страница (match.html)')
    n_fb = test_main_page(frames, T)
    print('  футбольных мини-карточек: %d' % n_fb)
    print('4) матч 17134546')
    test_match_17134546(frames, T)
    print('5) согласованность прематча')
    test_prematch_consistency(frames)
    print()
    print('Совпало значений со страницами: %d' % T.ok)
    for k, v in sorted(T.by.items()):
        print('   %-26s %d' % (k, v))
    if T.fail:
        print('НЕ СОВПАЛО: %d' % len(T.fail))
        for f in T.fail:
            print('  ', f)
    assert not T.fail, 'есть расхождения'
    print('ИТОГ: всё сошлось')


if __name__ == '__main__':
    main()

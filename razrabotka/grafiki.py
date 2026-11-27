"""Графики по отчёту владельца — для чата (владелец 28.11: «графики только для способов, которые я вижу в программе», а
испытываемые — «тут в чате»; «2 графика по одному способу в 1, 2 полоски разными цветами»).
Запуск: python3 razrabotka/grafiki.py <report.json> <папка> [все|скрытые|видимые]   (по умолчанию — скрытые)
Данные — та же `charts_data`, что у окна программы (ставки по порядку расчёта, по 100 ₽; итог и после налога 13% с каждого
выигрыша). Картинка — SVG (без сторонних пакетов), PNG — снимком встроенного браузера (Playwright)."""
import json, sys, pathlib, math, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import stavki as S

BG, INK, INK2, GRID, AXIS = '#191919', '#efefef', '#9c9c9c', '#303030', '#474747'
TOT, TAX, WIN, LOSS, PUSH = '#338ced', '#e76624', '#0aac23', '#eb6263', '#9c9c9c'
COL = {'w': WIN, 'l': LOSS, 'p': PUSH}


def esc(t):
    return str(t).replace('&', '&amp;').replace('<', '&lt;')


def fmt(v):
    return ('+' if v > 0 else ('−' if v < 0 else '')) + f'{abs(round(v)):,}'.replace(',', ' ') + ' ₽'


def ticks(lo, hi, k=6):
    raw = max(hi - lo, 1) / k
    mag = 10 ** math.floor(math.log10(raw))
    st = next((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), 10 * mag)
    a, b = math.floor(lo / st) * st, math.ceil(hi / st) * st
    return [a + i * st for i in range(int(round((b - a) / st)) + 1)]


def svg(it, made):
    s_, n = it['s'], len(it['s'])
    tot, tax, a, b = [0], [0], 0, 0
    for r, rub, _ in s_:
        a += rub
        b += rub * 0.87 if rub > 0 else rub
        tot.append(a)
        tax.append(b)
    W = 1100 if n <= 40 else min(2400, 900 + n * 2.2)
    pl, pr, pt, ph = 70, 120, 150, 330
    H = pt + ph + 70
    yt = ticks(min(tot + tax + [0]), max(tot + tax + [0]))
    lo, hi = yt[0], yt[-1]
    pw = W - pl - pr
    X = lambda i: pl + pw * i / max(n, 1)
    Y = lambda v: pt + ph * (1 - (v - lo) / ((hi - lo) or 1))
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H}" font-family="Inter, Segoe UI, Arial, sans-serif">',
         f'<rect width="100%" height="100%" fill="{BG}"/>',
         f'<text x="16" y="34" fill="{INK}" font-size="22" font-weight="700">{esc(it["title"])}</text>',
         f'<text x="16" y="58" fill="{INK2}" font-size="13">{esc(it["desc"])}</text>',
         f'<text x="16" y="84" fill="{INK}" font-size="14">Рассчитано {n}: <tspan fill="{WIN}">✓ {it["w"]}</tspan> · '
         f'<tspan fill="{LOSS}">✗ {it["l"]}</tspan> · ↩ {it["p"]}' + (f' · ещё ждут расчёта {it["open"]}' if it['open'] else '')
         + (f' · CLV {it["clv"]:+.1f}% по {it["clv_n"]}' if it['clv'] is not None else '') + f'   ·   отчёт {esc(made)}</text>',
         f'<rect x="16" y="102" width="20" height="3" rx="1.5" fill="{TOT}"/><text x="42" y="108" fill="{INK}" font-size="14">Итог '
         f'<tspan font-weight="700">{fmt(tot[-1])}</tspan></text>',
         f'<rect x="230" y="102" width="20" height="3" rx="1.5" fill="{TAX}"/><text x="256" y="108" fill="{INK}" font-size="14">После налога 13% '
         f'<tspan font-weight="700">{fmt(tax[-1])}</tspan></text>',
         f'<text x="16" y="132" fill="{INK2}" font-size="12">цвет номера ставки: <tspan fill="{WIN}">зелёный — выигрыш</tspan>, '
         f'<tspan fill="{LOSS}">красный — проигрыш</tspan>, серый — возврат</text>']
    for t in yt:
        o.append(f'<line x1="{pl}" x2="{pl + pw}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="{AXIS if t == 0 else GRID}"/>'
                 f'<text x="{pl - 8}" y="{Y(t) + 4:.1f}" fill="{INK2}" font-size="12" text-anchor="end">{fmt(t)[:-2]}</text>')
    for arr, c in ((tax, TAX), (tot, TOT)):
        o.append(f'<polyline points="{" ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(arr))}" fill="none" stroke="{c}" '
                 f'stroke-width="2" stroke-linejoin="round"/>')
    for arr, c in ((tot, TOT), (tax, TAX)):
        o.append(f'<circle cx="{X(n):.1f}" cy="{Y(arr[-1]):.1f}" r="4.5" fill="{c}" stroke="{BG}" stroke-width="2"/>'
                 f'<text x="{X(n) + 9:.1f}" y="{Y(arr[-1]) + 5:.1f}" fill="{INK}" font-size="13" font-weight="700">{fmt(arr[-1])}</text>')
    by = pt + ph + 4
    every = max(1, math.ceil(n / max(1, int(pw // 28))))
    step = 1 if every <= 1 else next((v for v in (2, 5, 10, 20, 25, 50, 100) if v >= every), 100)
    bw = max(1.5, pw / max(n, 1) * 0.8)
    for i in range(1, n + 1):
        c = COL[s_[i - 1][0]]
        o.append(f'<rect x="{X(i) - bw / 2:.1f}" y="{by}" width="{bw:.1f}" height="7" fill="{c}"/>')
        if step == 1 or i % step == 0 or i == 1:
            o.append(f'<text x="{X(i):.1f}" y="{by + 22}" fill="{c}" font-size="12" font-weight="700" text-anchor="middle">{i}</text>')
    o.append(f'<text x="{pl + pw / 2:.0f}" y="{H - 10}" fill="{INK2}" font-size="12" text-anchor="middle">ставки по порядку расчёта'
             + (f' · номер подписан у каждой {step}-й, цветная метка — у каждой ставки' if step > 1 else '') + '</text></svg>')
    return '\n'.join(o), W, H


def main(rep, out, which='скрытые'):
    r = json.load(open(rep, encoding='utf-8'))
    S.HERE = pathlib.Path(tempfile.mkdtemp())
    con = S.db_open()
    for t, rows in (('paper2', r['paper2']), ('expr', (r.get('expr') or {}).get('rows') or [])):
        cols = [c[1] for c in con.execute(f'PRAGMA table_info({t})')]
        for x in rows:
            ks = [k for k in x if k in cols]
            con.execute(f"INSERT INTO {t} ({','.join(ks)}) VALUES ({','.join('?' * len(ks))})", [x[k] for k in ks])
    con.commit()
    items = [x for x in S.charts_data(con, 100) if x['n']
             and (which == 'все' or (which == 'видимые') == x['visible'])]
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    jobs = []
    for k, it in enumerate(items, 1):
        sv, W, H = svg(it, r.get('made', ''))
        p = out / f'grafik_{k:02d}_{it["code"]}.svg'
        p.write_text(sv, encoding='utf-8')
        jobs.append((p, W, H))
        print(it['code'], it['title'], it['n'], 'итог', it['tot'], 'после налога', it['tax'], 'CLV', it['clv'])
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        br = pw.chromium.launch(executable_path='/opt/pw-browsers/chromium')
        for p, W, H in jobs:
            pg = br.new_page(viewport={'width': int(W), 'height': int(H)}, device_scale_factor=2)
            pg.set_content(f'<html><body style="margin:0;background:{BG}">{p.read_text(encoding="utf-8")}</body></html>')
            pg.screenshot(path=str(p.with_suffix('.png')))
            pg.close()
        br.close()


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else 'скрытые')
